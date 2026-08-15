"""Bounded Bytedance advertiser account profile product."""

from __future__ import annotations

import copy
import math
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
from .errors import ContractChangedError, ErrorCode, ErrorDetail
from .promotion_performance_request import normalize_promotion_window


SCHEMA_VERSION = "gravity-insight.advertiser-profile.v1"
OPERATION_ID = stable_operation(
    "promotion", "advertiser_performance", action="list"
).operation_id
INPUT_SCHEMA_VERSION = "gravity-insight.advertiser-profile-input.v1"
_SUCCESS = frozenset({"success", "empty", "contract_changed_additive"})
_BATCH_FIELDS = frozenset(
    {"operation_id", "request_id", "result_source", "ok", "status", "data", "error"}
)
_NATIVE_FIELDS = frozenset({
    "schema_version", "result_source", "operation_id", "contract_version", "status", "source",
    "fetched_at", "schema_fingerprint", "request", "page", "data", "warnings",
    "error", "truncated", "next_page_input", "total", "safety_limits",
})
_DATA_FIELDS = frozenset({"list", "page_info", "total", "update_at"})
_ROW_FIELDS = frozenset({
    "advertiser_agent_id", "advertiser_agent_name", "advertiser_balance",
    "advertiser_budget", "advertiser_budget_mode", "advertiser_id",
    "advertiser_name", "advertiser_remark", "advertiser_system_status",
    "app_id", "app_name", "company", "delay", "operator_id",
    "operator_name", "project_list", "stat_cost",
})
_TOTAL_FIELDS = frozenset({"stat_cost"})
_PAGE_INFO_FIELDS = frozenset(
    {"page", "page_size", "total_number", "total_page"}
)
_PAGE_FIELDS = frozenset({
    "number", "size", "item_count", "total_pages", "total_items", "has_more",
    "pages_fetched", "fetch_strategy", "max_workers",
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
        ErrorCode.NOT_IMPLEMENTED.value, ErrorCode.UNKNOWN_OPERATION.value,
        ErrorCode.UNSUPPORTED.value,
    }),
}
_BUILTIN_CODES = frozenset(code.value for code in ErrorCode)
_SPECIAL_FAILURE_CODES = frozenset(
    code for codes in _FAILURE_CODES.values() for code in codes
)


def advertiser_profile(
    client: Any,
    start: str,
    end: str,
    *,
    max_pages: int = 1_000,
    max_items: int = 100_000,
) -> dict[str, Any]:
    """Read all governed advertiser rows for one explicit date window."""

    window = normalize_promotion_window(start, end)
    pages, items = validate_composite_bounds(
        max_pages, max_items, minimum_items=1
    )
    requests = [{
        "operation_id": OPERATION_ID,
        "request_id": "advertisers",
        "inputs": {
            "date_list": list(window),
            "page": 1,
            "page_size": min(10, items),
        },
        "read_all": True,
    }]
    batch = runtime.call_batch(
        client,
        requests,
        concurrency=1,
        max_pages=pages,
        max_total_items=items,
    )
    result = ordered_results(batch, requests, component="advertiser profile")[0]
    enforce_composite_item_budget([result], items)
    safe = _safe_result(result)
    annotated = annotate_result(
        safe, source="advertisers", scope="bytedance"
    )
    envelope = composite_envelope(
        [annotated],
        schema_version=SCHEMA_VERSION,
        extra={
            "date_range": {"start": window[0], "end": window[1]},
            "source_count": 1,
            "scopes": ["bytedance"],
        },
    )
    envelope["status"] = str(safe.get("status", "error"))
    if safe.get("ok") is not True and isinstance(safe.get("error"), Mapping):
        envelope["next_action"] = str(safe["error"].get("next_action", ""))
    return envelope


def advertiser_profile_input_schema() -> dict[str, Any]:
    return {
        "schema_version": INPUT_SCHEMA_VERSION,
        "type": "object",
        "additionalProperties": False,
        "required": ["start", "end"],
        "properties": {
            "start": {"type": "string", "format": "date"},
            "end": {"type": "string", "format": "date"},
        },
    }


