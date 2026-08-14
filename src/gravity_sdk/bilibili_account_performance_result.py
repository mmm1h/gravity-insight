"""Fail-closed result contract for Bilibili account performance."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .errors import (
    ErrorCode,
    ErrorDetail,
    error_detail_from_exception,
    exit_code_for_error,
)
from .bilibili_account_performance_validation import (
    ROW_FIELDS,
    TOTAL_FIELDS,
    request_inputs,
    safe_native_payload,
    safe_public_page,
    safe_row,
    safe_rows,
    safe_total,
)


SCHEMA_VERSION = "gravity-insight.bilibili-account-performance.v1"

_ENVELOPE_FIELDS = frozenset({
    "schema_version",
    "ok",
    "status",
    "exit_code",
    "operation_id",
    "requested_date_range",
    "returned_items",
    "limits",
    "page",
    "data",
    "error",
    "next_action",
})
_ERROR_FIELDS = frozenset({
    "code", "category", "message", "field", "retryable",
    "retry_after_ms", "next_action",
})
_NATIVE_FIELDS = frozenset({
    "schema_version", "status", "source", "fetched_at", "schema_fingerprint",
    "operation_id", "contract_version", "request", "page", "data", "warnings",
    "error",
})
_SUCCESS_ACTION = (
    "Consume the governed Bilibili account and product performance rows; "
    "the date range describes the request, not a row-level date field."
)
_ACTIONS = {
    "partial": "Increase the bounded page or item limit and retry the same date range.",
    "unavailable": "Use the capability gap as terminal until this governed read is available.",
    "contract_changed": (
        "Stop automation until the Bilibili account performance contract is re-verified."
    ),
    "error": "Inspect the safe error category and retry the same bounded request if allowed.",
}
_MESSAGES = {
    "partial": "Bilibili account performance stopped at its pagination safety bound.",
    "unavailable": "Bilibili account performance is unavailable to this caller.",
    "contract_changed": "Bilibili account performance contract changed.",
    "error": "Bilibili account performance could not complete its governed read.",
}
_BUILTIN_CODES = frozenset(code.value for code in ErrorCode)
_UNAVAILABLE_CODES = frozenset({
    ErrorCode.UNKNOWN_OPERATION.value,
    ErrorCode.PARENT_REQUIRED.value,
    ErrorCode.PERMISSION_UNAVAILABLE.value,
    ErrorCode.UNSUPPORTED.value,
    ErrorCode.NOT_IMPLEMENTED.value,
})


def result_from_native(
    value: Any,
    *,
    operation_id: str,
    window: tuple[str, str],
    max_pages: int,
    max_items: int,
    max_workers: int,
) -> dict[str, Any]:
    """Rebuild a native read or exception into the product envelope."""

    options = _options(operation_id, window, max_pages, max_items, max_workers)
    if isinstance(value, BaseException):
        return _failure_from_exception(value, **options)
    if not isinstance(value, Mapping) or set(value) != _NATIVE_FIELDS:
        return contract_result(**options)
    status = value.get("status")
    if status in {"contract_changed", "contract_changed_additive"}:
        return failure_result(ErrorCode.CONTRACT_CHANGED, **options)
    if status not in {"success", "empty"}:
        return _failure_from_native(value, **options)
    selected = _native_success(value, **options)
    if selected is None:
        return contract_result(**options)
    rows, total, page = selected
    try:
        return success_result(rows=rows, total=total, page=page, **options)
    except ValueError:
        return contract_result(**options)


def success_result(
    *,
    operation_id: str,
    window: tuple[str, str],
    rows: list[Mapping[str, Any]],
    total: Mapping[str, Any] | None,
    page: Mapping[str, Any],
    max_pages: int,
    max_items: int,
    max_workers: int,
) -> dict[str, Any]:
    """Build one complete, request-scoped success envelope."""

    safe_rows = [safe_row(row) for row in rows]
    selected_total = safe_total(total)
    limits = _limits(max_pages, max_items, max_workers)
    safe_page = safe_public_page(page, len(safe_rows), limits)
    if any(row is None for row in safe_rows) or selected_total is False or safe_page is None:
        raise ValueError("Bilibili account performance success contract is invalid")
    if len(safe_rows) > max_items:
        raise ValueError("Bilibili account performance item budget is invalid")
    return {
        "schema_version": SCHEMA_VERSION,
        "ok": True,
        "status": "empty" if not safe_rows else "success",
        "exit_code": 0,
        "operation_id": operation_id,
        "requested_date_range": _date_range(window),
        "returned_items": len(safe_rows),
        "limits": limits,
        "page": safe_page,
        "data": {
            "list": [dict(row) for row in safe_rows if row is not None],
            "total": None if selected_total is None else dict(selected_total),
        },
        "error": None,
        "next_action": _SUCCESS_ACTION,
    }


def failure_result(
    code: ErrorCode | str,
    *,
    operation_id: str,
    window: tuple[str, str],
    max_pages: int,
    max_items: int,
    max_workers: int,
    retry_after_ms: int | None = None,
) -> dict[str, Any]:
    """Build a fixed-vocabulary failure without returning native values."""

    normalized = code.value if isinstance(code, ErrorCode) else str(code).strip().upper()
    status = _failure_status(normalized)
    retry_after = retry_after_ms if normalized == ErrorCode.RATE_LIMITED.value else None
    detail = ErrorDetail.create(
        normalized,
        _MESSAGES[status],
        operation_id=operation_id,
        field=status,
        retry_after_ms=retry_after,
        next_action=_ACTIONS[status],
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "ok": False,
        "status": status,
        "exit_code": exit_code_for_error(detail),
        "operation_id": operation_id,
        "requested_date_range": _date_range(window),
        "returned_items": 0,
        "limits": _limits(max_pages, max_items, max_workers),
        "page": None,
        "data": {"list": [], "total": None},
        "error": detail.to_dict(),
        "next_action": detail.next_action,
    }


def sanitize_product_result(
    value: Any,
    *,
    operation_id: str,
    window: tuple[str, str],
    max_pages: int,
    max_items: int,
    max_workers: int,
) -> dict[str, Any]:
    """Rebuild an SDK result against the exact Plan request."""

    options = _options(operation_id, window, max_pages, max_items, max_workers)
    if not _product_identity(value, **options):
        return contract_result(**options)
    assert isinstance(value, Mapping)
    if value.get("ok") is True and value.get("status") in {"success", "empty"}:
        rebuilt = _resanitize_success(value, **options)
    elif value.get("ok") is False:
        rebuilt = _resanitize_failure(value, **options)
    else:
        rebuilt = None
    return rebuilt if rebuilt is not None and value == rebuilt else contract_result(**options)


def contract_result(
    *,
    operation_id: str,
    window: tuple[str, str],
    max_pages: int,
    max_items: int,
    max_workers: int,
) -> dict[str, Any]:
    return failure_result(
        ErrorCode.CONTRACT_CHANGED,
        operation_id=operation_id,
        window=window,
        max_pages=max_pages,
        max_items=max_items,
        max_workers=max_workers,
    )


def product_item_count(value: Any) -> int:
    if not isinstance(value, Mapping) or value.get("schema_version") != SCHEMA_VERSION:
        return 0
    data = value.get("data")
    rows = data.get("list") if isinstance(data, Mapping) else None
    returned = value.get("returned_items")
    return returned if (
        value.get("ok") is True
        and isinstance(rows, list)
        and type(returned) is int
        and returned == len(rows)
    ) else 0


def _native_success(
    value: Mapping[str, Any],
    *,
    operation_id: str,
    window: tuple[str, str],
    max_pages: int,
    max_items: int,
    max_workers: int,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None, dict[str, Any]] | None:
    if (
        value.get("schema_version") != "gravity-insight.read.v1"
        or value.get("operation_id") != operation_id
        or value.get("error") not in (None, {})
        or value.get("request") != {"inputs": request_inputs(window, max_items)}
    ):
        return None
    return safe_native_payload(
        value,
        max_pages=max_pages,
        max_items=max_items,
        max_workers=max_workers,
    )


def _failure_from_exception(error: BaseException, **options: Any) -> dict[str, Any]:
    detail = error_detail_from_exception(error, operation_id=options["operation_id"])
    code = detail.code if detail.code in _BUILTIN_CODES else ErrorCode.CONTRACT_CHANGED.value
    return failure_result(
        code,
        retry_after_ms=detail.retry_after_ms,
        **options,
    )


def _failure_from_native(value: Mapping[str, Any], **options: Any) -> dict[str, Any]:
    status = str(value.get("status", ""))
    error = value.get("error")
    raw_code = error.get("code") if isinstance(error, Mapping) else None
    code = str(raw_code).strip().upper() if isinstance(raw_code, str) else ""
    defaults = {
        "contract_changed": ErrorCode.CONTRACT_CHANGED.value,
        "contract_changed_additive": ErrorCode.CONTRACT_CHANGED.value,
        "parent_required": ErrorCode.PARENT_REQUIRED.value,
        "permission_unavailable": ErrorCode.PERMISSION_UNAVAILABLE.value,
        "unavailable": ErrorCode.NOT_IMPLEMENTED.value,
    }
    code = code or defaults.get(status, ErrorCode.UPSTREAM_UNAVAILABLE.value)
    if code not in _BUILTIN_CODES:
        return contract_result(**options)
    retry_after = error.get("retry_after_ms") if isinstance(error, Mapping) else None
    if retry_after is not None and (type(retry_after) is not int or retry_after < 0):
        return contract_result(**options)
    return failure_result(code, retry_after_ms=retry_after, **options)


def _resanitize_success(value: Mapping[str, Any], **options: Any) -> dict[str, Any] | None:
    data = value.get("data")
    if not isinstance(data, Mapping) or set(data) != {"list", "total"}:
        return None
    rows = safe_rows(data.get("list"))
    total = safe_total(data.get("total"))
    if rows is None or total is False:
        return None
    try:
        return success_result(
            rows=rows,
            total=None if total is None else dict(total),
            page=value.get("page"),
            **options,
        )
    except (TypeError, ValueError):
        return None


def _resanitize_failure(value: Mapping[str, Any], **options: Any) -> dict[str, Any] | None:
    error = value.get("error")
    data = value.get("data")
    if (
        not isinstance(error, Mapping)
        or set(error) != _ERROR_FIELDS
        or data != {"list": [], "total": None}
        or value.get("page") is not None
        or value.get("returned_items") != 0
    ):
        return None
    code = error.get("code")
    retry_after = error.get("retry_after_ms")
    if not isinstance(code, str) or code not in _BUILTIN_CODES:
        return None
    try:
        return failure_result(code, retry_after_ms=retry_after, **options)
    except (TypeError, ValueError):
        return None


def _product_identity(value: Any, **options: Any) -> bool:
    return bool(
        isinstance(value, Mapping)
        and set(value) == _ENVELOPE_FIELDS
        and value.get("schema_version") == SCHEMA_VERSION
        and value.get("operation_id") == options["operation_id"]
        and value.get("requested_date_range") == _date_range(options["window"])
        and value.get("limits") == _limits(
            options["max_pages"], options["max_items"], options["max_workers"]
        )
    )


def _failure_status(code: str) -> str:
    if code == ErrorCode.PAGINATION_LIMIT.value:
        return "partial"
    if code == ErrorCode.CONTRACT_CHANGED.value:
        return "contract_changed"
    return "unavailable" if code in _UNAVAILABLE_CODES else "error"


def _date_range(window: tuple[str, str]) -> dict[str, Any]:
    return {"start": window[0], "end": window[1], "inclusive": True}


def _limits(max_pages: int, max_items: int, max_workers: int) -> dict[str, int]:
    values = {
        "max_pages": (max_pages, 1_000),
        "max_items": (max_items, 100_000),
        "max_workers": (max_workers, 24),
    }
    if any(type(value) is not int or not 1 <= value <= maximum for value, maximum in values.values()):
        raise ValueError("Bilibili account performance limits are invalid")
    return {key: value for key, (value, _maximum) in values.items()}


def _options(
    operation_id: str,
    window: tuple[str, str],
    max_pages: int,
    max_items: int,
    max_workers: int,
) -> dict[str, Any]:
    return {
        "operation_id": operation_id,
        "window": window,
        "max_pages": max_pages,
        "max_items": max_items,
        "max_workers": max_workers,
    }


__all__ = [
    "ROW_FIELDS",
    "SCHEMA_VERSION",
    "TOTAL_FIELDS",
    "contract_result",
    "failure_result",
    "product_item_count",
    "result_from_native",
    "sanitize_product_result",
    "success_result",
]
