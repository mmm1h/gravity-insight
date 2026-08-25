"""Governed Bytedance title-package family product."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from . import runtime
from .composite_batch import (
    annotate_result,
    composite_envelope,
    enforce_composite_item_budget,
    ordered_results,
    validate_composite_bounds,
)
from .composite_catalog import stable_operation
from .errors import ErrorCode, ErrorDetail, InputValidationError
from .models import load_operation_manifest
from .paths import MANIFEST_ROOT
from .promotion_performance_rows import safe_promotion_rows
from .result_audit import project_result_audit
from .actionable_error_values import actual_value


SCHEMA_VERSION = "gravity-insight.title-package.v1"
_TITLE_PACKAGE_OPERATIONS = {
    "regular": stable_operation(
        "material", "bytedance_asset_text_title_package", action="list"
    ),
    "standard": stable_operation(
        "material", "bytedance_std_asset_text_title_package", action="list"
    ),
}
OPERATION_IDS = {
    kind: operation.operation_id
    for kind, operation in _TITLE_PACKAGE_OPERATIONS.items()
}
TITLE_PACKAGE_FIELDS = frozenset({
    "app_id", "cid", "create_time", "create_user_id", "create_user_name",
    "history_click_rate", "history_cost", "id", "is_ai", "is_deleted",
    "last_3_day_click_rate", "last_3_day_cost", "modify_time", "plan_num",
    "title_list", "title_num", "title_package_name", "update_user_id",
})
_BATCH_FIELDS = frozenset({
    "operation_id", "request_id", "result_source", "ok", "status", "data", "error", "result_audit",
})
_NATIVE_FIELDS = frozenset({
    "schema_version", "result_source", "operation_id", "contract_version", "status", "source",
    "fetched_at", "schema_fingerprint", "request", "page", "data", "warnings",
    "error", "truncated", "next_page_input", "total", "safety_limits", "result_audit",
})
_PAGE_FIELDS = frozenset({
    "number", "size", "item_count", "total_pages", "total_items", "has_more",
    "pages_fetched", "fetch_strategy", "max_workers",
})
_PAGE_INFO_FIELDS = frozenset({
    "page", "page_size", "total_number", "total_page",
})
_PAGE_STRATEGIES = frozenset({
    "single_page", "serial_known_total", "parallel_known_total",
    "serial_unknown_total",
})
_FAILURE_CODES = {
    "parent_required": frozenset({ErrorCode.PARENT_REQUIRED.value}),
    "permission_unavailable": frozenset({ErrorCode.PERMISSION_UNAVAILABLE.value}),
    "semantic_error": frozenset({ErrorCode.INPUT_INVALID.value}),
    "unavailable": frozenset({
        ErrorCode.NOT_IMPLEMENTED.value,
        ErrorCode.UNKNOWN_OPERATION.value,
        ErrorCode.UNSUPPORTED.value,
    }),
}
_BUILTIN_CODES = frozenset(code.value for code in ErrorCode)
_SPECIAL_CODES = frozenset(
    code for codes in _FAILURE_CODES.values() for code in codes
)


def _opaque_fields_by_operation() -> dict[str, frozenset[str]]:
    """Derive Title Package opaque row boundaries from its compiled contract."""

    operations = {
        operation.operation_id: operation
        for operation in load_operation_manifest(MANIFEST_ROOT / "material.json")
    }
    opaque_by_operation: dict[str, frozenset[str]] = {}
    for operation_id in OPERATION_IDS.values():
        operation = operations.get(operation_id)
        if operation is None:
            raise RuntimeError(
                "compiled material manifest is missing title-package operation"
            )
        projection = operation.response_projection
        opaque = frozenset(projection.opaque_json_item_keys)
        if (
            not opaque <= set(projection.item_keys)
            or not opaque <= TITLE_PACKAGE_FIELDS
        ):
            raise RuntimeError(
                "title-package opaque JSON fields are not registered item keys"
            )
        opaque_by_operation[operation_id] = opaque
    return opaque_by_operation


_OPAQUE_FIELDS_BY_OPERATION = _opaque_fields_by_operation()


def title_packages(
    client: Any,
    app_id: int,
    package_kind: str,
    *,
    max_pages: int = 1_000,
    max_items: int = 100_000,
) -> dict[str, Any]:
    """Read every governed title-package summary for one App and one variant."""

    selected_app = _app_id(app_id)
    selected_kind = normalize_package_kind(package_kind)
    pages, items = validate_composite_bounds(max_pages, max_items, minimum_items=1)
    operation_id = OPERATION_IDS[selected_kind]
    requests = [{
        "operation_id": operation_id,
        "request_id": "title_packages",
        "inputs": {
            "app_id": selected_app,
            "filters": [],
            "order_by": [],
            "page": 1,
            "page_size": min(100, items),
        },
        "read_all": True,
    }]
    raw = runtime.call_batch(
        client,
        requests,
        concurrency=1,
        max_pages=pages,
        max_total_items=items,
    )
    result = ordered_results(raw, requests, component="title package")[0]
    enforce_composite_item_budget([result], items)
    safe = project_result_audit(_safe_result(result, operation_id), result)
    annotated = annotate_result(safe, source=selected_kind, scope="bytedance")
    if safe.get("status") == "partial" and isinstance(safe.get("data"), Mapping):
        annotated["continuation"] = safe["data"].get("next_page_input")
    envelope = composite_envelope(
        [annotated],
        schema_version=SCHEMA_VERSION,
        extra={
            "operation_id": operation_id,
            "app_id": selected_app,
            "package_kind": selected_kind,
            "source_count": 1,
        },
    )
    envelope["status"] = str(safe["status"])
    envelope["returned_items"] = _item_count(safe)
    if safe.get("ok") is not True and isinstance(safe.get("error"), Mapping):
        envelope["next_action"] = str(safe["error"].get("next_action", ""))
    return envelope


def normalize_package_kind(value: Any) -> str:
    if not isinstance(value, str) or value not in OPERATION_IDS:
        raise InputValidationError(
            f"actual value: {actual_value(value)}; " + ("package_kind must be regular or standard"), field="package_kind"
        )
    return value


def _app_id(value: Any) -> int:
    if type(value) is not int or value < 1:
        raise InputValidationError(f"actual value: {actual_value(value)}; " + ("app_id must be a positive integer"), field="app")
    return value


def _safe_result(value: Mapping[str, Any], operation_id: str) -> dict[str, Any]:
    if set(value) - _BATCH_FIELDS or value.get("operation_id") != operation_id:
        return _contract_result(operation_id)
    if value.get("request_id") != "title_packages":
        return _contract_result(operation_id)
    if value.get("ok") is not True:
        return _safe_failure(value, operation_id)
    native = value.get("data")
    status = value.get("status")
    if not _valid_native(native, operation_id, status):
        return _contract_result(operation_id)
    assert isinstance(native, Mapping)
    if status == "contract_changed_additive":
        return _contract_result(operation_id)
    data = _safe_data(native.get("data"), operation_id)
    if data is None or (status == "empty") != (not data["list"]):
        return _contract_result(operation_id)
    page = _safe_page(native.get("page"), len(data["list"]))
    continuation = _safe_continuation(
        native.get("next_page_input"), native.get("truncated")
    )
    if page is None or continuation is False:
        return _contract_result(operation_id)
    safe_native = {
        "schema_version": "gravity-insight.read.v1",
        "operation_id": operation_id,
        "status": status,
        "data": data,
        "page": page,
        "truncated": native["truncated"],
        "next_page_input": continuation,
    }
    if native["truncated"]:
        return _partial_result(operation_id, safe_native)
    return {
        "operation_id": operation_id,
        "request_id": "title_packages",
        "ok": True,
        "status": status,
        "data": safe_native,
        "error": None,
    }


def _valid_native(value: Any, operation_id: str, status: Any) -> bool:
    return bool(
        isinstance(value, Mapping)
        and status in {"success", "empty", "contract_changed_additive"}
        and value.get("schema_version") == "gravity-insight.read.v1"
        and value.get("operation_id") == operation_id
        and value.get("status") == status
        and value.get("error") in (None, {})
        and not (set(value) - _NATIVE_FIELDS)
        and isinstance(value.get("truncated"), bool)
    )


def _safe_data(value: Any, operation_id: str) -> dict[str, Any] | None:
    if not isinstance(value, Mapping) or "list" not in value:
        return None
    if set(value) - {"list", "page_info"} or not isinstance(value["list"], list):
        return None
    rows, failure = safe_promotion_rows(
        value["list"],
        allowed_fields=TITLE_PACKAGE_FIELDS,
        opaque_fields=_OPAQUE_FIELDS_BY_OPERATION.get(operation_id, frozenset()),
    )
    if failure is not None or rows is None:
        return None
    result: dict[str, Any] = {"list": rows}
    if "page_info" in value:
        info = _safe_page_info(value["page_info"])
        if info is None:
            return None
        result["page_info"] = info
    return result


def _safe_page_info(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping) or set(value) - _PAGE_INFO_FIELDS:
        return None
    if any(type(field) is not int or field < 0 for field in value.values()):
        return None
    return copy.deepcopy(dict(value))


def _safe_page(value: Any, rows: int) -> dict[str, Any] | None:
    if not isinstance(value, Mapping) or set(value) - _PAGE_FIELDS:
        return None
    required = ("number", "size", "pages_fetched", "max_workers")
    optional = ("total_pages", "total_items")
    if (
        type(value.get("item_count")) is not int
        or value["item_count"] != rows
        or any(type(value.get(field)) is not int or value[field] < 1 for field in required)
        or any(value.get(field) is not None and (
            type(value[field]) is not int or value[field] < 0
        ) for field in optional)
        or not isinstance(value.get("has_more"), bool)
        or value.get("fetch_strategy") not in _PAGE_STRATEGIES
    ):
        return None
    return copy.deepcopy(dict(value))


def _safe_continuation(value: Any, truncated: Any) -> dict[str, int] | None | bool:
    if truncated is False:
        return None if value is None else False
    if not isinstance(value, Mapping) or set(value) != {"page", "page_size"}:
        return False
    if any(type(field) is not int or field < 1 for field in value.values()):
        return False
    return {"page": value["page"], "page_size": value["page_size"]}


def _safe_failure(value: Mapping[str, Any], operation_id: str) -> dict[str, Any]:
    status, error = value.get("status"), value.get("error")
    if not isinstance(status, str) or not isinstance(error, Mapping):
        return _contract_result(operation_id)
    raw_code = error.get("code")
    code = raw_code.strip().upper() if isinstance(raw_code, str) else ""
    expected = _FAILURE_CODES.get(status)
    if code not in _BUILTIN_CODES:
        return _contract_result(operation_id)
    if expected is not None and code not in expected:
        return _contract_result(operation_id)
    if expected is None and (status != "error" or code in _SPECIAL_CODES):
        return _contract_result(operation_id)
    detail = ErrorDetail.create(
        code,
        "The governed title-package read could not complete.",
        operation_id=operation_id,
        retry_after_ms=(
            error.get("retry_after_ms")
            if code == ErrorCode.RATE_LIMITED.value else None
        ),
    )
    if error.get("category") != detail.category:
        return _contract_result(operation_id)
    return {
        "operation_id": operation_id,
        "request_id": "title_packages",
        "ok": False,
        "status": status,
        "data": None,
        "error": detail.to_dict(),
    }


def _partial_result(
    operation_id: str, data: Mapping[str, Any]
) -> dict[str, Any]:
    detail = ErrorDetail.create(
        ErrorCode.PAGINATION_LIMIT,
        "The title-package read stopped at its complete-read safety bound.",
        operation_id=operation_id,
        next_action="Increase max_pages or max_items within the documented limits.",
    )
    return {
        "operation_id": operation_id,
        "request_id": "title_packages",
        "ok": False,
        "status": "partial",
        "data": copy.deepcopy(dict(data)),
        "error": detail.to_dict(),
    }


def _contract_result(operation_id: str) -> dict[str, Any]:
    detail = ErrorDetail.create(
        ErrorCode.CONTRACT_CHANGED,
        "The stable title-package result contract changed.",
        operation_id=operation_id,
        next_action="Stop automation until the title-package contract is re-verified.",
    )
    return {
        "operation_id": operation_id,
        "request_id": "title_packages",
        "ok": False,
        "status": "contract_changed",
        "data": None,
        "error": detail.to_dict(),
    }


def _item_count(value: Mapping[str, Any]) -> int:
    native = value.get("data")
    data = native.get("data") if isinstance(native, Mapping) else None
    rows = data.get("list") if isinstance(data, Mapping) else None
    return len(rows) if isinstance(rows, list) else 0


__all__ = [
    "OPERATION_IDS",
    "SCHEMA_VERSION",
    "TITLE_PACKAGE_FIELDS",
    "normalize_package_kind",
    "title_packages",
]
