"""Fail-closed result contract for the material performance product."""

from __future__ import annotations

import copy
from collections.abc import Mapping
import math
import re
from typing import Any

from .composite_catalog import stable_operation
from .errors import ErrorCategory, ErrorCode, ErrorDetail


SCHEMA_VERSION = "gravity-insight.material-performance.v1"
MATERIAL_REPORT_OPERATION = stable_operation(
    "material", "report", action="query"
).operation_id
MATERIAL_ROW_FIELDS = frozenset(
    {
        "file_name", "gravity_material_id", "stat_cost", "ctr", "convert_rate",
        "cost", "conversions_rate", "charge", "action_ratio",
        "conversion_ratio", "click_rate", "AppRealRegisterCnt",
        "AppGamePayUserCntStandardAtv",
    }
)
_SUCCESS_STATUSES = frozenset({"success", "empty"})
_FAILURE_STATUSES = frozenset(
    {
        "contract_changed", "error", "semantic_error", "unavailable", "parent_required",
        "permission_unavailable",
    }
)
_FAILURE_CODES = {
    "contract_changed": frozenset({ErrorCode.CONTRACT_CHANGED.value}),
    "parent_required": frozenset({ErrorCode.PARENT_REQUIRED.value}),
    "permission_unavailable": frozenset({ErrorCode.PERMISSION_UNAVAILABLE.value}),
    "semantic_error": frozenset({ErrorCode.INPUT_INVALID.value}),
    "unavailable": frozenset(
        {
            ErrorCode.NOT_IMPLEMENTED.value,
            ErrorCode.UNKNOWN_OPERATION.value,
            ErrorCode.UNSUPPORTED.value,
        }
    ),
}
_SPECIAL_FAILURE_CODES = frozenset(
    code
    for status, codes in _FAILURE_CODES.items()
    if status != "semantic_error"
    for code in codes
)
_ERROR_CODE = re.compile(r"^[A-Z][A-Z0-9_]{2,63}$")
_ERROR_FIELD = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,127}$")
_CATEGORIES = frozenset(item.value for item in ErrorCategory)
_MAX_RECEIPT_INTEGER = (1 << 31) - 1
_BUILTIN_DEFAULTS = {
    code.value: (
        ErrorDetail.create(code, "default check").category,
        ErrorDetail.create(code, "default check").retryable,
    )
    for code in ErrorCode
}


def material_performance_item_count(value: Any) -> int:
    if not isinstance(value, Mapping):
        return 0
    results = value.get("results")
    if not isinstance(results, list):
        return 0
    return sum(material_component_item_count(item) for item in results)


def material_component_item_count(value: Any) -> int:
    if not isinstance(value, Mapping) or value.get("ok") is not True:
        return 0
    data = value.get("data")
    rows = data.get("list") if isinstance(data, Mapping) else None
    return len(rows) if isinstance(rows, list) else 0


def safe_component(
    value: Any,
    platform: str,
    *,
    max_pages: int,
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return contract_component(platform)
    if (
        value.get("operation_id") != MATERIAL_REPORT_OPERATION
        or value.get("request_id") != platform
    ):
        return contract_component(platform)
    status = value.get("status")
    if not isinstance(status, str):
        return contract_component(platform)
    if value.get("ok") is True and status in _SUCCESS_STATUSES:
        return _safe_success(value, platform, status, max_pages=max_pages)
    if value.get("ok") is False and status in _FAILURE_STATUSES:
        error = _safe_error(value.get("error"), platform)
        if error is None or not _failure_matches(status, error["code"]):
            return contract_component(platform)
        if error["code"] == ErrorCode.CONTRACT_CHANGED.value:
            return contract_component(platform)
        return {
            "platform": platform,
            "operation_id": MATERIAL_REPORT_OPERATION,
            "ok": False,
            "status": status,
            "data": None,
            "page": None,
            "error": error,
        }
    return contract_component(platform)


def _safe_success(
    value: Mapping[str, Any],
    platform: str,
    status: str,
    *,
    max_pages: int,
) -> dict[str, Any]:
    envelope = value.get("data")
    if not isinstance(envelope, Mapping):
        return contract_component(platform)
    if (
        envelope.get("schema_version") != "gravity-insight.read.v1"
        or envelope.get("operation_id") != MATERIAL_REPORT_OPERATION
        or envelope.get("status") != status
        or envelope.get("error") not in (None, {})
    ):
        return contract_component(platform)
    data = envelope.get("data")
    if not isinstance(data, Mapping) or set(data) - {"list", "page_info"}:
        return contract_component(platform)
    rows = _safe_rows(data.get("list"))
    if rows is None:
        return contract_component(platform)
    if (status == "empty") != (not rows):
        return contract_component(platform)
    page = _safe_page(envelope.get("page"), len(rows), max_pages=max_pages)
    if page is None:
        return contract_component(platform)
    return {
        "platform": platform,
        "operation_id": MATERIAL_REPORT_OPERATION,
        "ok": True,
        "status": status,
        "data": {"list": rows},
        "page": page,
        "error": None,
    }


def _safe_rows(value: Any) -> list[dict[str, Any]] | None:
    if not isinstance(value, list):
        return None
    rows: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping) or set(item) - MATERIAL_ROW_FIELDS:
            return None
        row: dict[str, Any] = {}
        for key, field_value in item.items():
            if not _json_scalar(field_value):
                return None
            row[str(key)] = copy.deepcopy(field_value)
        rows.append(row)
    return rows


