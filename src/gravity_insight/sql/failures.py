"""Caller-safe classification for governed SQL execution failures."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any, Mapping, TextIO

from gravity_insight.errors import (
    AuthenticationError,
    CredentialError,
    SqlResponseError,
    SqlValidationError,
    TransportError,
)
from gravity_insight.semantic_status import protocol_status_evidence


MAX_DIAGNOSTIC_ELAPSED_MS = 900_000
MAX_SQL_RETRY_AFTER_MS = 30_000
_CONTEXT_ATTRIBUTE = "_gravity_sql_failure_context"
_SAFE_CODE = re.compile(r"^(?:[A-Z][A-Z0-9_.:-]{0,63}|[0-9]{1,9})$")
_REVIEWED_PROTOCOL_TOKENS = frozenset({"SUCCESS", "OK", "ERROR", "FAILED", "REJECTED"})
SQL_COMMAND_ERROR_SCHEMA_VERSION = "gravity-sql.command-error.v1"


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
    retry_after_ms: int | None = None


@dataclass(frozen=True)
class _SqlCommandFailure:
    category: str
    code: str
    field: str
    message: str
    stage: str
    retryable: bool
    reached_upstream: str
    next_action: str


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


_COMMAND_FAILURES = {
    "credential_not_ready": _SqlCommandFailure(
        "authentication", "SQL_CREDENTIAL_SYNC_NOT_READY", "credentials", "Credential sync is not configured", "bind", False, "no",
        "Configure the local Gravity credential file, then retry this sync command.",
    ),
    "credential_sync_failed": _SqlCommandFailure(
        "authentication", "SQL_CREDENTIAL_SYNC_FAILED", "credentials", "Credential sync failed", "execute", False, "unknown",
        "Inspect credential-sync prerequisites and GitHub authentication; do not retry until corrected.",
    ),
    "workspace_invalid": _SqlCommandFailure(
        "input", "SQL_WORKSPACE_INVALID", "workspace", "Gravity workspace SQL product configuration is invalid", "bind", False, "no",
        "Correct the selected gravity.toml workspace, then rerun the failed SQL command.",
    ),
    "products_not_configured": _SqlCommandFailure(
        "input", "SQL_PRODUCTS_NOT_CONFIGURED", "workspace.products", "No SQL products are configured", "bind", False, "no",
        "Add a reviewed [products.<name>] entry to gravity.toml, then rerun `gravity sql products`.",
    ),
    "status_evidence_invalid": _SqlCommandFailure(
        "contract", "SQL_STATUS_EVIDENCE_INVALID", "evidence", "Current SQL Evidence violates its local contract", "shape", False, "no",
        "Run `gravity sql evidence-preflight`, then regenerate reviewed Evidence before using status.",
    ),
    "preflight_local_io": _SqlCommandFailure(
        "local_io", "SQL_EVIDENCE_PREFLIGHT_LOCAL_IO", "workspace.state", "SQL Evidence preflight could not read local state", "bind", False, "no",
        "Inspect the workspace state path and permissions, then rerun the offline preflight.",
    ),
    "preflight_contract_invalid": _SqlCommandFailure(
        "contract", "SQL_EVIDENCE_PREFLIGHT_CONTRACT_INVALID", "evidence", "SQL Evidence violates its local contract", "shape", False, "no",
        "Repair or regenerate reviewed SQL Evidence, then rerun the offline preflight.",
    ),
    "preflight_input_invalid": _SqlCommandFailure(
        "input", "SQL_EVIDENCE_PREFLIGHT_INPUT_INVALID", "date_or_workspace", "SQL Evidence preflight input is invalid", "bind", False, "no",
        "Correct the requested date or workspace input, then rerun the offline preflight.",
    ),
}


def command_failure_fields(kind: str) -> dict[str, Any]:
    """Return one fixed pre-query SQL failure classification."""

    failure = _COMMAND_FAILURES[kind]
    reached = failure.reached_upstream
    return {
        "category": failure.category,
        "code": failure.code,
        "field": failure.field,
        "message": failure.message,
        "stage": failure.stage,
        "retryable": failure.retryable,
        "reached_upstream": reached,
        "reached_sql_engine": "no",
        "upstream_error": {
            "category": "not_reached" if reached == "no" else "unknown",
            "code": failure.code,
        },
        "execution_evidence": {
            **execution_evidence(
                elapsed_seconds=0, request_count=0, request_count_bound=0
            ),
            "request_scope": "gravity_sql_engine",
        },
        "next_action": failure.next_action,
    }


def emit_command_error(
    command: str,
    kind: str,
    exit_code: int,
    *,
    serializer: Any,
    source: Mapping[str, Any],
    stream: TextIO,
) -> int:
    """Serialize one pre-query command failure through the CLI-owned transport."""

    payload = {
        "schema_version": SQL_COMMAND_ERROR_SCHEMA_VERSION,
        "result_source": dict(source),
        "ok": False,
        "status": "error",
        "command": command,
        "exit_code": exit_code,
        "error": command_failure_fields(kind),
    }
    print(
        serializer(payload, ensure_ascii=False, indent=2, sort_keys=True),
        file=stream,
    )
    return exit_code


def query_boundary_failure_fields(
    message: str, *, category: str, code: str, field: str | None = None
) -> dict[str, Any]:
    """Return the established direct-query boundary error shape."""

    stage = "shape" if category == "contract" else (
        "execute" if category == "runtime" else "bind"
    )
    return {
        "category": category,
        "code": code,
        "field": field,
        "message": message,
        "stage": stage,
        "retryable": category == "runtime",
        "reached_sql_engine": "unknown" if category == "runtime" else "no",
        "upstream_error": {
            "category": "unexpected_failure" if category == "runtime" else "not_reached",
            "code": code,
        },
        "execution_evidence": execution_evidence(
            elapsed_seconds=0, request_count=0, request_count_bound=1
        ),
        "next_action": (
            "Run `gravity auth status`; refresh or configure credentials, then retry."
            if category == "authentication"
            else "Run `gravity sql products`, correct this request, and retry."
            if category == "input"
            else "Inspect the governed SQL product contract and local state."
            if category in {"contract", "local_io"}
            else "Retry the same query once; if it fails again, run `gravity doctor --live`."
        ),
    }


def emit_query_boundary_error(
    message: str,
    *,
    category: str,
    code: str,
    field: str | None,
    exit_code: int,
    serializer: Any,
    source: Mapping[str, Any],
    stream: TextIO,
) -> int:
    """Serialize the established query failure through the CLI-owned transport."""

    payload = {
        "schema_version": "gravity-sql.query.v1",
        "result_source": dict(source),
        "ok": False,
        "status": "error",
        "exit_code": exit_code,
        "error": query_boundary_failure_fields(
            message, category=category, code=code, field=field
        ),
    }
    print(serializer(payload, ensure_ascii=False, sort_keys=True), file=stream)
    return exit_code


def annotate_sql_failure(
    error: Exception,
    *,
    kind: str,
    http_status: int | None = None,
    protocol_status: Mapping[str, Any] | None = None,
    retry_after_ms: int | None = None,
) -> Exception:
    """Attach only reviewed structural facts to an existing SQL exception type."""

    context = {
        "kind": kind,
        "http_status": http_status,
        "protocol_status": dict(protocol_status) if protocol_status is not None else None,
        "retry_after_ms": retry_after_ms,
    }
    setattr(error, _CONTEXT_ATTRIBUTE, context)
    failure = classify_sql_failure(error, request_count=1)
    for field, value in {
        "sql_stage": failure.stage,
        "sql_category": failure.upstream_category,
        "safe_message": failure.message,
        "retryable": failure.retryable,
        "reached_sql_engine": failure.reached_sql_engine,
        "next_action": failure.next_action,
        "http_status": failure.http_status,
        "protocol_status": failure.protocol_status,
        "retry_after_ms": failure.retry_after_ms,
    }.items():
        setattr(error, field, value)
    setattr(error, "code", failure.code)
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

    structured = _structured_stage_failure(error)
    if structured is not None:
        return structured
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


def _structured_stage_failure(error: BaseException) -> SqlFailure | None:
    """Preserve explicit bind/compile/plan/execute/shape failures from SQL adapters."""

    stage = getattr(error, "sql_stage", None)
    if stage not in {"bind", "compile", "plan", "execute", "shape"}:
        return None
    category = str(getattr(error, "sql_category", "runtime"))
    code = str(getattr(error, "code", "SQL_UNEXPECTED_FAILURE"))
    message = str(getattr(error, "safe_message", "Gravity SQL request failed"))
    next_action = str(
        getattr(
            error,
            "next_action",
            "Use the stable SQL failure stage to correct the request before retrying.",
        )
    )
    reached = str(getattr(error, "reached_sql_engine", "unknown"))
    if reached not in {"yes", "no", "unknown"}:
        reached = "unknown"
    return SqlFailure(
        kind=f"{stage}_failure",
        stage=stage,
        upstream_category=category,
        code=code,
        message=message,
        retryable=bool(getattr(error, "retryable", False)),
        reached_sql_engine=reached,
        next_action=next_action,
        http_status=(
            getattr(error, "http_status", None)
            if type(getattr(error, "http_status", None)) is int
            else None
        ),
        protocol_status=(
            dict(getattr(error, "protocol_status"))
            if isinstance(getattr(error, "protocol_status", None), Mapping)
            else None
        ),
        retry_after_ms=(
            getattr(error, "retry_after_ms", None)
            if type(getattr(error, "retry_after_ms", None)) is int
            else None
        ),
    )


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
    result = {
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
    if failure.retry_after_ms is not None:
        result["retry_after_ms"] = failure.retry_after_ms
    return result


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
    retry_after = context.get("retry_after_ms")
    return SqlFailure(
        **{
            **failure.__dict__,
            "http_status": status if type(status) is int else failure.http_status,
            "protocol_status": dict(protocol) if isinstance(protocol, Mapping) else None,
            "retry_after_ms": (
                retry_after
                if failure.code == "SQL_HTTP_RATE_LIMITED"
                and type(retry_after) is int
                and 0 <= retry_after <= MAX_SQL_RETRY_AFTER_MS
                else None
            ),
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
    "MAX_SQL_RETRY_AFTER_MS",
    "SQL_COMMAND_ERROR_SCHEMA_VERSION",
    "SqlFailure",
    "annotate_sql_failure",
    "classify_sql_failure",
    "command_failure_fields",
    "diagnostic_fields",
    "emit_command_error",
    "emit_query_boundary_error",
    "execution_evidence",
    "query_boundary_failure_fields",
    "sql_protocol_status",
]
