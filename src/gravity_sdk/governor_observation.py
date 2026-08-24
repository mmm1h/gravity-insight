"""Bounded value-free observation for Runtime-owned HTTP attempts."""

from __future__ import annotations

import copy
import hashlib
import os
import threading
from collections import OrderedDict, deque
from collections.abc import Callable, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator
from urllib.parse import urlsplit

from .agent_runtime_contracts import (
    AgentRuntimeContractError,
    validate_schema,
)
from .errors import InputValidationError


OBSERVATION_SCHEMA_VERSION = "gravity.governor-observation.v1"
SNAPSHOT_SCHEMA_VERSION = "gravity.governor-observation-snapshot.v1"
POLICY_REVISION = "gravity.governor-policy.observe.v1"
MAX_OBSERVATIONS = 4_096
MAX_SCOPES = 64
MAX_PAGE_SIZE = 1_000
MAX_LATENCY_MS = 600_000
MAX_RATE_DELAY_MS = 600_000
_OBSERVATION_SCHEMA = "governor-observation-v1.schema.json"
_SNAPSHOT_SCHEMA = "governor-observation-snapshot-v1.schema.json"
_PROCESS_SCOPE = "gravity-governor-process-http"
_OPERATION_CHARACTERS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:-"
)


class GovernorObservationContractError(AgentRuntimeContractError):
    """Governor observations are malformed or exceed their safe bounds."""


@dataclass
class _ScopeBuffer:
    observations: deque[dict[str, Any]]
    next_sequence: int = 1
    dropped: int = 0


class GovernorObservationRecorder:
    """Thread-safe LRU partitions whose private scope keys never render."""

    def __init__(
        self,
        *,
        max_observations: int = MAX_OBSERVATIONS,
        max_scopes: int = MAX_SCOPES,
        enabled: bool = True,
    ) -> None:
        if (
            type(max_observations) is not int
            or not 1 <= max_observations <= MAX_OBSERVATIONS
            or type(max_scopes) is not int
            or not 1 <= max_scopes <= MAX_SCOPES
            or type(enabled) is not bool
        ):
            raise ValueError("Governor observation recorder bounds are invalid")
        self.max_observations = max_observations
        self.max_scopes = max_scopes
        self._enabled = enabled
        self._lock = threading.Lock()
        self._scopes: OrderedDict[str, _ScopeBuffer] = OrderedDict()

    @property
    def enabled(self) -> bool:
        with self._lock:
            return self._enabled

    def set_enabled(self, enabled: bool) -> bool:
        if type(enabled) is not bool:
            raise ValueError("Governor observation mode must be boolean")
        with self._lock:
            previous = self._enabled
            self._enabled = enabled
            return previous

    def record(self, scope_material: Any, value: Mapping[str, Any]) -> None:
        partition = _partition(scope_material)
        selected = copy.deepcopy(dict(value))
        with self._lock:
            if not self._enabled:
                return
            scope = self._scopes.pop(partition, None)
            if scope is None:
                if len(self._scopes) >= self.max_scopes:
                    self._scopes.popitem(last=False)
                scope = _ScopeBuffer(deque(maxlen=self.max_observations))
            self._scopes[partition] = scope
            selected["schema_version"] = OBSERVATION_SCHEMA_VERSION
            selected["sequence"] = scope.next_sequence
            scope.next_sequence += 1
            if len(scope.observations) == self.max_observations:
                scope.dropped += 1
            scope.observations.append(selected)

    def snapshot(
        self,
        scope_material: Any,
        *,
        after_sequence: int = 0,
        limit: int = MAX_PAGE_SIZE,
    ) -> dict[str, Any]:
        _snapshot_bounds(after_sequence, limit)
        partition = _partition(scope_material)
        with self._lock:
            enabled = self._enabled
            scope = self._scopes.get(partition)
            if scope is None:
                values: list[dict[str, Any]] = []
                latest_sequence = 0
                dropped = 0
                earliest = 0
            else:
                self._scopes.move_to_end(partition)
                available = [
                    copy.deepcopy(item)
                    for item in scope.observations
                    if item["sequence"] > after_sequence
                ]
                values = available[:limit]
                latest_sequence = scope.next_sequence - 1
                dropped = scope.dropped
                earliest = (
                    scope.observations[0]["sequence"]
                    if scope.observations
                    else latest_sequence + 1
                )
                has_more = len(available) > len(values)
            if scope is None:
                has_more = False
            truncated = bool(dropped and after_sequence < earliest - 1)
            next_sequence = (
                values[-1]["sequence"]
                if values
                else max(after_sequence, latest_sequence)
            )
        snapshot = {
            "schema_version": SNAPSHOT_SCHEMA_VERSION,
            "mode": "observe" if enabled else "disabled",
            "policy_revision": POLICY_REVISION,
            "after_sequence": after_sequence,
            "next_sequence": next_sequence,
            "count": len(values),
            "has_more": has_more,
            "truncated": truncated,
            "dropped_observations": dropped,
            "observations": values,
            "limits": {
                "max_observations": self.max_observations,
                "max_scopes": self.max_scopes,
                "max_page_size": MAX_PAGE_SIZE,
                "max_latency_ms": MAX_LATENCY_MS,
                "max_rate_delay_ms": MAX_RATE_DELAY_MS,
            },
            "network_called": False,
        }
        return validate_governor_observation_snapshot(snapshot)


