"""HTTP observation and request-discipline adapters for online probes."""

from __future__ import annotations

import copy
import importlib
import json
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Callable, Iterator, Mapping
from urllib.parse import urlsplit

from gravity_sdk import runtime as tool_runtime
from gravity_sdk.paths import PROJECT_ROOT

from .privacy import response_schema_sketch


@dataclass
class RequestContext:
    operation_id: str = "unknown"
    family_id: str = "unassigned"
    purpose: str = "probe"


@dataclass
class HttpObservation:
    operation_id: str
    family_id: str
    purpose: str
    method: str
    path: str
    status_code: int
    payload: Any
    request_shape: Mapping[str, Any]


class RequestDiscipline:
    """Enforce the online request budget and immediate family termination."""

    def __init__(
        self, *, interval_seconds: float = 0.31, request_limit: int = 200,
        hard_limit: int = 200,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if interval_seconds < 0.3:
            raise ValueError("probe request interval must be at least 300ms")
        if hard_limit < 1 or hard_limit > 900:
            raise ValueError("probe hard limit must be between 1 and 900")
        if request_limit < 1 or request_limit > hard_limit:
            raise ValueError(
                f"probe request limit must be between 1 and {hard_limit}"
            )
        self.interval_seconds = interval_seconds
        self.request_limit = request_limit
        self.clock = clock
        self.sleeper = sleeper
        self.total = 0
        self.failed = 0
        self.backoff_events = 0
        self.backoff_terminations = 0
        self.domain_stopped = False
        self.stopped_families: set[str] = set()
        self._consecutive_transient_failures: dict[str, int] = {}
        self._consecutive_domain_transient_failures = 0
        self._last_started: float | None = None

    def before_request(self, family_id: str) -> None:
        if self.domain_stopped:
            raise RuntimeError("probe domain is terminated after three consecutive 429/5xx responses")
        if family_id in self.stopped_families:
            raise RuntimeError(f"probe family is terminated after 429/5xx: {family_id}")
        if self.total >= self.request_limit:
            raise RuntimeError("probe session request budget exhausted")
        now = self.clock()
        if self._last_started is not None:
            delay = self.interval_seconds - (now - self._last_started)
            if delay > 0:
                self.sleeper(delay)
                now = self.clock()
        self._last_started = now
        self.total += 1

    def after_response(self, family_id: str, status_code: int) -> None:
        if status_code >= 400:
            self.failed += 1
        if status_code == 429 or status_code >= 500:
            failures = self._consecutive_transient_failures.get(family_id, 0) + 1
            self._consecutive_transient_failures[family_id] = failures
            self._consecutive_domain_transient_failures += 1
            self.backoff_events += 1
            self.sleeper(min(4.0, float(2 ** (failures - 1))))
            if failures >= 3:
                self.stopped_families.add(family_id)
            if self._consecutive_domain_transient_failures >= 3 and not self.domain_stopped:
                self.domain_stopped = True
                self.backoff_terminations += 1
        else:
            self._consecutive_transient_failures[family_id] = 0
            self._consecutive_domain_transient_failures = 0


class RecordingSession:
    """Observe raw HTTP metadata in memory while delegating actual I/O."""

    def __init__(self, session: Any, discipline: RequestDiscipline) -> None:
        self._session = session
        self.discipline = discipline
        self.context = RequestContext()
        self.observations: list[HttpObservation] = []
        self.headers = getattr(session, "headers", {})

    @contextmanager
    def observing(self, operation_id: str, family_id: str, purpose: str) -> Iterator[None]:
        previous = self.context
        self.context = RequestContext(operation_id, family_id or operation_id, purpose)
        try:
            yield
        finally:
            self.context = previous

    def request(self, method: str, url: str, **kwargs: Any) -> Any:
        family_id = self.context.family_id
        self.discipline.before_request(family_id)
        response = self._session.request(method, url, **kwargs)
        try:
            payload = response.json()
        except (TypeError, ValueError, json.JSONDecodeError):
            payload = None
        status_code = int(getattr(response, "status_code", 0))
        self.discipline.after_response(family_id, status_code)
        request_path = urlsplit(url).path
        is_authentication = "/user_login/" in request_path
        request_value = {"query": kwargs.get("params") or {}, "body": kwargs.get("json") or {}}
        self.observations.append(
            HttpObservation(
                operation_id=(
                    "authentication" if is_authentication else self.context.operation_id
                ),
                family_id=family_id,
                purpose="authentication" if is_authentication else self.context.purpose,
                method=str(method).upper(),
                path=request_path, status_code=status_code, payload=payload,
                request_shape=response_schema_sketch(request_value),
            )
        )
        return response

    def __getattr__(self, name: str) -> Any:
        return getattr(self._session, name)


def sdk_parts() -> dict[str, Any]:
    sdk = tool_runtime._sdk_module()
    base = sdk.__name__
    return {
        "GravityInsightClient": sdk.GravityInsightClient,
        "models": importlib.import_module(base + ".models"),
        "registry": importlib.import_module(base + ".registry"),
        "executor": importlib.import_module(base + ".executor"),
        "transport": importlib.import_module(base + ".transport"),
        "http_runtime": importlib.import_module(base + ".http_runtime"),
        "credentials": importlib.import_module(base + ".credentials"),
    }


class _OpenApiProbeRuntime:
    """Probe-only bridge for read operations outside the stable route profile."""

    def __init__(self, base_runtime: Any, recording: RecordingSession, credentials: Any) -> None:
        self._base_runtime = base_runtime
        self._recording = recording
        self._credentials = credentials

    def _request_insight(
        self, method: str, path: str, *, policy_authorization: object,
        params: Mapping[str, Any] | None = None,
        json_body: Mapping[str, Any] | None = None,
        semantic_auth_codes: Any = (), timeout: float | None = None,
        attempts: int | None = None,
    ) -> Any:
        if not path.startswith("/openapi/api/v1/"):
            return self._base_runtime._request_insight(
                method, path, policy_authorization=policy_authorization,
                params=params, json_body=json_body,
                semantic_auth_codes=semantic_auth_codes,
                timeout=timeout, attempts=attempts,
            )
        parts = sdk_parts()
        query, body = parts["registry"]._consume_authorized_request(
            policy_authorization,
            method=method,
            path=path,
            query=params,
            body=json_body,
        )
        headers = {
            **dict(parts["http_runtime"].BROWSER_HEADERS),
            **self._credentials.authorization_headers(),
            "Origin": "https://web.gravity-engine.com",
            "Referer": "https://web.gravity-engine.com/",
        }
        response = self._recording.request(
            method,
            parts["credentials"].GRAVITY_HOST + path,
            headers=headers,
            params=query,
            json=body or None,
            timeout=timeout or 120.0,
            allow_redirects=False,
        )
        try:
            payload = response.json()
        except (TypeError, ValueError, json.JSONDecodeError):
            payload = None
        return parts["http_runtime"].RuntimeResponse(
            int(getattr(response, "status_code", 0)),
            payload,
            time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            {
                str(key): str(value)
                for key, value in getattr(response, "headers", {}).items()
            },
        )


def build_runtime(recording: RecordingSession) -> Any:
    parts = sdk_parts()
    credential_path = PROJECT_ROOT / ".env.gravity.local"
    credentials = parts["credentials"].CredentialProvider.from_env(
        credential_path, session=recording, persist=True,
    )
    base_runtime = parts["http_runtime"].GravityHttpRuntime(
        env_path=credential_path, session=recording,
        credentials=credentials, timeout=120.0, attempts=1,
        requests_per_second=3.0, interval_jitter_ratio=0.0,
    )
    return _OpenApiProbeRuntime(base_runtime, recording, credentials)


def _source_to_runtime(source_operation: Mapping[str, Any]) -> dict[str, Any]:
    operation = copy.deepcopy(dict(source_operation))
    for key in ("effect", "examples", "provenance"):
        operation.pop(key, None)
    operation["stability"] = "experimental"
    operation["executable"] = True
    operation.pop("block_reason", None)
    pagination = operation.get("pagination")
    if isinstance(pagination, Mapping) and pagination.get("kind") == "unverified":
        operation["pagination"] = {
            "kind": "none",
            "page_field": "",
            "page_size_field": "",
            "list_path": "",
            "page_info_path": "",
            "total_page_field": "",
        }
    privacy = operation.get("privacy_policy")
    if isinstance(privacy, Mapping):
        privacy = dict(privacy)
        privacy["redact_keys"] = list(privacy.pop("redact_fields", []))
        operation["privacy_policy"] = privacy
    live_probe = operation.get("live_probe")
    if isinstance(live_probe, Mapping):
        live_probe = dict(live_probe)
        live_probe["input"] = dict(live_probe.pop("inputs", {}))
        operation["live_probe"] = live_probe
    # Parent placeholders are resolved before this isolated registry is built.
    # Keeping provenance edges here would make the one-operation probe registry
    # reject otherwise valid inputs because the stable parent is not registered
    # in this temporary registry.
    operation["required_parent"] = []
    return operation


def build_probe_policy(parts: Mapping[str, Any], registry: Any, path: str) -> Any:
    policy_class = parts["registry"].PolicyEngine
    if not path.startswith("/openapi/api/v1/"):
        return policy_class(registry, allow_experimental=True)

    class OpenApiDraftPolicy(policy_class):
        @staticmethod
        def _check_template(template: str) -> None:
            if template.startswith("/openapi/api/v1/"):
                return
            policy_class._check_template(template)

    return OpenApiDraftPolicy(registry, allow_experimental=True)


def build_draft_client(source: Mapping[str, Any], runtime: Any) -> Any:
    parts = sdk_parts()
    runtime_operation = _source_to_runtime(source["operation"])
    operation = parts["models"].load_operation_manifest(
        {"operations": [runtime_operation]}
    )[0]
    registry = parts["registry"].Registry([operation])
    policy = build_probe_policy(parts, registry, operation.path_template)
    transport = parts["transport"].Transport(
        policy=policy, runtime=runtime, timeout=120.0, attempts=1
    )
    executor = parts["executor"].ReadExecutor(registry, policy, transport)
    return parts["GravityInsightClient"](registry, executor, allow_experimental=True)
