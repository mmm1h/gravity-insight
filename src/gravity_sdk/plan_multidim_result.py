"""Fail-closed Multidim result projection and Plan row accounting."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from .errors import ContractChangedError
from .multidim_service import (
    CUSTOM_METRIC_OPERATIONS,
    MULTIDIM_QUERY_OPERATION,
    MULTIDIM_TOTAL_OPERATION,
    STANDARD_METRIC_OPERATION,
)
from .multidim_product import MULTIDIM_INPUT_SCHEMA_VERSION
from .plan import AdapterContext


RESULT_SCHEMA_VERSION = "gravity-insight.composite.multidim.v1"
_SUCCESS = frozenset({"success", "empty"})
_TOP_STATUSES = frozenset({"success", "empty", "partial", "error", "contract_changed"})
_COMPONENT_STATUSES = frozenset(
    {
        "success", "empty", "partial", "error", "contract_changed",
        "semantic_error", "parent_required", "permission_unavailable", "unavailable",
    }
)
_STRUCTURAL = frozenset(
    {
        "schema_version", "ok", "status", "exit_code", "app_id",
        "network_called", "query_executed", "operation_id",
        "input_schema_version", "next_action",
    }
)
_KNOWN_CODES = frozenset(
    {
        "AUTH_MISSING", "AUTH_REJECTED", "INPUT_INVALID", "RATE_LIMITED",
        "UPSTREAM_UNAVAILABLE", "CONTRACT_CHANGED", "PERMISSION_UNAVAILABLE",
        "PAGINATION_LIMIT",
    }
)
_METADATA_OPERATIONS = frozenset(
    {STANDARD_METRIC_OPERATION, *CUSTOM_METRIC_OPERATIONS}
)


def is_multidim_result(value: Any) -> bool:
    return (
        isinstance(value, Mapping)
        and value.get("schema_version") == RESULT_SCHEMA_VERSION
        and "query" in value
        and "validation" in value
    )


def project_multidim_result(
    result: Any,
    fields: tuple[str, ...],
    _context: AdapterContext,
) -> dict[str, Any]:
    if not isinstance(result, Mapping):
        raise ContractChangedError("multidim result is invalid")
    app_id = result.get("app_id")
    if not isinstance(app_id, str):
        raise ContractChangedError("multidim result omitted its App identity")
    return sanitize_multidim_result(result, app_id, fields=fields)


def multidim_result_item_count(value: Any) -> int:
    """Use the greater of page metadata and the actual primary row container."""

    if not isinstance(value, Mapping):
        return 0
    query = value.get("query")
    if not isinstance(query, Mapping):
        return 0
    counts = [_page_count(query.get("page")), _row_count(query.get("data"))]
    return max(counts)


def sanitize_multidim_result(
    result: Mapping[str, Any],
    expected_app_id: str,
    *,
    fields: tuple[str, ...] = (),
) -> dict[str, Any]:
    _validate_result(result, expected_app_id)
    selected = {
        key: copy.deepcopy(result[key])
        for key in _STRUCTURAL
        if key in result
    }
    failed = result["ok"] is False
    if failed:
        selected["error"] = _safe_error(result.get("error"))
    selected["query"] = _safe_component(
        result.get("query"), MULTIDIM_QUERY_OPERATION, failed=failed
    )
    selected["total"] = _safe_component(
        result.get("total"), MULTIDIM_TOTAL_OPERATION, failed=failed
    )
    selected["validation"] = _safe_validation(result.get("validation"))
    selected["operation_id"] = MULTIDIM_QUERY_OPERATION
    selected["next_action"] = (
        selected["error"]["next_action"]
        if failed and isinstance(selected.get("error"), Mapping)
        else "Consume query and total only from this bounded Multidim envelope."
    )
    if not fields:
        return selected
    return {
        key: value
        for key, value in selected.items()
        if key in _STRUCTURAL or key in fields
    }


def _validate_result(result: Mapping[str, Any], expected_app_id: str) -> None:
    _validate_identity(result, expected_app_id)
    _validate_outcome(result)
    if not isinstance(result.get("validation"), Mapping):
        raise ContractChangedError("multidim validation result is invalid")
    _validate_component(result.get("query"), MULTIDIM_QUERY_OPERATION, required=True)
    _validate_component(result.get("total"), MULTIDIM_TOTAL_OPERATION, required=False)


def _validate_identity(result: Mapping[str, Any], expected_app_id: str) -> None:
    if result.get("schema_version") != RESULT_SCHEMA_VERSION:
        raise ContractChangedError("multidim result has the wrong schema")
    if result.get("app_id") != expected_app_id:
        raise ContractChangedError("multidim result App identity changed")
    if result.get("network_called") is not True:
        raise ContractChangedError("multidim network invariant changed")
    if result.get("query_executed") is not True:
        raise ContractChangedError("multidim execution invariant changed")
    if result.get("operation_id") not in {None, MULTIDIM_QUERY_OPERATION}:
        raise ContractChangedError("multidim operation identity changed")
    if result.get("input_schema_version") not in {
        None, MULTIDIM_INPUT_SCHEMA_VERSION,
    }:
        raise ContractChangedError("multidim input schema identity changed")


def _validate_outcome(result: Mapping[str, Any]) -> None:
    ok, status, exit_code = result.get("ok"), result.get("status"), result.get("exit_code")
    if not isinstance(ok, bool):
        raise ContractChangedError("multidim result has an invalid success marker")
    if not isinstance(status, str) or status not in _TOP_STATUSES:
        raise ContractChangedError("multidim result has an invalid status")
    if type(exit_code) is not int or not 0 <= exit_code <= 4:
        raise ContractChangedError("multidim result has an invalid exit code")
    if ok and (status not in _SUCCESS or exit_code != 0):
        raise ContractChangedError("multidim success outcome is inconsistent")
    if not ok and status in _SUCCESS:
        raise ContractChangedError("multidim failure returned a success status")
    if not ok and not isinstance(result.get("error"), Mapping):
        raise ContractChangedError("multidim failure omitted its safe error")


def _validate_component(value: Any, operation_id: str, *, required: bool) -> None:
    if value is None and not required:
        return
    if not isinstance(value, Mapping):
        raise ContractChangedError("multidim component is invalid")
    status = value.get("status")
    if not isinstance(status, str) or status not in _COMPONENT_STATUSES:
        raise ContractChangedError("multidim component status is invalid")
    if value.get("operation_id") not in {None, operation_id}:
        raise ContractChangedError("multidim component operation changed")
    if status in _SUCCESS:
        _validate_success_component(value, operation_id)
    elif value.get("ok") is True or not isinstance(value.get("error"), Mapping):
        raise ContractChangedError("multidim component failure is inconsistent")


def _validate_success_component(value: Mapping[str, Any], operation_id: str) -> None:
    if value.get("operation_id") != operation_id or value.get("ok") is False:
        raise ContractChangedError("multidim component success identity changed")
    data = value.get("data")
    if not isinstance(data, Mapping):
        raise ContractChangedError("multidim component data contract changed")
    if not any(isinstance(data.get(key), list) for key in ("list", "items")):
        raise ContractChangedError("multidim component rows contract changed")


def _safe_component(
    value: Any, operation_id: str, *, failed: bool
) -> dict[str, Any] | None:
    if value is None:
        return None
    assert isinstance(value, Mapping)
    status = str(value.get("status", "error"))
    if failed and status not in _SUCCESS:
        return {
            "operation_id": operation_id,
            "ok": False,
            "status": status,
            "error": _safe_error(value.get("error")),
        }
    data = value["data"]
    rows_key = "list" if isinstance(data.get("list"), list) else "items"
    selected: dict[str, Any] = {
        "operation_id": operation_id,
        "ok": value.get("ok", True),
        "status": status,
        "data": {rows_key: copy.deepcopy(data[rows_key])},
    }
    page = _safe_page(value.get("page"))
    if page is not None:
        selected["page"] = page
    if isinstance(value.get("truncated"), bool):
        selected["truncated"] = value["truncated"]
    return selected


def _safe_page(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    integer_fields = {
        "number", "size", "item_count", "total_pages", "total_items",
        "pages_fetched", "max_workers",
    }
    selected = {
        key: item
        for key, item in value.items()
        if key in integer_fields and (item is None or type(item) is int and item >= 0)
    }
    if isinstance(value.get("has_more"), bool):
        selected["has_more"] = value["has_more"]
    if value.get("fetch_strategy") in {"single", "serial", "parallel"}:
        selected["fetch_strategy"] = value["fetch_strategy"]
    return selected


def _safe_validation(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    selected: dict[str, Any] = {}
    enums = {
        "status": {"not_required", "validated", "validated_exclusions_only"},
        "metrics": {"not_requested", "validated_live"},
        "data_dims": {
            "not_requested", "not_validated_without_selected_metrics", "exclusion_checked"
        },
    }
    for key, allowed in enums.items():
        if value.get(key) in allowed:
            selected[key] = value[key]
    for key in ("metrics_checked", "data_dims_checked"):
        item = value.get(key)
        if type(item) is int and item >= 0:
            selected[key] = item
    operations = value.get("metadata_operations")
    if isinstance(operations, list) and all(item in _METADATA_OPERATIONS for item in operations):
        selected["metadata_operations"] = list(dict.fromkeys(operations))
    return selected


def _safe_error(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    code = value.get("code")
    selected_code = code if code in _KNOWN_CODES else "UPSTREAM_UNAVAILABLE"
    category = value.get("category")
    selected_category = category if category in {"caller", "upstream", "local"} else "upstream"
    retry_after = value.get("retry_after_ms")
    if type(retry_after) is not int or retry_after < 0:
        retry_after = None
    action = _safe_action(selected_code, selected_category)
    return {
        "code": selected_code,
        "category": selected_category,
        "retryable": value.get("retryable") if isinstance(value.get("retryable"), bool) else False,
        "retry_after_ms": retry_after,
        "next_action": action,
        "stage": value.get("stage") if value.get("stage") in {"query", "total"} else None,
    }


def _safe_action(code: str, category: str) -> str:
    if code.startswith("AUTH_"):
        return "Run `gravity auth status`, then retry the same Multidim request."
    if category == "caller":
        return "Correct the explicit Multidim request, then retry."
    return "Retry the same Multidim request after checking Gravity availability."


def _page_count(value: Any) -> int:
    if not isinstance(value, Mapping):
        return 0
    count = value.get("item_count")
    return count if type(count) is int and count >= 0 else 0


def _row_count(value: Any) -> int:
    if not isinstance(value, Mapping):
        return 0
    return max(
        (len(value[key]) for key in ("list", "items") if isinstance(value.get(key), list)),
        default=0,
    )


__all__ = [
    "is_multidim_result",
    "multidim_result_item_count",
    "project_multidim_result",
    "sanitize_multidim_result",
]