def _safe_result(value: Mapping[str, Any]) -> dict[str, Any]:
    _validate_batch_result(value)
    if value.get("ok") is not True:
        return _safe_failure(value)
    native, status = _native_success(value)
    data = _safe_data(native.get("data"))
    if status in {"success", "empty"} and (status == "empty") != (not data["list"]):
        raise ContractChangedError(
            "advertiser profile status no longer matches its rows"
        )
    page = _safe_page(native.get("page"), len(data["list"]))
    continuation = _safe_continuation(
        native.get("next_page_input"), native["truncated"]
    )
    safe_native = _safe_native(native, data, page, continuation)
    if status == "contract_changed_additive":
        return _incomplete_result(
            "contract_changed",
            ErrorCode.CONTRACT_CHANGED,
            "Advertiser profile observed an additive upstream contract change.",
        )
    if native.get("truncated") is True:
        return _incomplete_result(
            "partial",
            ErrorCode.PAGINATION_LIMIT,
            "Advertiser profile stopped at its complete-read safety bound.",
            data=safe_native,
        )
    return {
        "operation_id": OPERATION_ID,
        "request_id": "advertisers",
        "ok": True,
        "status": str(status),
        "data": safe_native,
        "error": None,
    }


def _validate_batch_result(value: Mapping[str, Any]) -> None:
    if value.get("operation_id") != OPERATION_ID:
        raise ContractChangedError("advertiser profile operation identity changed")
    if set(value) - _BATCH_FIELDS:
        raise ContractChangedError("advertiser profile batch result fields changed")


def _native_success(value: Mapping[str, Any]) -> tuple[Mapping[str, Any], str]:
    native = value.get("data")
    if not isinstance(native, Mapping):
        raise ContractChangedError("advertiser profile result envelope changed")
    status = native.get("status")
    if native.get("schema_version") != "gravity-insight.read.v1":
        raise ContractChangedError("advertiser profile result contract changed")
    if status not in _SUCCESS or value.get("status") != status:
        raise ContractChangedError("advertiser profile result contract changed")
    if native.get("operation_id") != OPERATION_ID or native.get("error") not in (None, {}):
        raise ContractChangedError("advertiser profile result contract changed")
    if set(native) - _NATIVE_FIELDS or not isinstance(native.get("truncated"), bool):
        raise ContractChangedError("advertiser profile result contract changed")
    return native, str(status)


def _safe_native(
    native: Mapping[str, Any],
    data: Mapping[str, Any],
    page: Mapping[str, Any],
    continuation: Mapping[str, int] | None,
) -> dict[str, Any]:
    result = {
        key: copy.deepcopy(native[key])
        for key in (
            "schema_version", "operation_id", "status", "data", "page", "truncated",
        )
        if key in native
    }
    result.update(
        data=dict(data), page=dict(page), next_page_input=continuation
    )
    return result


def _safe_data(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or "list" not in value or set(value) - _DATA_FIELDS:
        raise ContractChangedError("advertiser profile data contract changed")
    result = {"list": _safe_rows(value["list"], _ROW_FIELDS, "data.list")}
    if "total" in value:
        result["total"] = _safe_rows(value["total"], _TOTAL_FIELDS, "data.total")
    if "page_info" in value:
        result["page_info"] = _safe_page_info(value["page_info"])
    if "update_at" in value:
        update_at = value["update_at"]
        if update_at is not None and (
            not isinstance(update_at, str) or len(update_at) > 128
        ):
            raise ContractChangedError("advertiser profile update_at changed")
        result["update_at"] = update_at
    return result


def _safe_page_info(value: Any) -> dict[str, int]:
    if (
        not isinstance(value, Mapping)
        or set(value) - _PAGE_INFO_FIELDS
        or any(type(item) is not int or item < 0 for item in value.values())
    ):
        raise ContractChangedError("advertiser profile page_info changed")
    return copy.deepcopy(dict(value))


def _safe_rows(
    value: Any, fields: frozenset[str], label: str
) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ContractChangedError(f"advertiser profile {label} changed")
    rows: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping) or set(item) - fields or any(
            not _row_value(field, field_value)
            for field, field_value in item.items()
        ):
            raise ContractChangedError(f"advertiser profile {label} changed")
        rows.append(copy.deepcopy(dict(item)))
    return rows


