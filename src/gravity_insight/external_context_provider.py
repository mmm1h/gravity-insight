"""Agent-facing facade for one explicitly bound external Context Provider."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from .provider_rpc_guard import ProviderRpcGuard
from .provider_rpc_transport import (
    ProviderTransport,
    ProviderTransportError,
    SubprocessProviderTransport,
    _close_process_streams,
    _join_capture,
    _json_pointer,
    _launch_subprocess,
    _monitor_process,
    _real_directory,
    _real_executable,
    _sanitized_environment,
    _start_capture,
    _terminate_process_tree,
    _validate_argument_path,
    compile_external_provider,
)


_COMMAND_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,255}$")
_COMMAND_AMBIENT = ("PATH", "HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "XDG_CONFIG_HOME")
_CREDENTIAL_ARGUMENTS = frozenset({"--password", "--secret", "--cookie", "--authorization", "--api-key", "--auth-token", "--access-token"})


class CommandProviderTransport:
    """Bounded descriptor-driven argv/JSON adapter over the subprocess guard."""

    kind = "subprocess"

    def __init__(
        self,
        descriptor: Mapping[str, Any],
        *,
        work_root: str | Path,
        environment: Mapping[str, str] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._contract = compile_external_provider(descriptor)["contract"]
        binding = self._contract["deployment"]["subprocess"]
        if not isinstance(binding, Mapping):
            raise ValueError("Command Provider binding is missing")
        root = _real_directory(Path(work_root), "Provider work root")
        working = _real_directory(Path(binding["working_directory"]), "Provider cwd")
        try:
            working.relative_to(root)
        except ValueError as exc:
            raise ValueError("Provider cwd escapes its work root") from exc
        self._config = _validate_command_contract(self._contract, binding, root)
        self._executable = str(binding["executable"])
        self._base_arguments = list(binding["arguments"])
        self._working_directory = working
        self._environment = _command_environment(environment)
        self._clock = clock
        self._processes: dict[str, subprocess.Popen[bytes]] = {}
        self._degradations: dict[str, dict[str, Any]] = {}
        self._guard = threading.Lock()

    def invoke(
        self,
        request: Mapping[str, Any],
        request_bytes: bytes,
        *,
        timeout_ms: int,
        max_output_bytes: int,
        cancellation_grace_ms: int,
        cancel_event: threading.Event,
    ) -> bytes:
        del request_bytes
        request_id = str(request["request_id"])
        with self._guard:
            self._degradations.pop(request_id, None)
        resource_uri = str(request["payload"]["resource_uri"])
        route, segments = _command_route(self._config, resource_uri)
        try:
            executable = str(_real_executable(Path(self._executable)))
        except ValueError:
            return self._gap(request, "source_unavailable", "command_not_found")
        command = [
            executable, *self._base_arguments,
            *_expand_arguments(route["arguments"], segments),
        ]
        try:
            process = self._launch(command, cancellation_grace_ms)
        except ProviderTransportError as exc:
            if exc.reason_code != "PROVIDER_RPC_UNAVAILABLE":
                raise
            return self._gap(request, "source_unavailable", "command_not_found")
        return self._run(
            request, route, process, cancel_event=cancel_event,
            timeout_ms=timeout_ms, max_output_bytes=max_output_bytes,
            cancellation_grace_ms=cancellation_grace_ms,
        )

    def _run(
        self,
        request: Mapping[str, Any],
        route: Mapping[str, Any],
        process: subprocess.Popen[bytes],
        *,
        cancel_event: threading.Event,
        timeout_ms: int,
        max_output_bytes: int,
        cancellation_grace_ms: int,
    ) -> bytes:
        request_id = str(request["request_id"])
        with self._guard:
            self._processes[request_id] = process
        capture = _start_capture(process, max_output_bytes)
        try:
            if process.stdin is None:
                raise OSError("Command source stdin is unavailable")
            process.stdin.close()
            reason = _monitor_process(
                process,
                capture["exceeded"],
                cancel_event,
                timeout_ms=timeout_ms,
                clock=self._clock,
            )
            if reason is not None:
                _terminate_process_tree(
                    process, cancellation_grace_ms
                )
            _join_capture(
                capture, process, cancellation_grace_ms
            )
            if reason is not None:
                raise ProviderTransportError(
                    reason, "Command source did not complete safely"
                )
            if capture["exceeded"].is_set():
                raise ProviderTransportError(
                    "PROVIDER_RPC_OUTPUT_LIMIT", "Command source exceeded output budget"
                )
            return self._process_output(request, route, process, capture)
        except ProviderTransportError:
            raise
        except (OSError, ValueError) as exc:
            _terminate_process_tree(
                process, cancellation_grace_ms
            )
            raise ProviderTransportError(
                "PROVIDER_RPC_UNAVAILABLE", "Command source process I/O failed"
            ) from exc
        finally:
            with self._guard:
                self._processes.pop(request_id, None)
            _close_process_streams(process)

    def _process_output(
        self,
        request: Mapping[str, Any],
        route: Mapping[str, Any],
        process: subprocess.Popen[bytes],
        capture: Mapping[str, Any],
    ) -> bytes:
        if process.returncode != 0:
            kind = _failure_kind(
                route["failure_rules"], process.returncode,
                bytes(capture["stderr"]),
            )
            cause = (
                "resource_unavailable"
                if kind == "resource_unavailable"
                else "command_failed"
            )
            status = "denied" if kind == "resource_unavailable" else "unavailable"
            return self._gap(request, kind, cause, status=status)
        parsed = _strict_json(bytes(capture["stdout"]))
        stale = _stale_cause(
            self._contract["capabilities"]["freshness_model"], route, parsed
        )
        if stale is not None:
            return self._gap(request, "content_stale", stale, status="unsupported")
        with self._guard:
            self._degradations.pop(str(request["request_id"]), None)
        return _success_response(request, self._contract, route, parsed)

    def _gap(
        self,
        request: Mapping[str, Any],
        kind: str,
        cause: str,
        *,
        status: str = "unavailable",
    ) -> bytes:
        request_id = str(request["request_id"])
        resource_uri = str(request["payload"]["resource_uri"])
        degradation = _degradation(self._config, self._contract["authority_ceiling"], kind, cause, resource_uri)
        with self._guard:
            self._degradations[request_id] = degradation
        return _rpc_response(request, status=status, resources=[])

    def enrich_result(self, result: Mapping[str, Any]) -> dict[str, Any]:
        selected = copy.deepcopy(dict(result))
        request_id = selected.get("request_id")
        with self._guard:
            degradation = self._degradations.pop(str(request_id), None)
        expected = {"source_unavailable": "PROVIDER_RPC_UNAVAILABLE", "resource_unavailable": "PROVIDER_RESOURCE_DENIED", "content_stale": "PROVIDER_CAPABILITY_UNSUPPORTED"}
        if degradation is not None and selected.get("reason_codes") != [expected[degradation["kind"]]]:
            degradation = None
        if degradation is None and selected.get("reason_codes") == [
            "PROVIDER_CIRCUIT_OPEN"
        ]:
            degradation = _degradation(self._config, self._contract["authority_ceiling"], "source_unavailable", "circuit_open", "source")
        if degradation is None:
            return selected
        selected["degradation"] = degradation
        return selected

    def _launch(
        self, command: list[str], cancellation_grace_ms: int
    ) -> subprocess.Popen[bytes]:
        return _launch_subprocess(
            command, self._working_directory, self._environment,
            cancellation_grace_ms,
        )

    def cancel(self, request_id: str, *, grace_ms: int) -> None:
        with self._guard:
            process = self._processes.get(request_id)
        if process is not None:
            _terminate_process_tree(process, grace_ms)


def _validate_command_contract(
    contract: Mapping[str, Any], binding: Mapping[str, Any], root: Path
) -> Mapping[str, Any]:
    config = binding.get("command")
    _require(binding.get("protocol") == "command" and isinstance(config, Mapping), "Command Provider routes are missing")
    _require(contract["capabilities"]["operations"] == ["read"], "Command Providers support exact read only")
    _require(contract["authority_ceiling"] in {"declared_intent", "unverified"}, "Command Provider authority exceeds declared intent")
    model = contract["capabilities"]["freshness_model"]
    _require(model in {"content_hash", "ttl", "none"}, "Command Provider freshness model is unsupported")
    routes = config["routes"]
    prefixes = [route["resource_prefix"] for route in routes]
    route_ids = [route["route_id"] for route in routes]
    item_ids = [route["resource"]["item_id"] for route in routes]
    _require(all(len(values) == len(set(values)) for values in (prefixes, route_ids, item_ids)), "Command route identities are duplicated")
    _require(sorted(prefixes) == contract["allowed_resource_prefixes"], "Command routes and allowed prefixes disagree")
    _require(not any(a.startswith(b) or b.startswith(a) for i, a in enumerate(prefixes) for b in prefixes[i + 1:]), "Command route prefixes overlap")
    for argument in binding["arguments"]:
        _validate_literal(str(argument), root)
    for route in routes:
        _validate_command_route(contract, route, model, root)
    return config


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _validate_command_route(
    contract: Mapping[str, Any], route: Mapping[str, Any], model: str, root: Path
) -> None:
    if not route["resource_prefix"].endswith("/"):
        raise ValueError("Command route prefix must end with slash")
    if route["resource"]["resource_type"] not in contract["resource_types"]:
        raise ValueError("Command route resource type is undeclared")
    if (model == "ttl") != isinstance(route["freshness"], Mapping):
        raise ValueError("Command route freshness disagrees with its model")
    for argument in route["arguments"]:
        if "literal" in argument:
            _validate_literal(str(argument["literal"]), root)
            continue
        indices = [argument["uri_path_segment"]] if "uri_path_segment" in argument else argument["uri_path_segments"]
        if any(index >= route["path_segment_count"] for index in indices):
            raise ValueError("Command argument exceeds its URI path shape")


def _validate_literal(value: str, root: Path) -> None:
    if not value or any(character in value for character in ("\x00", "\r", "\n")):
        raise ValueError("Command source literal is unsafe")
    lowered = value.casefold()
    if lowered in _CREDENTIAL_ARGUMENTS or any(lowered.startswith(f"{item}=") for item in _CREDENTIAL_ARGUMENTS):
        raise ValueError("Command source literal names a credential")
    _validate_argument_path(value, root)


def _command_environment(explicit: Mapping[str, str] | None) -> dict[str, str]:
    selected = {key: os.environ[key] for key in _COMMAND_AMBIENT if key in os.environ}
    if explicit is not None:
        selected.update(explicit)
    return _sanitized_environment(selected)


def _command_route(
    config: Mapping[str, Any], resource_uri: str
) -> tuple[Mapping[str, Any], list[str]]:
    routes = [route for route in config["routes"] if resource_uri.startswith(route["resource_prefix"])]
    if len(routes) != 1:
        raise ProviderTransportError("PROVIDER_RPC_RESPONSE_INVALID", "Command resource route is ambiguous")
    route = routes[0]
    segments = resource_uri[len(route["resource_prefix"]):].split("/")
    if len(segments) != route["path_segment_count"] or any(_COMMAND_SEGMENT.fullmatch(item) is None for item in segments):
        raise ProviderTransportError("PROVIDER_RPC_RESPONSE_INVALID", "Command resource shape is invalid")
    return route, segments


def _expand_arguments(arguments: list[Mapping[str, Any]], segments: list[str]) -> list[str]:
    result = []
    for argument in arguments:
        if "literal" in argument:
            result.append(str(argument["literal"]))
        elif "uri_path_segment" in argument:
            result.append(segments[argument["uri_path_segment"]])
        else:
            result.append(argument["separator"].join(segments[index] for index in argument["uri_path_segments"]))
    return result


def _strict_json(content: bytes) -> Any:
    def unique_object(values: list[tuple[str, Any]]) -> dict[str, Any]:
        if len(values) != len({key for key, _value in values}): raise ValueError("duplicate JSON key")
        return dict(values)
    try:
        return json.loads(content.decode("utf-8"), object_pairs_hook=unique_object, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise ProviderTransportError("PROVIDER_RPC_MALFORMED", "Command source output is not strict JSON") from exc


def _failure_kind(rules: list[Mapping[str, Any]], returncode: int, stderr: bytes) -> str:
    try:
        value = _strict_json(stderr)
    except ProviderTransportError:
        return "source_unavailable"
    for rule in rules:
        try:
            matched = returncode in rule["exit_codes"] and _json_pointer(value, rule["json_pointer"]) in rule["equals"]
        except (IndexError, KeyError, TypeError, ValueError):
            matched = False
        if matched:
            return str(rule["kind"])
    return "source_unavailable"


def _stale_cause(model: str, route: Mapping[str, Any], parsed: Any) -> str | None:
    if model == "content_hash":
        return None
    if model == "none":
        return "freshness_unknown"
    try:
        raw = _json_pointer(parsed, route["freshness"]["timestamp_pointer"])
        observed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if observed.tzinfo is None:
            return "freshness_unknown"
        age = (datetime.now(timezone.utc) - observed.astimezone(timezone.utc)).total_seconds()
    except (AttributeError, IndexError, KeyError, TypeError, ValueError, OverflowError):
        return "freshness_unknown"
    return "freshness_unknown" if age < -300 else "freshness_expired" if age > route["freshness"]["max_age_seconds"] else None


def _success_response(
    request: Mapping[str, Any], contract: Mapping[str, Any],
    route: Mapping[str, Any], parsed: Any,
) -> bytes:
    resource = route["resource"]
    try:
        value = _json_pointer(parsed, resource["content_pointer"]) if "content_pointer" in resource else parsed
        content = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (IndexError, KeyError, TypeError, ValueError) as exc:
        raise ProviderTransportError("PROVIDER_RPC_MALFORMED", "Command source output lacks its declared content") from exc
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    item = {
        "uri": request["payload"]["resource_uri"], "title": resource["title"],
        "resource_type": resource["resource_type"], "source_revision": f"sha256:{digest}",
        "item_id": resource["item_id"], "fact_id": resource["fact_id"],
        "entity_refs": copy.deepcopy(resource["entity_refs"]), "valid_time": copy.deepcopy(resource["valid_time"]),
        "effective_range": copy.deepcopy(resource["effective_range"]),
        "observed_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "authority": contract["authority_ceiling"], "freshness": "current", "supersedes": [],
        "sensitivity": resource["sensitivity"],
        "citation": {"path": resource["citation_path"], "line_start": 1, "line_end": max(1, content.count("\n") + 1)},
        "content": content, "content_hash": digest,
    }
    return _rpc_response(request, status="success", resources=[item])


def _rpc_response(
    request: Mapping[str, Any], *, status: str, resources: list[Mapping[str, Any]]
) -> bytes:
    internal = 1 if resources else None
    value = {
        "schema_version": "gravity.provider-rpc-response.v1", "request_id": request["request_id"],
        "status": status, "resources": resources, "next_cursor": None,
        "stats": {"internal_requests": internal, "retries": 0 if resources else None, "cache_hits": 0 if resources else None},
    }
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _degradation(
    config: Mapping[str, Any], ceiling: str, kind: str, cause: str, resource_uri: str
) -> dict[str, Any]:
    selected = config["guidance"][kind]
    missing = resource_uri if kind == "resource_unavailable" else f"freshness:{resource_uri}" if kind == "content_stale" else selected["missing"]
    return {
        "schema_version": "gravity.command-source-degradation.v1", "kind": kind,
        "cause": cause, "missing": missing, "message": selected["message"],
        "user_actions": list(selected["user_actions"]), "continuation": "supplemental_context_only",
        "authority_ceiling": ceiling,
    }

class ExternalContextProvider:
    """Expose read-only Provider operations without binding them to a Skill."""

    def __init__(
        self,
        descriptor: Mapping[str, Any],
        transport: ProviderTransport,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._transport = transport
        self._guard = ProviderRpcGuard(descriptor, transport, clock=clock)

    def describe(self) -> dict[str, Any]:
        return {
            "schema_version": "gravity.external-context-provider-description.v1",
            "status": "success",
            "provider": _public_descriptor(self._guard.descriptor),
            "provider_digest": self._guard.descriptor_digest,
            "provider_internal_io_controlled": False,
            "provider_internal_network": "not_observable",
        }

    def list(
        self,
        *,
        cursor: str | None = None,
        limit: int = 50,
        cancellation: threading.Event | None = None,
    ) -> dict[str, Any]:
        return self._invoke(
            "list", {"cursor": cursor, "limit": limit}, cancellation=cancellation
        )

    def search(
        self,
        query: str,
        *,
        cursor: str | None = None,
        limit: int = 50,
        cancellation: threading.Event | None = None,
    ) -> dict[str, Any]:
        return self._invoke(
            "search",
            {"query": query, "cursor": cursor, "limit": limit},
            cancellation=cancellation,
        )

    def read(
        self,
        resource_uri: str,
        *,
        cancellation: threading.Event | None = None,
    ) -> dict[str, Any]:
        return self._invoke(
            "read", {"resource_uri": resource_uri}, cancellation=cancellation
        )

    def list_changed(
        self,
        since_revision: str,
        *,
        cursor: str | None = None,
        limit: int = 50,
        cancellation: threading.Event | None = None,
    ) -> dict[str, Any]:
        return self._invoke(
            "list_changed",
            {
                "since_revision": since_revision,
                "cursor": cursor,
                "limit": limit,
            },
            cancellation=cancellation,
        )

    def metrics(self) -> dict[str, Any]:
        return self._guard.metrics()

    def _invoke(
        self,
        operation: str,
        payload: Mapping[str, Any],
        *,
        cancellation: threading.Event | None,
    ) -> dict[str, Any]:
        result = self._guard.invoke(operation, payload, cancellation=cancellation)
        enrich = getattr(self._transport, "enrich_result", None)
        return enrich(result) if callable(enrich) else result


def subprocess_context_provider(
    descriptor: Mapping[str, Any],
    *,
    work_root: str | Path,
    environment: Mapping[str, str] | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> ExternalContextProvider:
    contract = compile_external_provider(descriptor)["contract"]
    binding = contract["deployment"]["subprocess"]
    transport_type = (
        CommandProviderTransport
        if isinstance(binding, Mapping) and binding.get("protocol") == "command"
        else SubprocessProviderTransport
    )
    transport = transport_type(
        contract, work_root=work_root, environment=environment, clock=clock
    )
    return ExternalContextProvider(contract, transport, clock=clock)


def _public_descriptor(value: Mapping[str, Any]) -> dict[str, Any]:
    selected = copy.deepcopy(dict(value))
    binding = selected["deployment"].pop("subprocess")
    selected["deployment"]["subprocess_configured"] = binding is not None
    selected["deployment"]["subprocess_argument_count"] = (
        len(binding["arguments"]) if isinstance(binding, Mapping) else 0
    )
    return selected


__all__ = [
    "CommandProviderTransport",
    "ExternalContextProvider",
    "subprocess_context_provider",
]