def _safe_page(value: Any, rows: int, *, max_pages: int) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    item_count = value.get("item_count")
    pages_fetched = value.get("pages_fetched")
    number = value.get("number")
    size = value.get("size")
    total_pages = value.get("total_pages")
    total_items = value.get("total_items")
    receipt = (item_count, pages_fetched, value.get("max_workers"), number, size)
    if not _valid_page_receipt(
        receipt,
        rows=rows,
        max_pages=max_pages,
        total_pages=total_pages,
        total_items=total_items,
        has_more=value.get("has_more"),
    ):
        return None
    result: dict[str, Any] = {
        "item_count": item_count,
        "pages_fetched": pages_fetched,
        "max_workers": 1,
        "number": number,
        "size": size,
        "has_more": False,
    }
    if total_pages is not None:
        result["total_pages"] = total_pages
    if total_items is not None:
        result["total_items"] = total_items
    return result


def _valid_total(value: Any, observed: int) -> bool:
    return value is None or (
        type(value) is int and observed <= value <= _MAX_RECEIPT_INTEGER
    )


def _valid_page_receipt(
    receipt: tuple[Any, Any, Any, Any, Any],
    *,
    rows: int,
    max_pages: int,
    total_pages: Any,
    total_items: Any,
    has_more: Any,
) -> bool:
    item_count, pages_fetched, workers, number, size = receipt
    integers = all(type(value) is int for value in receipt)
    return bool(
        integers
        and item_count == rows
        and 1 <= pages_fetched <= max_pages
        and workers == 1
        and number == 1
        and 1 <= size <= 1_000
        and has_more is False
        and _valid_page_total(total_pages, pages_fetched, rows)
        and _valid_total(total_items, rows)
    )


def _valid_page_total(value: Any, pages_fetched: int, rows: int) -> bool:
    if rows == 0 and type(value) is int and value == 0 and pages_fetched == 1:
        return True
    return _valid_total(value, pages_fetched)


def _safe_error(value: Any, platform: str) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    code = value.get("code")
    category = value.get("category")
    if (
        not isinstance(code, str)
        or not _ERROR_CODE.fullmatch(code)
        or not isinstance(category, str)
        or category not in _CATEGORIES
        or (
            code in _BUILTIN_DEFAULTS
            and category != _BUILTIN_DEFAULTS[code][0]
        )
    ):
        return None
    field = value.get("field")
    if field is not None and (
        not isinstance(field, str) or not _ERROR_FIELD.fullmatch(field)
    ):
        return None
    retryable = value.get("retryable", False)
    retry_after = value.get("retry_after_ms")
    if not _valid_retry_receipt(code, retryable, retry_after):
        return None
    return {
        "code": code,
        "category": category,
        "message": f"Material performance query failed for {platform}.",
        "field": "result" if field is not None else None,
        "retryable": retryable,
        "retry_after_ms": retry_after,
        "next_action": _failure_action(code, category),
    }


def _valid_retry_receipt(code: str, retryable: Any, retry_after: Any) -> bool:
    if not isinstance(retryable, bool):
        return False
    default = _BUILTIN_DEFAULTS.get(code)
    if default is not None and retryable is not default[1]:
        return False
    if retry_after is None:
        return True
    return bool(
        retryable
        and type(retry_after) is int
        and 0 <= retry_after <= _MAX_RECEIPT_INTEGER
    )


