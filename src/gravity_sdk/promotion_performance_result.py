"""Fail-closed result contract for Promotion Performance v1.

The public Insight client already projects every upstream response.  This
module adds a second, product-specific boundary: it verifies platform and
operation identities, keeps only the declared native row fields, rebuilds
pagination receipts, and replaces all error text with controlled wording.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from .component_aggregate import (
    aggregate_exit_code,
    aggregate_status,
    component_exit_code,
)
from .composite_result import bounded_structural_drift_diagnostics
from .domains import PROMOTION_PRIMARY_OPERATIONS
from .errors import ErrorCategory, ErrorCode, ErrorDetail, exit_code_for_error
from .promotion_performance_error import (
    error_exit_code as _error_exit_code,
    failure_matches as _failure_matches,
    safe_performance_error as _safe_error,
)
from .promotion_performance_binding import performance_request_mismatch_path
from .promotion_performance_rows import safe_promotion_rows
from .promotion_projection import (
    promotion_opaque_json_fields,
    promotion_row_fields,
)
from .result_audit import aggregate_result_audit
from .result_source import GOVERNED_PRODUCT, result_source


SCHEMA_VERSION = "gravity-insight.promotion-performance.v1"
SUPPORTED_PLATFORMS = (
    "alipay",
    "apple",
    "baidu",
    "bilibili",
    "bytedance",
    "honor",
    "huawei",
    "huawei_store",
    "huya",
    "iqiyi",
    "kuaishou",
    "oppo",
    "qihu360",
    "sigmob",
    "tencent",
    "ubix",
    "uc",
    "vivo",
    "weibo",
    "xiaomi",
    "youdao",
)


def _platform_operations() -> MappingProxyType[str, str]:
    missing = set(SUPPORTED_PLATFORMS) - set(PROMOTION_PRIMARY_OPERATIONS)
    if missing:
        raise RuntimeError(
            "Promotion Performance stable operations are missing: "
            + ", ".join(sorted(missing))
        )
    return MappingProxyType(
        {
            platform: PROMOTION_PRIMARY_OPERATIONS[platform]
            for platform in SUPPORTED_PLATFORMS
        }
    )


PROMOTION_PLATFORM_OPERATIONS = _platform_operations()
PROMOTION_PLATFORM_RESOURCES = MappingProxyType(
    {
        platform: operation_id.rsplit(".", 2)[-2]
        for platform, operation_id in PROMOTION_PLATFORM_OPERATIONS.items()
    }
)

@dataclass(frozen=True)
class PromotionComponentBinding:
    platform: str
    resource: str
    operation_id: str
    row_fields: frozenset[str]
    opaque_json_fields: frozenset[str]

PROMOTION_ROW_FIELDS = promotion_row_fields(SUPPORTED_PLATFORMS)
PROMOTION_OPAQUE_JSON_FIELDS = promotion_opaque_json_fields(SUPPORTED_PLATFORMS)
# Identity, time, hierarchy and status fields are useful native output columns,
# but they are not physical performance metrics.  Requiring metric inputs to
# stay outside this set prevents static projection fields from bypassing the
# live ``promotion.metric.list`` proof in FieldPolicy.
PROMOTION_NON_METRIC_FIELDS = frozenset(
    field
    for fields in PROMOTION_ROW_FIELDS.values()
    for field in fields
) - {"stat_cost", "cost"}

_SUCCESS_STATUSES = frozenset({"success", "empty"})
_FAILURE_STATUSES = frozenset(
    {
        "contract_changed",
        "error",
        "semantic_error",
        "unavailable",
        "parent_required",
        "permission_unavailable",
    }
)


def promotion_performance_item_count(value: Any) -> int:
    """Count only verified native rows in a product envelope."""

    if not isinstance(value, Mapping):
        return 0
    results = value.get("results")
    if not isinstance(results, list):
        return 0
    return sum(promotion_component_item_count(item) for item in results)


def promotion_component_item_count(value: Any) -> int:
    if not isinstance(value, Mapping) or value.get("ok") is not True:
        return 0
    data = value.get("data")
    rows = data.get("list") if isinstance(data, Mapping) else None
    return len(rows) if isinstance(rows, list) else 0


def safe_component(
    value: Any,
    platform: str,
    *,
    metrics: Sequence[str],
    expected_app_id: str,
    expected_window: tuple[str, str],
    max_pages: int,
) -> dict[str, Any]:
    """Project one batch result against its request-bound identity."""

    return safe_bound_component(
        value,
        _primary_binding(platform),
        metrics=metrics,
        expected_app_id=expected_app_id,
        expected_window=expected_window,
        max_pages=max_pages,
    )


def safe_bound_component(
    value: Any,
    binding: PromotionComponentBinding,
    *,
    metrics: Sequence[str],
    expected_app_id: str,
    expected_window: tuple[str, str],
    max_pages: int,
) -> dict[str, Any]:
    """Project one result against an explicit stable operation binding."""

    if binding.operation_id == "unknown" or not isinstance(value, Mapping):
        return _contract_failure(binding, "component_shape", "$")
    if (
        value.get("operation_id") != binding.operation_id
        or value.get("request_id") != binding.platform
    ):
        return _contract_failure(
            binding, "component_identity", "$.operation_id_or_request_id"
        )
    status = value.get("status")
    if not isinstance(status, str):
        return _contract_failure(binding, "component_status_type", "$.status")
    if value.get("ok") is True and status in _SUCCESS_STATUSES:
        return _safe_success(
            value,
            binding,
            status,
            metrics=metrics,
            expected_app_id=expected_app_id,
            expected_window=expected_window,
            max_pages=max_pages,
        )
    if value.get("ok") is False and status in _FAILURE_STATUSES:
        error = _safe_error(value.get("error"), binding.platform)
        if error is None or not _failure_matches(status, error["code"]):
            return _contract_failure(binding, "component_error", "$.error")
        if error["code"] == ErrorCode.CONTRACT_CHANGED.value:
            return _contract_failure(
                binding, "component_contract_status", "$.status"
            )
        return {
            **_component_identity(binding),
            "ok": False,
            "status": status,
            "exit_code": _error_exit_code(error),
            "data": None,
            "page": None,
            "window_applied": True,
            "returned_items": 0,
            "error": error,
        }
    return _contract_failure(binding, "component_status", "$.status")


def _safe_success(
    value: Mapping[str, Any],
    binding: PromotionComponentBinding,
    status: str,
    *,
    metrics: Sequence[str],
    expected_app_id: str,
    expected_window: tuple[str, str],
    max_pages: int,
) -> dict[str, Any]:
    if value.get("error") not in (None, {}):
        return _contract_failure(binding, "success_error", "$.error")
    envelope = value.get("data")
    if not isinstance(envelope, Mapping):
        return _contract_failure(binding, "read_envelope_type", "$.data")
    if (
        envelope.get("schema_version") != "gravity-insight.read.v1"
        or envelope.get("operation_id") != binding.operation_id
        or envelope.get("status") != status
        or envelope.get("error") not in (None, {})
    ):
        return _contract_failure(binding, "read_envelope_identity", "$.data")
    rows, failure = _success_rows(
        envelope,
        binding=binding,
        status=status,
        metrics=metrics,
        expected_app_id=expected_app_id,
        expected_window=expected_window,
    )
    if failure is not None or rows is None:
        check, path = failure or ("row_projection", "$.data.data.list")
        return _contract_failure(binding, check, path)
    page = _safe_page(envelope.get("page"), len(rows), max_pages=max_pages)
    if page is None:
        return _contract_failure(binding, "page_receipt", "$.data.page")
    return {
        **_component_identity(binding),
        "ok": True,
        "status": status,
        "exit_code": 0,
        "data": {"list": rows},
        "page": page,
        "window_applied": True,
        "returned_items": len(rows),
        "error": None,
    }


def _success_rows(
    envelope: Mapping[str, Any],
    *,
    binding: PromotionComponentBinding,
    status: str,
    metrics: Sequence[str],
    expected_app_id: str,
    expected_window: tuple[str, str],
) -> tuple[list[dict[str, Any]] | None, tuple[str, str] | None]:
    data = envelope.get("data")
    if not isinstance(data, Mapping):
        return None, ("read_data_type", "$.data.data")
    if "list" not in data:
        return None, ("read_data_required", "$.data.data.list")
    if set(data) - {"list", "page_info", "total", "update_at"}:
        return None, ("read_data_registration", "$.data.data.<unregistered>")
    allowed_fields = binding.row_fields | frozenset(metrics)
    rows, row_failure = safe_promotion_rows(
        data.get("list"),
        allowed_fields=allowed_fields,
        opaque_fields=binding.opaque_json_fields,
    )
    if row_failure is not None or rows is None:
        return None, row_failure or ("row_projection", "$.data.data.list")
    mismatch_path = performance_request_mismatch_path(
        rows, expected_app_id, expected_window
    )
    if mismatch_path is not None:
        return None, ("request_binding", mismatch_path)
    if (status == "empty") != (not rows):
        return None, ("status_row_consistency", "$.status")
    return rows, None


def _primary_binding(platform: str) -> PromotionComponentBinding:
    operation_id = PROMOTION_PLATFORM_OPERATIONS.get(platform, "unknown")
    resource = PROMOTION_PLATFORM_RESOURCES.get(platform, "unknown")
    return PromotionComponentBinding(
        platform=platform,
        resource=resource,
        operation_id=operation_id,
        row_fields=PROMOTION_ROW_FIELDS.get(platform, frozenset()),
        opaque_json_fields=PROMOTION_OPAQUE_JSON_FIELDS.get(platform, frozenset()),
    )


def _component_identity(binding: PromotionComponentBinding) -> dict[str, str]:
    return {
        "platform": binding.platform,
        "resource": binding.resource,
        "operation_id": binding.operation_id,
    }


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
    return bool(
        all(type(item) is int for item in receipt)
        and item_count == rows
        and 1 <= pages_fetched <= max_pages
        and workers == 1
        and number == 1
        and size == 10
        and has_more is False
        and _valid_completion_totals(
            rows,
            pages_fetched=pages_fetched,
            total_pages=total_pages,
            total_items=total_items,
        )
    )


def _valid_completion_totals(
    rows: int,
    *,
    pages_fetched: int,
    total_pages: Any,
    total_items: Any,
) -> bool:
    if rows == 0:
        return bool(
            pages_fetched == 1
            and _optional_empty_page_total(total_pages)
            and _optional_exact_total(total_items, 0)
        )
    return bool(
        _optional_exact_total(total_pages, pages_fetched)
        and _optional_exact_total(total_items, rows)
    )


def _optional_empty_page_total(value: Any) -> bool:
    return value is None or (type(value) is int and value in {0, 1})


def _optional_exact_total(value: Any, expected: int) -> bool:
    return value is None or (type(value) is int and value == expected)


def contract_component(
    platform: str, *, failure: tuple[str, str] | None = None
) -> dict[str, Any]:
    return _bound_contract_component(_primary_binding(platform), failure=failure)


def _bound_contract_component(
    binding: PromotionComponentBinding, *, failure: tuple[str, str] | None = None
) -> dict[str, Any]:
    detail = ErrorDetail.create(
        ErrorCode.CONTRACT_CHANGED,
        f"Promotion performance result contract changed for {binding.platform}.",
        operation_id=(
            None if binding.operation_id == "unknown" else binding.operation_id
        ),
        next_action=(
            "Stop this promotion performance automation until the stable "
            "platform result contract is re-verified."
        ),
    )
    result = {
        **_component_identity(binding),
        "ok": False,
        "status": "contract_changed",
        "exit_code": exit_code_for_error(detail),
        "data": None,
        "page": None,
        "window_applied": False,
        "returned_items": 0,
        "error": detail.to_dict(),
    }
    if failure is not None:
        result["drift_diagnostics"] = bounded_structural_drift_diagnostics(
            binding.operation_id, [failure]
        )
    return result


def _contract_failure(
    binding: PromotionComponentBinding, check: str, path: str
) -> dict[str, Any]:
    return _bound_contract_component(binding, failure=(check, path))


def contract_result() -> dict[str, Any]:
    detail = ErrorDetail.create(
        ErrorCode.CONTRACT_CHANGED,
        "Promotion performance result contract changed.",
        next_action=(
            "Stop this Plan until the promotion performance contract is re-verified."
        ),
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "result_source": result_source(GOVERNED_PRODUCT),
        "ok": False,
        "status": "contract_changed",
        "exit_code": exit_code_for_error(detail),
        "error": detail.to_dict(),
        "next_action": detail.next_action,
    }


def product_envelope(
    results: list[dict[str, Any]],
    *,
    app_id: str,
    window: tuple[str, str],
    platforms: tuple[str, ...],
    metric_count: int,
    max_pages: int,
    max_items: int,
    max_workers: int,
    returned_items: int,
) -> dict[str, Any]:
    """Build the controlled top-level product receipt."""

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
        "error": _primary_error(failures),
        "app_id": app_id,
        "date_range": {
            "start": window[0],
            "end": window[1],
            "inclusive": True,
        },
        "platform_count": len(platforms),
        "metric_count": metric_count,
        "total_count": len(results),
        "success_count": success_count,
        "failure_count": len(failures),
        "returned_items": returned_items,
        "limits": {
            "max_pages_per_platform": max_pages,
            "max_items_shared": max_items,
            "max_items_per_platform": max_items // len(platforms),
            "platform_workers": min(max_workers, len(platforms)),
            "page_workers_per_platform": 1,
        },
        "results": results,
        "next_action": (
            "Consume native platform rows in declaration order."
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


__all__ = [
    "PROMOTION_OPAQUE_JSON_FIELDS",
    "PROMOTION_PLATFORM_OPERATIONS",
    "PROMOTION_PLATFORM_RESOURCES",
    "PROMOTION_NON_METRIC_FIELDS",
    "PROMOTION_ROW_FIELDS",
    "SCHEMA_VERSION",
    "SUPPORTED_PLATFORMS",
    "PromotionComponentBinding",
    "contract_component",
    "contract_result",
    "product_envelope",
    "promotion_component_item_count",
    "promotion_performance_item_count",
    "safe_bound_component",
    "safe_component",
]
