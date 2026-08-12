"""Stable machine-result contracts for composite Gravity reads."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .errors import ErrorCategory, ErrorCode, ErrorDetail, exit_code_for_error


_FAILURE_STATUSES = frozenset(
    {"error", "semantic_error", "unavailable", "parent_required", "permission_unavailable"}
)
_STATUS_CODES = {
    "contract_changed": ErrorCode.CONTRACT_CHANGED,
    "parent_required": ErrorCode.PARENT_REQUIRED,
    "permission_unavailable": ErrorCode.PERMISSION_UNAVAILABLE,
}
_KNOWN_CODES = frozenset(item.value for item in ErrorCode)
_CATEGORIES = frozenset(item.value for item in ErrorCategory)


def should_calculate_total(query: Mapping[str, Any]) -> bool:
    return query.get("ok") is not False and query.get("status", "success") == "success"


def multidim_envelope(
    validation: Mapping[str, Any],
    query: Mapping[str, Any],
    total: Mapping[str, Any] | None,
    *,
    query_operation: str,
    total_operation: str,
) -> dict[str, Any]:
    query_failure = _failure("query", query_operation, query)
    total_failure = _failure("total", total_operation, total)
    failures = [item for item in (query_failure, total_failure) if item]
    primary = max(failures, key=_failure_exit_code, default=None)
    error = {**primary[1].to_dict(), "stage": primary[0]} if primary else None
    statuses = [str(query.get("status", "error"))]
    if total is not None:
        statuses.append(str(total.get("status", "error")))
    return {
        "schema_version": "gravity-insight.composite.multidim.v1",
        "ok": not failures,
        "status": combined_status(statuses),
        "exit_code": max((_failure_exit_code(item) for item in failures), default=0),
        "error": error,
        "next_action": (
            error["next_action"]
            if error
            else "Consume query and total; continue only from a bounded query envelope."
        ),
        "validation": dict(validation),
        "query": _safe_component(query, query_failure),
        "total": _safe_component(total, total_failure),
    }


def combined_status(statuses: Sequence[str]) -> str:
    if any(status in _FAILURE_STATUSES for status in statuses):
        successes = {"success", "empty", "contract_changed"}
        return "partial" if any(status in successes for status in statuses) else "error"
    if "contract_changed" in statuses:
        return "contract_changed"
    if statuses and all(status == "empty" for status in statuses):
        return "empty"
    return "success"


def _failure(
    stage: str,
    operation_id: str,
    envelope: Mapping[str, Any] | None,
) -> tuple[str, ErrorDetail] | None:
    if envelope is None:
        return None
    status = str(envelope.get("status", "error"))
    if envelope.get("ok") is not False and status in {"success", "empty"}:
        return None
    raw_value = envelope.get("error")
    raw = raw_value if isinstance(raw_value, Mapping) else {}
    code = raw.get("code", _STATUS_CODES.get(status, ErrorCode.UPSTREAM_UNAVAILABLE))
    category = raw.get("category") if raw.get("category") in _CATEGORIES else None
    try:
        detail = _error_detail(stage, status, operation_id, code, category, raw)
    except (TypeError, ValueError):
        detail = _fallback_detail(stage, operation_id)
    return stage, detail


def _error_detail(
    stage: str,
    status: str,
    operation_id: str,
    code: object,
    category: object,
    raw: Mapping[str, Any],
) -> ErrorDetail:
    normalized_code = code.value if isinstance(code, ErrorCode) else str(code).strip().upper()
    return ErrorDetail.create(
        code,
        f"Multidimensional {stage} stage failed.",
        operation_id=operation_id,
        category=category,
        retryable=raw.get("retryable") if isinstance(raw.get("retryable"), bool) else None,
        retry_after_ms=raw.get("retry_after_ms") if type(raw.get("retry_after_ms")) is int else None,
        next_action=_next_action(status, normalized_code, category),
    )


def _next_action(status: str, code: str, category: object) -> str | None:
    if status == "contract_changed":
        return "Stop automation until the multidimensional contract is re-verified."
    if code in {ErrorCode.AUTH_MISSING.value, ErrorCode.AUTH_REJECTED.value}:
        return "Run `gravity auth status`, then retry the same multidimensional request."
    if code not in _KNOWN_CODES and category == ErrorCategory.UPSTREAM.value:
        return "Retry the same multidimensional request; do not consume partial totals until exit_code is 0."
    return None


def _fallback_detail(stage: str, operation_id: str) -> ErrorDetail:
    return ErrorDetail.create(
        ErrorCode.UPSTREAM_UNAVAILABLE,
        f"Multidimensional {stage} stage failed.",
        operation_id=operation_id,
        next_action="Retry the same multidimensional request; do not consume partial totals until exit_code is 0.",
    )


def _safe_component(
    envelope: Mapping[str, Any] | None,
    failure: tuple[str, ErrorDetail] | None,
) -> dict[str, Any] | None:
    if envelope is None or failure is None:
        return dict(envelope) if envelope is not None else None
    return {
        "schema_version": envelope.get("schema_version"),
        "ok": False,
        "status": str(envelope.get("status", "error")),
        "error": failure[1].to_dict(),
    }


def _failure_exit_code(failure: tuple[str, ErrorDetail]) -> int:
    return exit_code_for_error(failure[1])


__all__ = ["combined_status", "multidim_envelope", "should_calculate_total"]