def observe_http_attempt(
    request_args: Sequence[Any],
    request_kwargs: Mapping[str, Any],
    *,
    receipt_context: Mapping[str, Any] | None,
    governor_context: Mapping[str, Any] | None,
    response: Any,
    error: BaseException | None,
    duration_seconds: float,
) -> None:
    receipt = dict(receipt_context or {})
    governor = dict(governor_context or {})
    status = _status(response)
    attempt = _positive(receipt.get("attempt")) or 1
    attempt_budget = _positive(governor.get("attempt_budget")) or attempt
    latency_ms, latency_capped = _capped_ms(duration_seconds, MAX_LATENCY_MS)
    rate_delay_ms, rate_delay_capped = _capped_ms(
        governor.get("rate_delay_seconds", 0.0), MAX_RATE_DELAY_MS
    )
    value = {
        "host_key": _host_key(request_args),
        "operation_class": _operation(receipt.get("operation_id")),
        "profile": _profile(governor.get("profile"), receipt.get("operation_id")),
        "method": _method(receipt.get("method"), request_args),
        "outcome": "transport_error" if error is not None else "response",
        "status_class": _status_class(status, error),
        "http_status": status,
        "request_count": 1,
        "latency_ms": latency_ms,
        "latency_capped": latency_capped,
        "rate_limit_delay_ms": rate_delay_ms,
        "rate_limit_delay_capped": rate_delay_capped,
        "attempt": attempt,
        "attempt_budget": max(attempt, attempt_budget),
        "retry_attempt": bool(receipt.get("retry")) or attempt > 1,
        "budgets": {
            "business_limit": _positive(governor.get("business_limit")),
            "sql_limit": _positive(governor.get("sql_limit")),
            "timeout_ms": _timeout_ms(
                governor.get("timeout_seconds", request_kwargs.get("timeout"))
            ),
        },
    }
    _RECORDER.record(governor.get("scope_key", _PROCESS_SCOPE), value)


def runtime_attempt_context(
    *,
    scope_key: str,
    profile: str,
    rate_delay_seconds: float,
    attempt_budget: int,
    timeout_seconds: float,
    business_limit: int,
    sql_limit: int,
) -> dict[str, Any]:
    """Build fixed Runtime budget metadata without request values."""

    return {
        "scope_key": scope_key,
        "profile": profile,
        "rate_delay_seconds": rate_delay_seconds,
        "attempt_budget": attempt_budget,
        "timeout_seconds": timeout_seconds,
        "business_limit": None if profile == "login" else business_limit,
        "sql_limit": sql_limit if profile == "sql" else None,
    }


