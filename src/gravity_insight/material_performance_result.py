"""Fail-closed result contract for the material performance product."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from collections.abc import Sequence
import re
from typing import Any

from .component_aggregate import (
    aggregate_exit_code,
    aggregate_status,
    component_exit_code,
)
from .contracts.envelope_obligations import (
    CompletenessState,
    DataCompleteness,
    DiagnosticEvidence,
    DiagnosticState,
    EnvelopeObligations,
    ExecutionState,
    ExecutionStatus,
    MutationCertainty,
    MutationState,
    SemanticState,
    SemanticValidity,
    diagnostic_evidence,
    serialize_envelope,
)
from .composite_result import bounded_structural_drift_diagnostics
from .errors import (
    ErrorCategory,
    ErrorCode,
    ErrorDetail,
    exit_code_for_error,
)
from .material_performance_projection import (
    MATERIAL_IDENTITY_FIELDS,
    MATERIAL_REPORT_OPERATION,
    MATERIAL_ROW_FIELDS,
    coerce_profile as _coerce_profile,
    material_component_item_count,
    material_performance_item_count,
    project_success_data,
    safe_rows as _safe_rows,
)
from .result_audit import (
    aggregate_result_audit,
    project_result_audit,
    result_response_drift,
)
from .result_source import GOVERNED_PRODUCT, result_source


SCHEMA_VERSION = "gravity-insight.material-performance.v1"
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


def safe_component(
    value: Any,
    platform: Any,
    *,
    max_pages: int,
) -> dict[str, Any]:
    profile = _coerce_profile(platform)
    platform = str(getattr(profile, "platform", platform))
    if profile is None:
        return _contract_failure(platform, "query_profile", "$.query")
    query = profile.receipt()
    if not isinstance(value, Mapping):
        return _contract_failure(platform, "component_shape", "$", query=query)
    if (
        value.get("operation_id") != MATERIAL_REPORT_OPERATION
        or value.get("request_id") != platform
    ):
        return _contract_failure(
            platform, "component_identity", "$.operation_id_or_request_id", query=query
        )
    status = value.get("status")
    if not isinstance(status, str):
        return _contract_failure(platform, "component_status_type", "$.status", query=query)
    if value.get("ok") is True and status in _SUCCESS_STATUSES:
        return _safe_success(
            value, profile, status, max_pages=max_pages
        )
    if value.get("ok") is False and status in _FAILURE_STATUSES:
        error = _safe_error(value.get("error"), platform)
        if error is None:
            return _contract_failure(platform, "component_error_shape", "$.error", query=query)
        if not _failure_matches(status, error["code"]):
            return _contract_failure(
                platform, "component_error_status", "$.status_or_error.code", query=query
            )
        if error["code"] == ErrorCode.CONTRACT_CHANGED.value:
            inner = value.get("data")
            if result_response_drift(value) is not None or result_response_drift(
                inner
            ) is not None:
                return project_result_audit(contract_component(platform, query=query), value)
            return project_result_audit(
                _contract_failure(
                    platform, "component_contract_status", "$.status", query=query
                ),
                value,
            )
        payload = {
            "platform": platform,
            "query": query,
            "operation_id": MATERIAL_REPORT_OPERATION,
            "ok": False,
            "status": status,
            "data": None,
            "page": None,
            "error": error,
        }
        return serialize_envelope(
            payload, _component_obligations(False, status, 0, error)
        )
    return _contract_failure(platform, "component_status", "$.ok_or_status", query=query)


def _safe_success(
    value: Mapping[str, Any],
    profile: Any,
    status: str,
    *,
    max_pages: int,
) -> dict[str, Any]:
    platform = str(profile.platform)
    query = profile.receipt()
    if value.get("error") not in (None, {}):
        return _contract_failure(platform, "success_error", "$.error", query=query)
    envelope = value.get("data")
    if not isinstance(envelope, Mapping):
        return _contract_failure(platform, "read_envelope_type", "$.data", query=query)
    if (
        envelope.get("schema_version") != "gravity-insight.read.v1"
        or envelope.get("operation_id") != MATERIAL_REPORT_OPERATION
        or envelope.get("status") != status
        or envelope.get("error") not in (None, {})
    ):
        return _contract_failure(platform, "read_envelope_identity", "$.data", query=query)
    data = envelope.get("data")
    if not isinstance(data, Mapping) or set(data) - {
        "list", "page_info", "total", "update_at"
    }:
        return _contract_failure(platform, "read_data_shape", "$.data.data", query=query)
    safe_data, failure = project_success_data(data, profile)
    if failure is not None or safe_data is None:
        check, path = failure or ("data_projection", "$.data.data")
        return _contract_failure(platform, check, path, query=query)
    rows = safe_data["list"]
    if (status == "empty") != (not rows):
        return _contract_failure(platform, "row_status", "$.data.status", query=query)
    page = _safe_page(envelope.get("page"), len(rows), max_pages=max_pages)
    if page is None:
        return _contract_failure(platform, "page_receipt", "$.data.page", query=query)
    payload = {
        "platform": platform,
        "query": query,
        "operation_id": MATERIAL_REPORT_OPERATION,
        "ok": True,
        "status": status,
        "data": safe_data,
        "page": page,
        "error": None,
    }
    return serialize_envelope(
        payload, _component_obligations(True, status, len(rows), None)
    )


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


def contract_component(
    platform: str, *, query: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    detail = ErrorDetail.create(
        ErrorCode.CONTRACT_CHANGED,
        f"Material performance result contract changed for {platform}.",
        operation_id=MATERIAL_REPORT_OPERATION,
        next_action=(
            "Stop this material performance automation until the stable result "
            "contract is re-verified."
        ),
    )
    payload = {
        "platform": platform,
        "query": copy.deepcopy(dict(query)) if query is not None else None,
        "operation_id": MATERIAL_REPORT_OPERATION,
        "ok": False,
        "status": "contract_changed",
        "data": None,
        "page": None,
        "error": detail.to_dict(),
    }
    return serialize_envelope(
        payload,
        _component_obligations(
            False, "contract_changed", 0, detail.to_dict()
        ),
    )


def _contract_failure(
    platform: str,
    check: str,
    path: str,
    *,
    query: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    result = contract_component(platform, query=query)
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
    profiles: Sequence[Any] | None = None,
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
        "queries": [
            copy.deepcopy(item.receipt()) for item in profiles
        ] if profiles is not None else [
            copy.deepcopy(item.get("query")) for item in results
        ],
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
    if code == ErrorCode.PAGINATION_LIMIT.value:
        return (
            "The page or item budget ended before the material report did; this is not a "
            "wrong App, date, or platform. Keep them unchanged and rerun with a larger "
            "--max-pages (up to 1000) or --max-items (up to 100000)."
        )
    if category == ErrorCategory.CALLER.value:
        return "Correct the selected App, dates, or platform and retry."
    return "Retry only the failed platform; do not replay successful siblings."


def _failure_matches(status: str, code: str) -> bool:
    expected = _FAILURE_CODES.get(status)
    if expected is not None:
        return code in expected
    return code not in _SPECIAL_FAILURE_CODES


def _component_obligations(
    ok: bool,
    status: str,
    rows: int,
    error: Mapping[str, Any] | None,
) -> EnvelopeObligations:
    execution = ExecutionStatus(
        ExecutionState.COMPLETE if ok else ExecutionState.FAILED,
        "MATERIAL_COMPONENT_READ_COMPLETE" if ok else "MATERIAL_COMPONENT_READ_FAILED",
    )
    completeness = DataCompleteness(
        CompletenessState.COMPLETE if ok else CompletenessState.UNKNOWN,
        "MATERIAL_PAGINATION_COMPLETE" if ok else "MATERIAL_COMPLETENESS_UNKNOWN",
        {"returned_rows": rows},
    )
    semantics = SemanticValidity(
        SemanticState.VALID if ok else SemanticState.INVALID,
        (
            "MATERIAL_QUERY_PROFILE_VALIDATED"
            if ok
            else "MATERIAL_COMPONENT_REJECTED"
        ,),
    )
    diagnostics = (
        DiagnosticEvidence(DiagnosticState.NONE)
        if error is None
        else diagnostic_evidence(error)
    )
    return EnvelopeObligations(
        execution,
        completeness,
        semantics,
        diagnostics,
        MutationCertainty(MutationState.NOT_APPLICABLE, "READ_ONLY_MATERIAL_REPORT"),
    )


__all__ = [
    "MATERIAL_REPORT_OPERATION",
    "MATERIAL_IDENTITY_FIELDS",
    "MATERIAL_ROW_FIELDS",
    "SCHEMA_VERSION",
    "contract_component",
    "contract_result",
    "material_component_item_count",
    "material_performance_item_count",
    "product_envelope",
    "safe_component",
]
