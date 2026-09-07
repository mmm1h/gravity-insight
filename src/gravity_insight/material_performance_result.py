"""Fail-closed result contract for the material performance product."""

from __future__ import annotations

import copy
from collections.abc import Mapping
import re
from typing import Any

from .component_aggregate import (
    aggregate_exit_code,
    aggregate_status,
    component_exit_code,
)
from .composite_catalog import stable_operation
from .composite_result import bounded_structural_drift_diagnostics
from .errors import (
    ErrorCategory,
    ErrorCode,
    ErrorDetail,
    ManifestError,
    exit_code_for_error,
)
from .models import load_operation_manifest
from .paths import MANIFEST_ROOT
from .promotion_performance_rows import safe_promotion_rows
from .result_audit import (
    aggregate_result_audit,
    project_result_audit,
    result_response_drift,
)
from .result_source import GOVERNED_PRODUCT, result_source


SCHEMA_VERSION = "gravity-insight.material-performance.v1"
MATERIAL_REPORT_OPERATION = stable_operation(
    "material", "report", action="query"
).operation_id


def _material_source_row_contract() -> tuple[frozenset[str], frozenset[str]]:
    operations = load_operation_manifest(MANIFEST_ROOT / "candidates.json")
    matches = tuple(
        operation
        for operation in operations
        if operation.operation_id == MATERIAL_REPORT_OPERATION
    )
    if len(matches) != 1:
        raise ManifestError(
            "compiled candidate manifest must contain one material report operation"
        )
    projection = matches[0].response_projection
    fields = frozenset(projection.item_keys)
    opaque = frozenset(projection.opaque_json_item_keys)
    if not fields or opaque - fields:
        raise ManifestError(
            "compiled material report row projection is internally inconsistent"
        )
    return fields, opaque


MATERIAL_ROW_FIELDS = frozenset(
    {
        "file_name", "gravity_material_id", "material_id", "stat_cost", "ctr",
        "convert_rate", "cost", "conversions_rate", "charge", "action_ratio",
        "conversion_ratio", "click_rate", "AppRealRegisterCnt",
        "AppGamePayUserCntStandardAtv",
    }
)
_MATERIAL_SOURCE_ROW_FIELDS, _MATERIAL_OPAQUE_JSON_FIELDS = (
    _material_source_row_contract()
)
if MATERIAL_ROW_FIELDS - _MATERIAL_SOURCE_ROW_FIELDS:
    raise ManifestError(
        "material performance row fields must be registered source fields"
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
        return _contract_failure(platform, "component_shape", "$")
    if (
        value.get("operation_id") != MATERIAL_REPORT_OPERATION
        or value.get("request_id") != platform
    ):
        return _contract_failure(
            platform, "component_identity", "$.operation_id_or_request_id"
        )
    status = value.get("status")
    if not isinstance(status, str):
        return _contract_failure(platform, "component_status_type", "$.status")
    if value.get("ok") is True and status in _SUCCESS_STATUSES:
        return _safe_success(value, platform, status, max_pages=max_pages)
    if value.get("ok") is False and status in _FAILURE_STATUSES:
        error = _safe_error(value.get("error"), platform)
        if error is None:
            return _contract_failure(platform, "component_error_shape", "$.error")
        if not _failure_matches(status, error["code"]):
            return _contract_failure(
                platform, "component_error_status", "$.status_or_error.code"
            )
        if error["code"] == ErrorCode.CONTRACT_CHANGED.value:
            inner = value.get("data")
            if result_response_drift(value) is not None or result_response_drift(
                inner
            ) is not None:
                return project_result_audit(contract_component(platform), value)
            return project_result_audit(
                _contract_failure(
                    platform, "component_contract_status", "$.status"
                ),
                value,
            )
        return {
            "platform": platform,
            "operation_id": MATERIAL_REPORT_OPERATION,
            "ok": False,
            "status": status,
            "data": None,
            "page": None,
            "error": error,
        }
    return _contract_failure(platform, "component_status", "$.ok_or_status")


def _safe_success(
    value: Mapping[str, Any],
    platform: str,
    status: str,
    *,
    max_pages: int,
) -> dict[str, Any]:
    if value.get("error") not in (None, {}):
        return _contract_failure(platform, "success_error", "$.error")
    envelope = value.get("data")
    if not isinstance(envelope, Mapping):
        return _contract_failure(platform, "read_envelope_type", "$.data")
    if (
        envelope.get("schema_version") != "gravity-insight.read.v1"
        or envelope.get("operation_id") != MATERIAL_REPORT_OPERATION
        or envelope.get("status") != status
        or envelope.get("error") not in (None, {})
    ):
        return _contract_failure(platform, "read_envelope_identity", "$.data")
    data = envelope.get("data")
    if not isinstance(data, Mapping) or set(data) - {"list", "page_info"}:
        return _contract_failure(platform, "read_data_shape", "$.data.data")
    rows, failure = _safe_rows_with_failure(data.get("list"))
    if failure is not None or rows is None:
        check, path = failure or ("row_projection", "$.data.data.list")
        return _contract_failure(platform, check, path)
    if (status == "empty") != (not rows):
        return _contract_failure(platform, "row_status", "$.data.status")
    page = _safe_page(envelope.get("page"), len(rows), max_pages=max_pages)
    if page is None:
        return _contract_failure(platform, "page_receipt", "$.data.page")
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
    rows, failure = _safe_rows_with_failure(value)
    return rows if failure is None else None


def _safe_rows_with_failure(
    value: Any,
) -> tuple[list[dict[str, Any]] | None, tuple[str, str] | None]:
    rows, failure = safe_promotion_rows(
        value,
        allowed_fields=_MATERIAL_SOURCE_ROW_FIELDS,
        opaque_fields=_MATERIAL_OPAQUE_JSON_FIELDS,
    )
    if rows is None or failure is not None:
        return rows, failure
    return [
        {
            str(key): item
            for key, item in row.items()
            if key in MATERIAL_ROW_FIELDS
        }
        for row in rows
    ], None


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


def _contract_failure(platform: str, check: str, path: str) -> dict[str, Any]:
    result = contract_component(platform)
    result["drift_diagnostics"] = bounded_structural_drift_diagnostics(
        MATERIAL_REPORT_OPERATION, [(check, path)]
    )
    return result


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
        "result_source": result_source(GOVERNED_PRODUCT),
        "ok": False,
        "status": "contract_changed",
        "exit_code": exit_code_for_error(detail),
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
    exit_code = aggregate_exit_code(failures)
    status = aggregate_status(results, failures)
    return aggregate_result_audit({
        "schema_version": SCHEMA_VERSION,
        "result_source": result_source(GOVERNED_PRODUCT),
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
    }, results)


def _primary_error(failures: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not failures:
        return None
    selected = max(failures, key=component_exit_code)
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