def _safe_page(value: Any, rows: int) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) - _PAGE_FIELDS:
        raise ContractChangedError("advertiser profile page receipt changed")
    item_count = value.get("item_count")
    required = ("number", "size", "pages_fetched", "max_workers")
    optional = ("total_pages", "total_items")
    if (
        type(item_count) is not int
        or item_count != rows
        or any(type(value.get(field)) is not int or value[field] < 1 for field in required)
        or any(
            value.get(field) is not None
            and (type(value[field]) is not int or value[field] < 0)
            for field in optional
        )
        or not isinstance(value.get("has_more"), bool)
        or value.get("fetch_strategy") not in _PAGE_STRATEGIES
    ):
        raise ContractChangedError("advertiser profile page receipt changed")
    return copy.deepcopy(dict(value))


def _safe_continuation(value: Any, truncated: bool) -> dict[str, int] | None:
    if not truncated:
        if value is not None:
            raise ContractChangedError("advertiser profile continuation changed")
        return None
    if (
        not isinstance(value, Mapping)
        or set(value) != {"page", "page_size"}
        or any(type(item) is not int or item < 1 for item in value.values())
    ):
        raise ContractChangedError("advertiser profile continuation changed")
    return {"page": value["page"], "page_size": value["page_size"]}


def _scalar(value: Any) -> bool:
    if value is None or isinstance(value, (bool, str)):
        return not isinstance(value, str) or len(value) <= 8_192
    if type(value) is int:
        return value.bit_length() <= 256
    return isinstance(value, float) and math.isfinite(value)


def _row_value(field: str, value: Any) -> bool:
    if field != "project_list":
        return _scalar(value)
    return _bounded_json(value)


def _bounded_json(value: Any, *, depth: int = 0) -> bool:
    if depth > 6:
        return False
    if _scalar(value):
        return True
    if isinstance(value, (list, tuple)):
        return len(value) <= 10_000 and all(
            _bounded_json(item, depth=depth + 1) for item in value
        )
    if isinstance(value, Mapping):
        return len(value) <= 1_000 and all(
            isinstance(key, str)
            and len(key) <= 256
            and _bounded_json(item, depth=depth + 1)
            for key, item in value.items()
        )
    return False


def _incomplete_result(
    status: str,
    code: ErrorCode,
    message: str,
    *,
    data: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    detail = ErrorDetail.create(
        code,
        message,
        operation_id=OPERATION_ID,
        next_action=(
            "Increase max_pages or max_items within the documented limits and retry."
            if code == ErrorCode.PAGINATION_LIMIT
            else "Stop automation until the advertiser profile contract is re-verified."
        ),
    )
    return {
        "operation_id": OPERATION_ID,
        "request_id": "advertisers",
        "ok": False,
        "status": status,
        "data": dict(data) if data is not None else None,
        "error": detail.to_dict(),
    }


def _safe_failure(value: Mapping[str, Any]) -> dict[str, Any]:
    error = value.get("error")
    if (
        value.get("request_id") != "advertisers"
        or value.get("ok") is not False
        or not isinstance(value.get("status"), str)
        or not isinstance(error, Mapping)
    ):
        raise ContractChangedError("advertiser profile failure envelope changed")
    status = str(value["status"])
    raw_code = error.get("code")
    code = raw_code.strip().upper() if isinstance(raw_code, str) else ""
    expected = _FAILURE_CODES.get(status)
    if code not in _BUILTIN_CODES:
        raise ContractChangedError("advertiser profile failure error changed")
    if expected is not None and code not in expected:
        raise ContractChangedError("advertiser profile failure error changed")
    if expected is None and (status != "error" or code in _SPECIAL_FAILURE_CODES):
        raise ContractChangedError("advertiser profile failure error changed")
    detail = ErrorDetail.create(
        code,
        "Advertiser profile could not complete its governed read.",
        operation_id=OPERATION_ID,
        retry_after_ms=(
            error.get("retry_after_ms")
            if code == ErrorCode.RATE_LIMITED.value
            else None
        ),
    )
    if error.get("category") != detail.category:
        raise ContractChangedError("advertiser profile failure category changed")
    return {
        "operation_id": OPERATION_ID,
        "request_id": "advertisers",
        "ok": False,
        "status": status,
        "data": None,
        "error": detail.to_dict(),
    }


__all__ = [
    "INPUT_SCHEMA_VERSION",
    "OPERATION_ID",
    "SCHEMA_VERSION",
    "advertiser_profile",
    "advertiser_profile_input_schema",
]
