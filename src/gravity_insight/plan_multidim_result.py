"""Fail-closed Multidim result projection and Plan row accounting."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from .errors import ContractChangedError, ErrorCode
from .multidim_service import (
    CUSTOM_METRIC_OPERATIONS,
    MULTIDIM_QUERY_OPERATION,
    MULTIDIM_TOTAL_OPERATION,
    STANDARD_METRIC_OPERATION,
)
from .multidim_product import MULTIDIM_INPUT_SCHEMA_VERSION
from .plan import AdapterContext
from .result_audit import project_result_audit


RESULT_SCHEMA_VERSION = "gravity-insight.composite.multidim.v1"
_SUCCESS = frozenset({"success", "empty"})
_TOP_STATUSES = frozenset({"success", "empty", "partial", "error", "contract_changed"})
_COMPONENT_STATUSES = frozenset(
    {
        "success", "empty", "partial", "error", "contract_changed",
        "semantic_error", "parent_required", "permission_unavailable", "unavailable",
        "contract_changed_additive",
    }
)
_STRUCTURAL = frozenset(
    {
        "schema_version", "ok", "status", "exit_code", "app_id",
        "network_called", "query_executed", "operation_id",
        "input_schema_version", "next_action",
    }
)
_KNOWN_CODES = frozenset(item.value for item in ErrorCode)
_METADATA_OPERATIONS = frozenset(
    {STANDARD_METRIC_OPERATION, *CUSTOM_METRIC_OPERATIONS}
)
_VALIDATION_ENUMS = {
    "status": frozenset({"not_required", "validated", "validated_exclusions_only"}),
    "metrics": frozenset({"not_requested", "validated_live"}),
    "data_dims": frozenset(
        {"not_requested", "not_validated_without_selected_metrics", "exclusion_checked"}
    ),
}
_VALIDATION_FIELDS = frozenset(
    {*_VALIDATION_ENUMS, "metrics_checked", "data_dims_checked", "metadata_operations"}
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
        return project_result_audit(selected, result)
    return {
        key: value
        for key, value in selected.items()
        if key in _STRUCTURAL or key in fields
    }


def _validate_result(result: Mapping[str, Any], expected_app_id: str) -> None:
    _validate_identity(result, expected_app_id)
    _validate_outcome(result)
    _validate_validation(result.get("validation"))
    _validate_component(result.get("query"), MULTIDIM_QUERY_OPERATION, required=True)
    _validate_component(result.get("total"), MULTIDIM_TOTAL_OPERATION, required=False)
    _validate_success_components(result)


def _validate_identity(result: Mapping[str, Any], expected_app_id: str) -> None:
    if result.get("schema_version") != RESULT_SCHEMA_VERSION:
        raise ContractChangedError("multidim result has the wrong schema")
    if result.get("app_id") != expected_app_id:
        raise ContractChangedError("multidim result App identity changed")
    if result.get("network_called") is not True:
        raise ContractChangedError("multidim network invariant changed")
    if result.get("query_executed") is not True:
        raise ContractChangedError("multidim execution invariant changed")
    operation_id = result.get("operation_id")
    if operation_id is not None and operation_id != MULTIDIM_QUERY_OPERATION:
        raise ContractChangedError("multidim operation identity changed")
    input_schema_version = result.get("input_schema_version")
    if input_schema_version is not None and input_schema_version != MULTIDIM_INPUT_SCHEMA_VERSION:
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
    component_operation = value.get("operation_id")
    if component_operation is not None and component_operation != operation_id:
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
    rows = next(
        (data[key] for key in ("list", "items") if isinstance(data.get(key), list)),
        None,
    )
    if rows is None or any(not isinstance(item, Mapping) for item in rows):
        raise ContractChangedError("multidim component rows contract changed")


def _validate_success_components(result: Mapping[str, Any]) -> None:
    if result.get("ok") is not True:
        return
    for field in ("query", "total"):
        component = result.get(field)
        if component is not None and component.get("status") not in _SUCCESS:
            raise ContractChangedError(
                "multidim success outcome contradicts a component failure"
            )


def _validate_validation(value: Any) -> None:
    if not isinstance(value, Mapping) or set(value) - _VALIDATION_FIELDS:
        raise ContractChangedError("multidim validation result is invalid")
    for key, allowed in _VALIDATION_ENUMS.items():
        item = value.get(key)
        if not isinstance(item, str) or item not in allowed:
            raise ContractChangedError("multidim validation status changed")
    for key in ("metrics_checked", "data_dims_checked"):
        if key in value and (type(value[key]) is not int or value[key] < 0):
            raise ContractChangedError("multidim validation count changed")
    operations = value.get("metadata_operations")
    if not isinstance(operations, list) or any(
        not isinstance(item, str) or item not in _METADATA_OPERATIONS
        for item in operations
    ):
        raise ContractChangedError("multidim validation operations changed")


def _safe_component(
    value: Any, operation_id: str, *, failed: bool
) -> dict[str, Any] | None:
    if value is None:
        return None
    assert isinstance(value, Mapping)
    status = value["status"]
    if failed and status not in _SUCCESS:
        selected = {
            "operation_id": operation_id,
            "ok": False,
            "status": status,
            "error": _safe_error(value.get("error")),
        }
        diagnostics = _safe_drift_diagnostics(value, operation_id)
        if diagnostics is not None:
            selected["drift_diagnostics"] = diagnostics
        return selected
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
    return project_result_audit(selected, value)


def _safe_drift_diagnostics(
    value: Mapping[str, Any], operation_id: str
) -> dict[str, Any] | None:
    diagnostics = value.get("drift_diagnostics")
    if not isinstance(diagnostics, Mapping):
        return None
    if diagnostics.get("schema_version") != "gravity-insight.drift-diagnostics.v1":
        return None
    warning_counts = _safe_drift_warning_counts(diagnostics.get("warning_counts"))
    if warning_counts is None:
        return None
    evidence = diagnostics.get("evidence")
    if not isinstance(evidence, Mapping) or evidence.get("operation_id") != operation_id:
        return None
    selected_evidence: dict[str, Any] = {
        "operation_id": operation_id,
        "required_evidence": "maintainer_live_probe",
    }
    fingerprint = _safe_contract_fingerprint(
        evidence.get("contract_schema_fingerprint")
    )
    if fingerprint is not None:
        selected_evidence["contract_schema_fingerprint"] = fingerprint
    return {
        "schema_version": "gravity-insight.drift-diagnostics.v1",
        "warning_counts": warning_counts,
        "evidence": selected_evidence,
    }


def _safe_drift_warning_counts(value: Any) -> list[dict[str, Any]] | None:
    if not isinstance(value, list) or len(value) > 8:
        return None
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in value:
        normalized = _safe_drift_warning_count(item, seen)
        if normalized is None:
            return None
        seen.add(normalized["class"])
        selected.append(normalized)
    return selected


def _safe_drift_warning_count(
    value: Any, seen: set[str]
) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    allowed_classes = {
        "unregistered_list_item_keys",
        "unregistered_response_data_item_keys",
    }
    warning_class, count = value.get("class"), value.get("count")
    if not isinstance(warning_class, str) or warning_class not in allowed_classes:
        return None
    if warning_class in seen or type(count) is not int or not 0 <= count <= 1_000_000:
        return None
    return {"class": warning_class, "count": count}


def _safe_contract_fingerprint(value: Any) -> str | None:
    if (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    ):
        return value
    return None


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
    strategy = value.get("fetch_strategy")
    if isinstance(strategy, str) and strategy in {
        "single_page",
        "serial_known_total",
        "parallel_known_total",
        "serial_unknown_total",
        "stopped_missing_total_page",
    }:
        selected["fetch_strategy"] = strategy
    return selected


def _safe_validation(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    selected: dict[str, Any] = {}
    for key in _VALIDATION_ENUMS:
        selected[key] = value[key]
    for key in ("metrics_checked", "data_dims_checked"):
        item = value.get(key)
        if type(item) is int and item >= 0:
            selected[key] = item
    operations = value.get("metadata_operations")
    selected["metadata_operations"] = list(dict.fromkeys(operations))
    return selected


def _safe_error(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    code = value.get("code")
    selected_code = code if isinstance(code, str) and code in _KNOWN_CODES else "UPSTREAM_UNAVAILABLE"
    category = value.get("category")
    selected_category = (
        category
        if isinstance(category, str) and category in {"caller", "upstream", "local"}
        else "upstream"
    )
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
        "stage": (
            value.get("stage")
            if isinstance(value.get("stage"), str)
            and value.get("stage") in {"query", "total"}
            else None
        ),
    }


def _safe_action(code: str, category: str) -> str:
    if code.startswith("AUTH_"):
        return "Run `gravity auth status`, then retry the same Multidim request."
    if code == "CONTRACT_CHANGED":
        return "Stop automation until the Multidim contract is re-verified."
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
