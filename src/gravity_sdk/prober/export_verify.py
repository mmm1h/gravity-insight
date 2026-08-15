"""One-shot online verification for cataloged Gravity export routes.

This module is intentionally separate from the executable export registry.  It
can observe an unverified catalog route, but it cannot promote that route or
bypass the contracted file schema.  Evidence contains shapes and file metadata
only; response values and tabular row values are never persisted.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import importlib
import json
from pathlib import Path
import time
from typing import Any, Mapping, Sequence
from urllib.parse import urlsplit
import zipfile

import requests

from gravity_sdk import runtime as tool_runtime
from gravity_sdk.paths import CONTRACT_ROOT, TMP_ROOT

from .core import REPO_ROOT
from .privacy import response_schema_sketch
from .transport import RecordingSession, RequestDiscipline, build_runtime


EXPORT_CONTRACT_PATH = CONTRACT_ROOT / "exports" / "routes-v1.json"
DEFAULT_OUTPUT_ROOT = TMP_ROOT / "codex" / "gi-export-verify"
MAX_CREATION_REQUESTS = 12
MIN_POLL_INTERVAL_SECONDS = 2.0
MAX_TASK_SECONDS = 300.0
_SUCCESS_CODES = frozenset({0, 200, "0", "200", None})
_NEVER_CALL = frozenset(
    {
        "export.subscribe.start",
        "export.promotion.click_url.start",
        "export.openapi.event.submit",
        "export.openapi.event.result",
    }
)
_READY_STATES = frozenset({2, "2", "ready", "success", "completed"})
_FAILED_STATES = frozenset({3, 5, "3", "5", "failed", "expired"})


def _sdk_module(name: str) -> Any:
    base = tool_runtime._sdk_module().__name__
    return importlib.import_module(f"{base}.{name}")


def load_catalog(path: Path = EXPORT_CONTRACT_PATH) -> dict[str, Mapping[str, Any]]:
    document = json.loads(path.read_text(encoding="utf-8"))
    routes = document.get("routes") if isinstance(document, Mapping) else None
    if not isinstance(routes, list):
        raise ValueError("export route catalog requires a routes array")
    result: dict[str, Mapping[str, Any]] = {}
    for value in routes:
        if not isinstance(value, Mapping):
            raise ValueError("export route entries must be objects")
        operation_id = value.get("operation_id")
        if not isinstance(operation_id, str) or operation_id in result:
            raise ValueError("export route operation_id is missing or duplicated")
        result[operation_id] = value
    if len(result) != 22:
        raise ValueError("export verification requires the 22-route catalog")
    return result


def validate_plan_item(
    item: Mapping[str, Any],
    catalog: Mapping[str, Mapping[str, Any]],
) -> Mapping[str, Any]:
    operation_id = item.get("operation_id")
    if not isinstance(operation_id, str) or operation_id not in catalog:
        raise ValueError("verification plan references an unknown export operation")
    contract = catalog[operation_id]
    called = item.get("call", True)
    if not isinstance(called, bool):
        raise ValueError("verification plan call must be boolean")
    if not called:
        reason = item.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("skipped verification items require a reason")
        return contract
    if operation_id in _NEVER_CALL:
        raise ValueError(f"verification policy forbids calling {operation_id}")
    if contract.get("method") == "UNKNOWN":
        raise ValueError("verification cannot guess an UNKNOWN HTTP method")
    if item.get("method") != contract.get("method"):
        raise ValueError("verification method differs from the route catalog")
    if item.get("path") != contract.get("path"):
        raise ValueError("verification path differs from the route catalog")
    if item.get("effect") != contract.get("effect"):
        raise ValueError("verification effect differs from the route catalog")
    payload = item.get("request")
    if not isinstance(payload, Mapping):
        raise ValueError("called verification items require an object request")
    if contract.get("effect") not in {"export_job_create", "export_status"}:
        raise ValueError("this verifier only calls create or status-like routes")
    return contract


class ExportVerificationRunner:
    def __init__(
        self,
        client: Any,
        runtime: Any,
        *,
        output_root: Path = DEFAULT_OUTPUT_ROOT,
        max_creation_requests: int = MAX_CREATION_REQUESTS,
        poll_interval_seconds: float = MIN_POLL_INTERVAL_SECONDS,
        task_timeout_seconds: float = MAX_TASK_SECONDS,
        monotonic_clock: Any = time.monotonic,
        sleeper: Any = time.sleep,
    ) -> None:
        if not 1 <= max_creation_requests <= MAX_CREATION_REQUESTS:
            raise ValueError("export verification task budget must be between 1 and 12")
        if poll_interval_seconds < MIN_POLL_INTERVAL_SECONDS:
            raise ValueError("export verification polling interval must be at least 2 seconds")
        if not 0 < task_timeout_seconds <= MAX_TASK_SECONDS:
            raise ValueError("export verification task timeout must be at most 5 minutes")
        self.client = client
        self.runtime = runtime
        self.output_root = output_root.resolve()
        self.max_creation_requests = max_creation_requests
        self.poll_interval_seconds = poll_interval_seconds
        self.task_timeout_seconds = task_timeout_seconds
        self.clock = monotonic_clock
        self.sleeper = sleeper
        self.catalog = load_catalog()
        self.creation_requests = 0
        self.confirmed_tasks = 0

    def run(self, plan: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        self.output_root.mkdir(parents=True, exist_ok=True)
        results: list[dict[str, Any]] = []
        for raw in plan:
            if not isinstance(raw, Mapping):
                raise ValueError("verification plan items must be objects")
            contract = validate_plan_item(raw, self.catalog)
            if not raw.get("call", True):
                results.append(
                    {
                        "operation_id": raw["operation_id"],
                        "called": False,
                        "reason": str(raw["reason"]),
                    }
                )
                continue
            try:
                if contract["effect"] == "export_status":
                    results.append(self._run_status_like(raw, contract))
                else:
                    results.append(self._run_create(raw, contract))
            except Exception as exc:
                results.append(
                    {
                        "operation_id": raw["operation_id"],
                        "called": True,
                        "ok": False,
                        "error_type": type(exc).__name__,
                        "error_code": str(getattr(exc, "code", "PROBE_FAILED"))[:64],
                    }
                )
        return {
            "schema_version": "gravity-insight.export-verification.v1",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "creation_request_count": self.creation_requests,
            "confirmed_task_count": self.confirmed_tasks,
            "creation_request_limit": self.max_creation_requests,
            "results": results,
        }

    def _run_status_like(
        self,
        item: Mapping[str, Any],
        contract: Mapping[str, Any],
    ) -> dict[str, Any]:
        started = self.clock()
        _, _, response = self._call_contract(item, contract)
        return {
            "operation_id": item["operation_id"],
            "called": True,
            "ok": response["semantic_success"],
            "method": item["method"],
            "request_shape": response_schema_sketch(item["request"]),
            "http_status": response["http_status"],
            "semantic_code": response["semantic_code"],
            "response_shape": response["response_shape"],
            "elapsed_seconds": round(self.clock() - started, 3),
        }

    def _run_create(
        self,
        item: Mapping[str, Any],
        contract: Mapping[str, Any],
    ) -> dict[str, Any]:
        request = self._resolved_request(item)
        if self.creation_requests >= self.max_creation_requests:
            raise RuntimeError("export verification creation budget exhausted")
        self.creation_requests += 1
        started = self.clock()
        _, _, response = self._call_contract(item, contract, request=request)
        job_id, job_id_path = _task_id(response["payload"])
        result: dict[str, Any] = {
            "operation_id": item["operation_id"],
            "called": True,
            "ok": response["semantic_success"] and job_id is not None,
            "method": item["method"],
            "request_shape": response_schema_sketch(request),
            "http_status": response["http_status"],
            "semantic_code": response["semantic_code"],
            "response_shape": response["response_shape"],
            "task_id_path": job_id_path,
            "task_id_fingerprint": _fingerprint(job_id) if job_id is not None else None,
        }
        if job_id is None:
            result["elapsed_seconds"] = round(self.clock() - started, 3)
            return result
        self.confirmed_tasks += 1
        polling = self._poll(str(job_id), contract)
        result.update(polling["evidence"])
        result["ok"] = False
        if polling["ready"]:
            result["file"] = self._download_and_inspect(
                str(job_id),
                contract,
                polling["payload"],
                polling["authorization"],
                polling["policy"],
            )
            result["ok"] = bool(result["file"].get("privacy_gate_passed"))
        result["elapsed_seconds"] = round(self.clock() - started, 3)
        return result

    def _poll(
        self,
        job_id: str,
        create_contract: Mapping[str, Any],
    ) -> dict[str, Any]:
        progress = self.catalog["export.task.progress"]
        deadline = self.clock() + self.task_timeout_seconds
        history: list[Any] = []
        polls = 0
        last: tuple[Any, Any, dict[str, Any]] | None = None
        while self.clock() < deadline:
            self.sleeper(self.poll_interval_seconds)
            payload = {"task_id": int(job_id) if job_id.isdecimal() else job_id}
            authorization, policy, response = self._call(
                operation_id="export.task.progress",
                effect="export_status",
                method=str(progress["method"]),
                path=str(progress["path"]),
                request_location=str(progress["request"]["location"]),
                payload=payload,
            )
            polls += 1
            raw_state = _first_path(response["payload"], ("data.status", "status"))
            history.append(raw_state)
            last = (authorization, policy, response)
            normalized = raw_state.casefold() if isinstance(raw_state, str) else raw_state
            if normalized in _READY_STATES or normalized in _FAILED_STATES:
                break
        if last is None:
            raise RuntimeError("export task polling produced no response")
        authorization, policy, response = last
        raw_state = history[-1]
        normalized = raw_state.casefold() if isinstance(raw_state, str) else raw_state
        return {
            "ready": normalized in _READY_STATES,
            "payload": response["payload"],
            "authorization": authorization,
            "policy": policy,
            "evidence": {
                "poll_count": polls,
                "state_history": history,
                "terminal_state": raw_state,
                "status_response_shape": response["response_shape"],
            },
        }

    def _call_contract(
        self,
        item: Mapping[str, Any],
        contract: Mapping[str, Any],
        *,
        request: Mapping[str, Any] | None = None,
    ) -> tuple[Any, Any, dict[str, Any]]:
        return self._call(
            operation_id=str(item["operation_id"]),
            effect=str(item["effect"]),
            method=str(item["method"]),
            path=str(item["path"]),
            request_location=str(contract["request"]["location"]),
            payload=request if request is not None else item["request"],
        )

    def _resolved_request(self, item: Mapping[str, Any]) -> Mapping[str, Any]:
        request = json.loads(
            json.dumps(item["request"], ensure_ascii=False, allow_nan=False)
        )
        if "$first_segment_client_id" not in _nested_strings(request):
            return request
        resolver = item.get("resolve_client_id")
        if not isinstance(resolver, Mapping):
            raise ValueError("client_id placeholder requires resolve_client_id")
        app_id = resolver.get("app_id")
        segment_id = resolver.get("segment_id")
        if not isinstance(app_id, str) or not isinstance(segment_id, str):
            raise ValueError("client_id resolver requires string app_id and segment_id")
        inputs = {"app_id": app_id, "segment_id": segment_id}
        try:
            result = tool_runtime.to_jsonable(
                self.client.read("analysis.segment.user_detail.list", inputs)
            )
        except Exception as exc:
            if (
                type(exc).__name__ != "InputValidationError"
                or "required live field metadata is unavailable" not in str(exc)
            ):
                raise
            result = self._read_segment_member_for_probe(inputs)
        client_id = _first_list_value(result, "data.list", "ClientID")
        if not isinstance(client_id, (str, int)) or not str(client_id).strip():
            raise ValueError("client_id resolver found no contracted segment member")
        return _replace_nested_string(
            request,
            "$first_segment_client_id",
            str(client_id),
        )

    def _read_segment_member_for_probe(
        self,
        inputs: Mapping[str, str],
    ) -> Mapping[str, Any]:
        """Use the stable read contract when optional field metadata is unavailable."""

        executor = self.client._executor
        operation_id = "analysis.segment.user_detail.list"
        operation = executor._policy.authorize_operation(operation_id)
        values = operation.validate_inputs(inputs)
        authorization = executor._policy._prepare_request(operation_id, values)
        response = executor._transport.request(
            authorization.method,
            authorization.path,
            operation=operation,
            query=authorization.query,
            body=authorization.body,
            authorization=authorization,
        )
        payload = getattr(response, "payload", None)
        if not isinstance(payload, Mapping) or payload.get("code") not in _SUCCESS_CODES:
            raise ValueError("segment member probe did not return a successful envelope")
        return payload

    def _call(
        self,
        *,
        operation_id: str,
        effect: str,
        method: str,
        path: str,
        request_location: str,
        payload: Mapping[str, Any],
    ) -> tuple[Any, Any, dict[str, Any]]:
        export_policy = _sdk_module("export_policy")
        registry_module = _sdk_module("registry")
        route = export_policy.EffectRoute(
            operation_id=operation_id,
            effect=effect,
            method=method,
            path=path,
            request_location=request_location,
            allowed_fields=frozenset(str(key) for key in payload),
            required_fields=frozenset(str(key) for key in payload),
            fixed_fields={},
            executable=True,
            contract_status="verified",
        )
        policy = registry_module.PolicyEngine(
            self.client._registry,
            allow_experimental=True,
            effect_routes=(route,),
        )
        authorization = policy._prepare_effect_request(operation_id, effect, payload)
        response = self.runtime._request_insight(
            method,
            path,
            policy_authorization=authorization,
            params=dict(authorization.query),
            json_body=dict(authorization.body) or None,
            semantic_auth_codes=(2001, 10000, 10001),
            timeout=120.0,
            attempts=1,
        )
        raw = getattr(response, "payload", None)
        code = raw.get("code") if isinstance(raw, Mapping) else None
        return authorization, policy, {
            "http_status": int(getattr(response, "status_code", 0)),
            "semantic_code": code,
            "semantic_success": (
                200 <= int(getattr(response, "status_code", 0)) < 300
                and isinstance(raw, Mapping)
                and code in _SUCCESS_CODES
            ),
            "payload": raw,
            "response_shape": response_schema_sketch(raw),
        }

    def _download_and_inspect(
        self,
        job_id: str,
        create_contract: Mapping[str, Any],
        status_payload: Mapping[str, Any],
        status_authorization: Any,
        policy: Any,
    ) -> dict[str, Any]:
        url = _first_path(status_payload, ("data.download_url", "download_url"))
        if not isinstance(url, str) or not url:
            raise RuntimeError("READY status omitted download_url")
        parsed = urlsplit(url)
        extension, mime_type, magic = _file_protocol(parsed.path)
        trusted = self.catalog["export.material.report.start"]["privacy"]
        hosts = frozenset(str(value) for value in trusted["allowed_hosts"])
        prefixes = {
            str(host): tuple(str(value) for value in values)
            for host, values in trusted["allowed_path_prefixes"].items()
        }
        if parsed.scheme != "https" or parsed.hostname not in hosts:
            raise RuntimeError("export download host is outside the verified allowlist")
        if not any(
            parsed.path.startswith(prefix)
            for prefix in prefixes.get(parsed.hostname, ())
        ):
            raise RuntimeError("export download path is outside the verified tenant prefix")

        blob = _sdk_module("blob")
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=300)
        authorization_scope = (
            f"export_probe:{create_contract['operation_id']}:{job_id}"
        )
        receipt = policy.authorize_blob_download(
            status_authorization,
            job_id=job_id,
            url=url,
            declared_path=parsed.path,
            expires_at=expires_at,
            authorization_scope=authorization_scope,
        )
        source = blob.AuthorizedBlobSource(
            url=url,
            declared_path=parsed.path,
            expires_at=expires_at,
            authorization_scope=authorization_scope,
            job_id=job_id,
            declared_mime_type=mime_type,
            effect_receipt=receipt,
        )
        blob_policy = blob.BlobPolicy(
            allowed_extensions=frozenset({extension}),
            allowed_mime_types=frozenset({mime_type}),
            magic_signatures={extension: (blob.MagicSignature(0, magic),)},
            mime_types_by_extension={extension: (mime_type,)},
            max_declared_size_bytes=100 * 1024 * 1024,
            max_stream_size_bytes=100 * 1024 * 1024,
            allowed_hosts=hosts,
            allowed_redirect_hosts=frozenset(),
            allowed_path_prefixes=prefixes,
            archive_policy=blob.ArchivePolicy(
                enabled=extension == ".xlsx",
                max_uncompressed_size_bytes=128 * 1024 * 1024,
                max_entries=1_000,
                max_nested_depth=0,
                max_compression_ratio=100.0,
            ),
            destination_root=self.output_root,
            temporary_root=self.output_root,
            overwrite_policy="deny",
            require_effect_receipt=True,
        )
        destination = (
            create_contract["operation_id"].replace(".", "-") + extension
        )
        path = self.output_root / destination
        try:
            downloaded = blob.SafeBlobTransfer().download(
                source,
                destination,
                blob_policy,
            )
            schema, rows, worksheet_count = _inspect_table(path, extension)
            narrow_rejected, exact_accepted = validate_privacy_gate(
                schema,
                classification=str(create_contract["privacy"]["classification"]),
            )
            return {
                "format": extension.lstrip("."),
                "mime_type": downloaded.content_type,
                "size_bytes": downloaded.size_bytes,
                "rows": rows,
                "columns": list(schema),
                "column_count": len(schema),
                "worksheet_count": worksheet_count,
                "etag_present": downloaded.etag is not None,
                "last_modified_present": downloaded.last_modified is not None,
                "narrow_allowlist_rejected": narrow_rejected,
                "exact_allowlist_accepted": exact_accepted,
                "privacy_gate_passed": narrow_rejected and exact_accepted,
                "temporary_file_deleted": True,
            }
        finally:
            path.unlink(missing_ok=True)


def validate_privacy_gate(
    schema: tuple[str, ...],
    *,
    classification: str = "user_level",
) -> tuple[bool, bool]:
    if not schema:
        return False, False
    models = _sdk_module("export_models")
    privacy = _sdk_module("export_privacy")
    narrow = schema[:-1] if len(schema) > 1 else ("__probe_no_actual_column__",)
    narrow_contract = models.ExportPrivacyContract(
        allowed_columns=narrow,
        required_columns=(),
        classification=classification,
        format="xlsx",
    )
    narrow_rejected = False
    try:
        privacy._validate_actual_schema(schema, narrow_contract)
    except Exception as exc:
        narrow_rejected = getattr(exc, "code", None) == "EXPORT_SCHEMA_MISMATCH"
    exact_contract = models.ExportPrivacyContract(
        allowed_columns=schema,
        required_columns=schema,
        classification=classification,
        format="xlsx",
    )
    exact_accepted = True
    try:
        privacy._validate_actual_schema(schema, exact_contract)
    except Exception:
        exact_accepted = False
    return narrow_rejected, exact_accepted


def _inspect_table(path: Path, extension: str) -> tuple[tuple[str, ...], int, int]:
    if extension != ".xlsx":
        raise ValueError("online export verification currently supports XLSX only")
    privacy = _sdk_module("export_privacy")
    with zipfile.ZipFile(path) as archive:
        worksheets = privacy._xlsx_worksheet_names(archive)
        shared = privacy._xlsx_shared_strings(archive)
        observed = [
            privacy._xlsx_sheet_schema(archive, worksheet, shared)
            for worksheet in worksheets
        ]
    schemas = [item[0] for item in observed]
    if any(schema != schemas[0] for schema in schemas[1:]):
        raise ValueError("export worksheets do not share one schema")
    return schemas[0], sum(item[1] for item in observed), len(worksheets)


def _file_protocol(path: str) -> tuple[str, str, bytes]:
    lowered = path.casefold()
    if lowered.endswith(".xlsx"):
        return (
            ".xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            b"PK\x03\x04",
        )
    raise ValueError("export download has an unverified file extension")


def _task_id(payload: Any) -> tuple[str | int | None, str | None]:
    if not isinstance(payload, Mapping):
        return None, None
    for path in ("data.task_id", "task_id", "data.id", "id", "data"):
        value = _first_path(payload, (path,))
        if isinstance(value, bool) or not isinstance(value, (str, int)):
            continue
        if str(value).strip():
            return value, path
    return None, None


def _first_path(value: Any, paths: Sequence[str]) -> Any:
    for path in paths:
        current = value
        for part in path.split("."):
            if not isinstance(current, Mapping) or part not in current:
                current = None
                break
            current = current[part]
        if current is not None:
            return current
    return None


def _first_list_value(value: Any, path: str, key: str) -> Any:
    rows = _first_path(value, (path,))
    if not isinstance(rows, list):
        return None
    for row in rows:
        if isinstance(row, Mapping) and row.get(key) not in (None, ""):
            return row[key]
    return None


def _nested_strings(value: Any) -> set[str]:
    if isinstance(value, str):
        return {value}
    if isinstance(value, Mapping):
        result: set[str] = set()
        for item in value.values():
            result.update(_nested_strings(item))
        return result
    if isinstance(value, list):
        result = set()
        for item in value:
            result.update(_nested_strings(item))
        return result
    return set()


def _replace_nested_string(value: Any, target: str, replacement: str) -> Any:
    if value == target:
        return replacement
    if isinstance(value, Mapping):
        return {
            str(key): _replace_nested_string(item, target, replacement)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_replace_nested_string(item, target, replacement) for item in value]
    return value


def _fingerprint(value: str | int) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    temporary.replace(path)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a bounded, metadata-only verification of export routes."
    )
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-tasks", type=int, default=MAX_CREATION_REQUESTS)
    parser.add_argument("--interval", type=float, default=2.0)
    parser.add_argument("--timeout", type=float, default=300.0)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    document = json.loads(args.plan.read_text(encoding="utf-8"))
    plan = document.get("routes") if isinstance(document, Mapping) else None
    if not isinstance(plan, list):
        raise ValueError("verification plan requires a routes array")
    discipline = RequestDiscipline(
        interval_seconds=0.31,
        request_limit=200,
        hard_limit=200,
    )
    recording = RecordingSession(requests.Session(), discipline)
    runtime = build_runtime(recording)
    client = tool_runtime._sdk_module().GravityInsightClient.from_env(
        runtime=runtime,
        allow_experimental=True,
        attempts=1,
    )
    runner = ExportVerificationRunner(
        client,
        runtime,
        output_root=args.output.parent,
        max_creation_requests=args.max_tasks,
        poll_interval_seconds=args.interval,
        task_timeout_seconds=args.timeout,
    )
    result = runner.run(plan)
    result["http_request_count"] = discipline.total
    result["http_failure_count"] = discipline.failed
    _write_json(args.output, result)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
