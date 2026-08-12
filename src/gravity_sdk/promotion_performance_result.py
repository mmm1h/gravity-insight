"""Fail-closed result contract for Promotion Performance v1.

The public Insight client already projects every upstream response.  This
module adds a second, product-specific boundary: it verifies platform and
operation identities, keeps only the declared native row fields, rebuilds
pagination receipts, and replaces all error text with controlled wording.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
import math
from types import MappingProxyType
from typing import Any

from .domains import PROMOTION_PRIMARY_OPERATIONS
from .errors import ErrorCategory, ErrorCode, ErrorDetail
from .promotion_performance_error import (
    error_exit_code as _error_exit_code,
    failure_matches as _failure_matches,
    safe_performance_error as _safe_error,
)
from .promotion_performance_binding import rows_match_performance_request


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

_COMMON_ROW_FIELDS = frozenset(
    {
        "id",
        "name",
        "status",
        "date",
        "day",
        "hour",
        "week",
        "month",
        "advertiser_id",
        "campaign_id",
        "campaign_name",
        "project_id",
        "project_name",
        "group_id",
        "group_name",
        "ad_group_id",
        "ad_group_name",
        "ad_unit_id",
        "ad_unit_name",
        "creative_id",
        "creative_name",
        "account_id",
        "account_name",
        "app_id",
        "app_name",
    }
)
PROMOTION_ROW_FIELDS = MappingProxyType(
    {
        platform: _COMMON_ROW_FIELDS
        | (
            frozenset(
                {
                    "advertiser_budget_mode",
                    "advertiser_system_status",
                    "stat_cost",
                }
            )
            if platform == "bytedance"
            else frozenset(
                {
                    "advertiser_budget_mode",
                    "advertiser_system_status",
                    "cost",
                }
            )
            if platform == "tencent"
            else frozenset()
        )
        for platform in SUPPORTED_PLATFORMS
    }
)
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

    operation_id = PROMOTION_PLATFORM_OPERATIONS.get(platform)
    if operation_id is None or not isinstance(value, Mapping):
        return contract_component(platform)
    if (
        value.get("operation_id") != operation_id
        or value.get("request_id") != platform
    ):
        return contract_component(platform)
    status = value.get("status")
    if not isinstance(status, str):
        return contract_component(platform)
    if value.get("ok") is True and status in _SUCCESS_STATUSES:
        return _safe_success(
            value,
            platform,
            status,
            metrics=metrics,
            expected_app_id=expected_app_id,
            expected_window=expected_window,
            max_pages=max_pages,
        )
    if value.get("ok") is False and status in _FAILURE_STATUSES:
        error = _safe_error(value.get("error"), platform)
        if error is None or not _failure_matches(status, error["code"]):
            return contract_component(platform)
        if error["code"] == ErrorCode.CONTRACT_CHANGED.value:
            return contract_component(platform)
        return {
            **_component_identity(platform),
            "ok": False,
            "status": status,
            "exit_code": _error_exit_code(error),
            "data": None,
            "page": None,
            "window_applied": True,
            "returned_items": 0,
            "error": error,
        }
    return contract_component(platform)


def _safe_success(
    value: Mapping[str, Any],
    platform: str,
    status: str,
    *,
    metrics: Sequence[str],
    expected_app_id: str,
    expected_window: tuple[str, str],
    max_pages: int,
) -> dict[str, Any]:
    operation_id = PROMOTION_PLATFORM_OPERATIONS[platform]
    if value.get("error") not in (None, {}):
        return contract_component(platform)
    envelope = value.get("data")
    if not isinstance(envelope, Mapping):
        return contract_component(platform)
    if (
        envelope.get("schema_version") != "gravity-insight.read.v1"
        or envelope.get("operation_id") != operation_id
        or envelope.get("status") != status
        or envelope.get("error") not in (None, {})
    ):
        return contract_component(platform)
    data = envelope.get("data")
    if (
        not isinstance(data, Mapping)
        or "list" not in data
        or set(data) - {"list", "page_info", "total", "update_at"}
    ):
        return contract_component(platform)
    allowed_fields = PROMOTION_ROW_FIELDS[platform] | frozenset(metrics)
    rows = _safe_rows(data.get("list"), allowed_fields=allowed_fields)
    if (
        rows is None
        or not rows_match_performance_request(
            rows, expected_app_id, expected_window
        )
        or (status == "empty") != (not rows)
    ):
        return contract_component(platform)
    page = _safe_page(envelope.get("page"), len(rows), max_pages=max_pages)
    if page is None:
        return contract_component(platform)
    return {
        **_component_identity(platform),
        "ok": True,
        "status": status,
        "exit_code": 0,
        "data": {"list": rows},
        "page": page,
        "window_applied": True,
        "returned_items": len(rows),
        "error": None,
    }


def _component_identity(platform: str) -> dict[str, str]:
    operation_id = PROMOTION_PLATFORM_OPERATIONS.get(platform)
    resource = PROMOTION_PLATFORM_RESOURCES.get(platform)
    return {
        "platform": platform,
        "resource": resource or "unknown",
        "operation_id": operation_id or "unknown",
    }


def _safe_rows(
    value: Any, *, allowed_fields: frozenset[str]
) -> list[dict[str, Any]] | None:
    if not isinstance(value, list):
        return None
    rows: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping) or set(item) - allowed_fields:
            return None
        row: dict[str, Any] = {}
        for key, field_value in item.items():
            if not isinstance(key, str) or not _json_scalar(field_value):
                return None
            row[key] = copy.deepcopy(field_value)
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


def contract_component(platform: str) -> dict[str, Any]:
    operation_id = PROMOTION_PLATFORM_OPERATIONS.get(platform)
    detail = ErrorDetail.create(
        ErrorCode.CONTRACT_CHANGED,
        f"Promotion performance result contract changed for {platform}.",
        operation_id=operation_id,
        next_action=(
            "Stop this promotion performance automation until the stable "
            "platform result contract is re-verified."
        ),
    )
    return {
        **_component_identity(platform),
        "ok": False,
        "status": "contract_changed",
        "exit_code": 3,
        "data": None,
        "page": None,
        "window_applied": False,
        "returned_items": 0,
        "error": detail.to_dict(),
    }


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
        "ok": False,
        "status": "contract_changed",
        "exit_code": 3,
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
    }


def _component_exit_code(value: Mapping[str, Any]) -> int:
    exit_code = value.get("exit_code")
    if type(exit_code) is int and exit_code in {2, 3, 4}:
        return exit_code
    error = value.get("error")
    return _error_exit_code(error if isinstance(error, Mapping) else {})


def _primary_error(failures: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not failures:
        return None
    selected = max(failures, key=_component_exit_code)
    error = selected.get("error")
    if not isinstance(error, Mapping):
        return contract_component(str(selected.get("platform", "unknown")))["error"]
    return copy.deepcopy(dict(error))


def _json_scalar(value: Any) -> bool:
    if value is None or isinstance(value, bool):
        return True
    if isinstance(value, str):
        return len(value) <= 8_192
    if type(value) is int:
        return value.bit_length() <= 256
    return isinstance(value, float) and math.isfinite(value)


__all__ = [
    "PROMOTION_PLATFORM_OPERATIONS",
    "PROMOTION_PLATFORM_RESOURCES",
    "PROMOTION_NON_METRIC_FIELDS",
    "PROMOTION_ROW_FIELDS",
    "SCHEMA_VERSION",
    "SUPPORTED_PLATFORMS",
    "contract_component",
    "contract_result",
    "product_envelope",
    "promotion_component_item_count",
    "promotion_performance_item_count",
    "safe_component",
]