def observation_snapshot(
    scope_material: Any,
    *,
    after_sequence: int = 0,
    limit: int = MAX_PAGE_SIZE,
) -> dict[str, Any]:
    return _RECORDER.snapshot(
        scope_material, after_sequence=after_sequence, limit=limit
    )


def process_observation_snapshot(
    *, after_sequence: int = 0, limit: int = MAX_PAGE_SIZE
) -> dict[str, Any]:
    """Internal evidence for Runtime-owned HTTP without a principal runtime."""

    return observation_snapshot(
        _PROCESS_SCOPE, after_sequence=after_sequence, limit=limit
    )


@contextmanager
def governor_observation_mode(enabled: bool) -> Iterator[None]:
    previous = _RECORDER.set_enabled(enabled)
    try:
        yield
    finally:
        _RECORDER.set_enabled(previous)


def validate_governor_observation(value: Mapping[str, Any]) -> dict[str, Any]:
    return _validate(value, _OBSERVATION_SCHEMA, "Governor observation")


def validate_governor_observation_snapshot(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    selected = _validate(value, _SNAPSHOT_SCHEMA, "Governor observation snapshot")
    for observation in selected["observations"]:
        validate_governor_observation(observation)
    sequences = [item["sequence"] for item in selected["observations"]]
    if sequences != sorted(set(sequences)):
        raise GovernorObservationContractError(
            "Governor observation sequence is not strictly ordered"
        )
    if selected["count"] != len(sequences):
        raise GovernorObservationContractError(
            "Governor observation snapshot count changed"
        )
    return selected


class GovernorObservationService:
    """Lazy current-scope snapshot facade for an environment-bound SDK."""

    def __init__(self, runtime_factory: Callable[[], Any] | None) -> None:
        self._runtime_factory = runtime_factory

    def __repr__(self) -> str:
        return "<GovernorObservationService private>"

    def observations(
        self, *, after_sequence: int = 0, limit: int = MAX_PAGE_SIZE
    ) -> dict[str, Any]:
        if self._runtime_factory is None:
            raise InputValidationError(
                "actual value: SDK has no environment-bound Runtime; allowed value: GravitySDK.from_env()",
                field="sdk",
                code="GOVERNOR_SCOPE_UNBOUND",
                next_action="Construct a scoped SDK with GravitySDK.from_env(), then read its observations.",
            )
        runtime = self._runtime_factory()
        snapshot = getattr(runtime, "governor_observations", None)
        if not callable(snapshot):
            raise InputValidationError(
                "actual value: bound Runtime has no Governor observation contract; allowed value: the current Gravity HTTP Runtime",
                field="runtime",
                code="GOVERNOR_RUNTIME_UNAVAILABLE",
                next_action="Reinstall the current Runtime and retry the offline observation query.",
            )
        return snapshot(after_sequence=after_sequence, limit=limit)


def _validate(value: Mapping[str, Any], schema: str, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise GovernorObservationContractError(f"{label} must be an object")
    selected = copy.deepcopy(dict(value))
    try:
        validate_schema(selected, schema, label)
    except AgentRuntimeContractError as exc:
        raise GovernorObservationContractError(str(exc)) from exc
    return selected


def _snapshot_bounds(after_sequence: Any, limit: Any) -> None:
    if type(after_sequence) is not int or after_sequence < 0:
        raise InputValidationError(
            "actual value: invalid observation sequence; allowed value: a non-negative integer",
            field="after_sequence",
            code="GOVERNOR_CURSOR_INVALID",
            next_action="Use zero or the previous snapshot next_sequence.",
        )
    if type(limit) is not int or not 1 <= limit <= MAX_PAGE_SIZE:
        raise InputValidationError(
            f"actual value: invalid observation limit; allowed range: 1 through {MAX_PAGE_SIZE}",
            field="limit",
            code="GOVERNOR_LIMIT_INVALID",
            next_action="Choose a bounded observation page size and retry.",
        )


def _partition(value: Any) -> str:
    rendered = str(value or _PROCESS_SCOPE)
    return hashlib.sha256(
        ("gravity-governor-scope-v1\0" + rendered).encode("utf-8")
    ).hexdigest()


def _host_key(arguments: Sequence[Any]) -> str:
    origin = "unknown"
    for value in arguments:
        if not isinstance(value, str) or not value.startswith("https://"):
            continue
        parsed = urlsplit(value)
        if (
            parsed.scheme == "https"
            and parsed.hostname
            and parsed.username is None
            and parsed.password is None
        ):
            port = f":{parsed.port}" if parsed.port else ""
            origin = f"https://{parsed.hostname.casefold()}{port}"
            break
    digest = hashlib.sha256(("gravity-host-v1\0" + origin).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _operation(value: Any) -> str:
    selected = str(value or "unknown")
    if not 1 <= len(selected) <= 256 or any(
        character not in _OPERATION_CHARACTERS for character in selected
    ):
        return "unknown"
    return selected


def _profile(value: Any, operation: Any) -> str:
    selected = str(value or "")
    if selected in {"insight", "sql", "login", "artifact", "probe", "census"}:
        return selected
    operation_id = str(operation or "")
    if operation_id == "authentication":
        return "login"
    if operation_id == "sql.query":
        return "sql"
    if operation_id.startswith("export_blob_") or "asset" in operation_id:
        return "artifact"
    return "runtime_http"


def _method(value: Any, arguments: Sequence[Any]) -> str:
    selected = str(value or "").upper()
    if selected in {"GET", "POST"}:
        return selected
    for item in arguments:
        candidate = str(item).upper() if isinstance(item, str) else ""
        if candidate in {"GET", "POST"}:
            return candidate
    return "GET"


def _status(response: Any) -> int | None:
    value = getattr(response, "status_code", None)
    return value if type(value) is int and 0 <= value <= 999 else None


def _status_class(status: int | None, error: BaseException | None) -> str:
    if error is not None:
        return "transport_error"
    if status is None:
        return "unknown"
    if 200 <= status < 300:
        return "success"
    if 300 <= status < 400:
        return "redirect"
    if status == 429:
        return "rate_limited"
    if 400 <= status < 500:
        return "client_error"
    if 500 <= status < 600:
        return "server_error"
    return "unknown"


def _capped_ms(value: Any, maximum: int) -> tuple[int, bool]:
    try:
        raw = max(0, round(float(value) * 1_000))
    except (TypeError, ValueError, OverflowError):
        raw = 0
    return min(raw, maximum), raw > maximum


def _timeout_ms(value: Any) -> int | None:
    try:
        raw = round(float(value) * 1_000)
    except (TypeError, ValueError, OverflowError):
        return None
    return min(max(1, raw), 3_600_000)


def _positive(value: Any) -> int | None:
    return value if type(value) is int and value > 0 else None


def _enabled_from_environment() -> bool:
    return os.environ.get("GRAVITY_GOVERNOR_OBSERVE", "1").strip().casefold() not in {
        "0",
        "false",
        "off",
        "no",
    }


_RECORDER = GovernorObservationRecorder(enabled=_enabled_from_environment())


__all__ = [
    "GovernorObservationContractError",
    "GovernorObservationRecorder",
    "GovernorObservationService",
    "MAX_OBSERVATIONS",
    "MAX_PAGE_SIZE",
    "MAX_SCOPES",
    "OBSERVATION_SCHEMA_VERSION",
    "POLICY_REVISION",
    "SNAPSHOT_SCHEMA_VERSION",
    "validate_governor_observation",
    "validate_governor_observation_snapshot",
]