def contract_component(platform: str) -> dict[str, Any]:
    detail = ErrorDetail.create(
        ErrorCode.CONTRACT_CHANGED,
        f"Material performance result contract changed for {platform}.",
        operation_id=MATERIAL_REPORT_OPERATION,
        next_action=(
            "Stop this material performance automation until the stable result "
            "contract is re-verified."
        ),
    )
    return {
        "platform": platform,
        "operation_id": MATERIAL_REPORT_OPERATION,
        "ok": False,
        "status": "contract_changed",
        "data": None,
        "page": None,
        "error": detail.to_dict(),
    }


def contract_result() -> dict[str, Any]:
    detail = ErrorDetail.create(
        ErrorCode.CONTRACT_CHANGED,
        "Material performance result contract changed.",
        operation_id=MATERIAL_REPORT_OPERATION,
        next_action=(
            "Stop this Plan until the material performance contract is re-verified."
        ),
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "ok": False,
        "status": "contract_changed",
        "exit_code": 3,
        "operation_id": MATERIAL_REPORT_OPERATION,
        "error": detail.to_dict(),
        "next_action": detail.next_action,
    }


def product_envelope(
    results: list[dict[str, Any]],
    *,
    app_count: int,
    window: tuple[str, str],
    platforms: tuple[str, ...],
    max_pages: int,
    max_items: int,
    max_workers: int,
    returned_items: int,
) -> dict[str, Any]:
    failures = [item for item in results if item.get("ok") is not True]
    success_count = len(results) - len(failures)
    exit_code = max((_component_exit_code(item) for item in failures), default=0)
    contract_changed = any(
        item.get("status") == "contract_changed" for item in failures
    )
    status = (
        "contract_changed"
        if contract_changed
        else "partial"
        if failures and success_count
        else "error"
        if failures
        else "empty"
        if all(item.get("status") == "empty" for item in results)
        else "success"
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "ok": not failures,
        "status": status,
        "exit_code": exit_code,
        "operation_id": MATERIAL_REPORT_OPERATION,
        "error": _primary_error(failures),
        "app_count": app_count,
        "date_range": {"start": window[0], "end": window[1], "inclusive": True},
        "platforms": list(platforms),
        "platform_count": len(platforms),
        "total_count": len(results),
        "success_count": success_count,
        "failure_count": len(failures),
        "returned_items": returned_items,
        "limits": {
            "max_pages_per_platform": max_pages,
            "max_items_shared": max_items,
            "platform_workers": min(max_workers, len(platforms)),
            "page_workers_per_platform": 1,
        },
        "results": results,
        "next_action": (
            "Consume platform results in declaration order."
            if not failures
            else "Inspect failed platforms; successful independent platforms remain usable."
        ),
    }


def _component_exit_code(value: Mapping[str, Any]) -> int:
    error = value.get("error")
    category = error.get("category") if isinstance(error, Mapping) else None
    return {
        ErrorCategory.CALLER.value: 2,
        ErrorCategory.UPSTREAM.value: 3,
        ErrorCategory.LOCAL.value: 4,
    }.get(str(category), 4)


def _primary_error(failures: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not failures:
        return None
    selected = max(failures, key=_component_exit_code)
    error = selected.get("error")
    if not isinstance(error, Mapping):
        return contract_component(str(selected.get("platform", "unknown")))["error"]
    return copy.deepcopy(dict(error))


def _failure_action(code: str, category: str) -> str:
    if code == ErrorCode.CONTRACT_CHANGED.value:
        return "Stop this Plan until the material performance contract is re-verified."
    if code in {ErrorCode.AUTH_MISSING.value, ErrorCode.AUTH_REJECTED.value}:
        return "Run `gravity auth status`, then retry the same material performance query."
    if category == ErrorCategory.CALLER.value:
        return "Correct the selected App, dates, or platform and retry."
    return "Retry only the failed platform; do not replay successful siblings."


def _failure_matches(status: str, code: str) -> bool:
    expected = _FAILURE_CODES.get(status)
    if expected is not None:
        return code in expected
    return code not in _SPECIAL_FAILURE_CODES


def _json_scalar(value: Any) -> bool:
    if value is None or isinstance(value, bool):
        return True
    if isinstance(value, str):
        return len(value) <= 8_192
    if type(value) is int:
        return value.bit_length() <= 256
    return isinstance(value, float) and math.isfinite(value)


__all__ = [
    "MATERIAL_REPORT_OPERATION",
    "MATERIAL_ROW_FIELDS",
    "SCHEMA_VERSION",
    "contract_component",
    "contract_result",
    "material_component_item_count",
    "material_performance_item_count",
    "product_envelope",
    "safe_component",
]
