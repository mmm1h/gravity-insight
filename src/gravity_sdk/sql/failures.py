"""Caller-safe classification for governed SQL execution failures."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any, Mapping

from gravity_sdk.errors import (
    AuthenticationError,
    CredentialError,
    SqlResponseError,
    SqlValidationError,
    TransportError,
)
from gravity_sdk.semantic_status import protocol_status_evidence


MAX_DIAGNOSTIC_ELAPSED_MS = 900_000
_CONTEXT_ATTRIBUTE = "_gravity_sql_failure_context"
_SAFE_CODE = re.compile(r"^(?:[A-Z][A-Z0-9_.:-]{0,63}|[0-9]{1,9})$")
_REVIEWED_PROTOCOL_TOKENS = frozenset({"SUCCESS", "OK", "ERROR", "FAILED", "REJECTED"})


@dataclass(frozen=True)
class SqlFailure:
    kind: str
    stage: str
    upstream_category: str
    code: str
    message: str
    retryable: bool
    reached_sql_engine: str
    next_action: str
    http_status: int | None = None
    protocol_status: Mapping[str, Any] | None = None


_FAILURES = {
    "authentication": SqlFailure(
        "authentication", "bind", "authentication", "SQL_PRODUCT_AUTH_FAILED",
        "Gravity SQL authentication failed", False, "no",
        "Run `gravity auth status`, refresh credentials, then retry once.",
    ),
    "credentials": SqlFailure(
        "credentials", "bind", "credentials", "SQL_PRODUCT_CREDENTIALS_UNAVAILABLE",
        "Gravity SQL credentials are unavailable", False, "no",
        "Run `gravity auth status`, then configure or refresh credentials before retrying.",
    ),
    "local_validation": SqlFailure(
        "local_validation", "bind", "local_validation", "SQL_LOCAL_VALIDATION_FAILED",
        "Gravity SQL request was rejected by local validation", False, "no",
        "Correct the registered SQL product input or template; do not retry it unchanged.",
    ),
    "transport": SqlFailure(
        "transport", "execute", "transport_failure", "SQL_TRANSPORT_FAILED",
        "Gravity SQL transport failed", True, "no",
        "Retry the same query once; if it fails again, run `gravity doctor --live`.",
    ),
    "invalid_http_status": SqlFailure(
        "invalid_http_status", "shape", "http_status_shape", "SQL_HTTP_STATUS_INVALID",
        "Gravity SQL returned an invalid HTTP status shape", False, "unknown",
        "Stop automation and ask the SDK maintainer to re-verify the SQL transport contract.",
    ),
    "blocked_redirect": SqlFailure(
        "blocked_redirect", "execute", "redirect_blocked", "SQL_REDIRECT_BLOCKED",
        "Gravity SQL redirect was blocked", False, "no",
        "Do not retry; ask the SDK maintainer to verify the fixed SQL endpoint routing.",
    ),
    "engine_rejected": SqlFailure(
        "engine_rejected", "plan", "engine_rejected", "SQL_ENGINE_REJECTED",
        "Gravity SQL engine rejected the query", False, "yes",
        "Do not retry unchanged. Check SQL syntax and types plus documented join support; "
        "reduce join, CTE, window, or resource demands, or use governed Analysis reads. "
        "Provide only the sanitized protocol_status to the SDK maintainer.",
    ),
    "non_tabular": SqlFailure(
        "non_tabular", "shape", "tabular_shape_drift", "SQL_RESPONSE_SHAPE_INVALID",
        "Gravity SQL response did not contain tabular rows", False, "yes",
        "Stop automation and ask the SDK maintainer to re-verify the SQL response shape.",
    ),
    "unexpected": SqlFailure(
        "unexpected", "execute", "unexpected_failure", "SQL_UNEXPECTED_FAILURE",
        "Gravity SQL query failed unexpectedly", True, "unknown",
        "Retry the same query once; if it fails again, report the stable error code to the SDK maintainer.",
    ),
}


def annotate_sql_failure(
    error: Exception,
    *,
    kind: str,
    http_status: int | None = None,
    protocol_status: Mapping[str, Any] | None = None,
) -> Exception:
    """Attach only reviewed structural facts to an existing SQL exception type."""

    setattr(
        error,
        _CONTEXT_ATTRIBUTE,
        {
            "kind": kind,
            "http_status": http_status,
            "protocol_status": dict(protocol_status) if protocol_status is not None else None,
        },
    )
    return error


def sql_protocol_status(
    payload: Any,
    *,
    http_status: int | None,
    status: str | None,
    classification: str,
) -> dict[str, Any]:
    """Extend protocol evidence while withholding unreviewed scalar prose."""

    evidence = protocol_status_evidence(payload, http_status=http_status)
    status_payload = _status_payload(payload)
    if status_payload is not None and status_payload is not payload:
        nested = protocol_status_evidence(status_payload, http_status=http_status)
        for field in ("code", "msg", "extra_error"):
            if evidence[field].get("present") is False:
                evidence[field] = nested[field]
    evidence["classification"] = classification
    evidence["status"] = _safe_scalar_field(status, field="status", present=status is not None)
    for field in ("code", "msg", "extra_error"):
        evidence[field] = _sanitize_evidence_field(evidence[field], field=field)
    return evidence


def classify_sql_failure(error: BaseException, *, request_count: int = 0) -> SqlFailure:
    """Map all SQL client and batch failures through one stable taxonomy."""

    context = getattr(error, _CONTEXT_ATTRIBUTE, None)
    kind = context.get("kind") if isinstance(context, Mapping) else None
    if isinstance(error, AuthenticationError):
        kind = "authentication"
    elif isinstance(error, CredentialError):
        kind = "credentials"
    elif isinstance(error, SqlValidationError):
        kind = "local_validation"
    elif isinstance(error, SqlResponseError) and kind not in {"engine_rejected", "non_tabular"}:
        kind = "engine_rejected"
    elif isinstance(error, TransportError) and kind not in {
        "invalid_http_status", "blocked_redirect", "http_status", "transport"
    }:
        kind = "transport"
    if kind == "http_status":
        status = context.get("http_status") if isinstance(context, Mapping) else None
        return _http_failure(status, context)
    selected = _FAILURES.get(str(kind), _FAILURES["unexpected"])
    if selected.kind == "unexpected" and request_count == 0:
        selected = SqlFailure(
            "unexpected", "compile", "local_compile_failure", "SQL_COMPILE_FAILED",
            "Governed SQL product compilation failed", False, "no",
            "Inspect the registered product placeholders and local contract; do not retry unchanged.",
        )
    return _with_context(selected, context)


def diagnostic_fields(
    failure: SqlFailure,
    *,
    elapsed_seconds: float,
    request_count: int,
    request_count_bound: int,
) -> dict[str, Any]:
    effective_count = 0 if failure.kind == "local_validation" else request_count
    upstream: dict[str, Any] = {
        "category": failure.upstream_category,
        "code": failure.code,
    }
    if failure.http_status is not None:
        upstream["http_status"] = failure.http_status
        upstream["http_status_class"] = f"{failure.http_status // 100}xx"
    if failure.protocol_status is not None:
        upstream["protocol_status"] = dict(failure.protocol_status)
    return {
        "stage": failure.stage,
        "retryable": failure.retryable,
        "reached_sql_engine": failure.reached_sql_engine,
        "upstream_error": upstream,
        "execution_evidence": execution_evidence(
            elapsed_seconds=elapsed_seconds,
            request_count=effective_count,
            request_count_bound=request_count_bound,
        ),
    }


def execution_evidence(
    *, elapsed_seconds: float, request_count: int, request_count_bound: int
) -> dict[str, Any]:
    raw_ms = max(0, int(elapsed_seconds * 1000))
    safe_bound = max(0, int(request_count_bound))
    safe_count = max(0, int(request_count))
    return {
        "elapsed_ms": min(raw_ms, MAX_DIAGNOSTIC_ELAPSED_MS),
        "elapsed_ms_bound": MAX_DIAGNOSTIC_ELAPSED_MS,
        "elapsed_ms_capped": raw_ms > MAX_DIAGNOSTIC_ELAPSED_MS,
        "request_count": min(safe_count, safe_bound),
        "request_count_bound": safe_bound,
        "request_count_capped": safe_count > safe_bound,
    }


def _http_failure(status: Any, context: Mapping[str, Any] | None) -> SqlFailure:
    if status in {408, 504}:
        selected = SqlFailure(
            "http_status", "execute", "http_timeout", "SQL_HTTP_TIMEOUT",
            "Gravity SQL request timed out", True, "unknown",
            "Retry once with a smaller window or simpler join/CTE plan; do not fan out retries.",
        )
    elif status == 429:
        selected = SqlFailure(
            "http_status", "execute", "http_rate_limited", "SQL_HTTP_RATE_LIMITED",
            "Gravity SQL request was rate limited", True, "unknown",
            "Wait for service capacity, then retry the same query once without increasing concurrency.",
        )
    elif isinstance(status, int) and status >= 500:
        selected = SqlFailure(
            "http_status", "execute", "http_server_error", "SQL_HTTP_SERVER_ERROR",
            "Gravity SQL service returned a server error", True, "unknown",
            "Retry the same query once; if it fails again, report the HTTP status class.",
        )
    else:
        selected = SqlFailure(
            "http_status", "execute", "http_request_rejected", "SQL_HTTP_REQUEST_REJECTED",
            "Gravity SQL request was rejected at the HTTP layer", False, "unknown",
            "Do not retry unchanged; verify the fixed route and request limits with the SQL service owner.",
        )
    return _with_context(selected, context)


def _with_context(
    failure: SqlFailure, context: Mapping[str, Any] | None
) -> SqlFailure:
    if not isinstance(context, Mapping):
        return failure
    status = context.get("http_status")
    protocol = context.get("protocol_status")
    return SqlFailure(
        **{
            **failure.__dict__,
            "http_status": status if type(status) is int else failure.http_status,
            "protocol_status": dict(protocol) if isinstance(protocol, Mapping) else None,
        }
    )


def _sanitize_evidence_field(value: Any, *, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or "value" not in value:
        return dict(value) if isinstance(value, Mapping) else {"present": False}
    return _safe_scalar_field(value["value"], field=field, present=True)


def _status_payload(payload: Any) -> Mapping[str, Any] | None:
    if not isinstance(payload, Mapping):
        return None
    if isinstance(payload.get("status"), str):
        return payload
    for key in ("data", "result"):
        nested = _status_payload(payload.get(key))
        if nested is not None:
            return nested
    return None


def _safe_scalar_field(value: Any, *, field: str, present: bool) -> dict[str, Any]:
    if not present:
        return {"present": False}
    if value is None or isinstance(value, (bool, int, float)):
        return {"present": True, "value": value}
    if isinstance(value, str):
        if (_SAFE_CODE.fullmatch(value) if field == "code" else value in _REVIEWED_PROTOCOL_TOKENS):
            return {"present": True, "value": value}
        return {
            "present": True,
            "value_persisted": False,
            "value_type": "string",
            "truthy": bool(value),
            "value_sha256": hashlib.sha256(value.encode("utf-8")).hexdigest(),
        }
    return {
        "present": True,
        "value_persisted": False,
        "value_type": "object" if isinstance(value, Mapping) else "array",
        "truthy": bool(value),
    }


__all__ = [
    "MAX_DIAGNOSTIC_ELAPSED_MS",
    "SqlFailure",
    "annotate_sql_failure",
    "classify_sql_failure",
    "diagnostic_fields",
    "execution_evidence",
    "sql_protocol_status",
]
