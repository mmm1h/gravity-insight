"""Plan re-verification and projection for Material Performance v1."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from .material_performance_result import (
    MATERIAL_REPORT_OPERATION,
    SCHEMA_VERSION,
    contract_component,
    contract_result,
    material_component_item_count,
    product_envelope,
    safe_component,
)


_PLATFORMS = frozenset({"bytedance", "tencent", "kuaishou", "bilibili"})
_PROJECT_STRUCTURAL = frozenset(
    {"schema_version", "ok", "status", "exit_code", "error", "next_action"}
)


def sanitize_product_result(
    value: Any,
    *,
    expected_platforms: tuple[str, ...] | None = None,
    expected_app_count: int | None = None,
    expected_window: tuple[str, str] | None = None,
    expected_max_pages: int | None = None,
    expected_max_items: int | None = None,
    expected_max_workers: int | None = None,
) -> dict[str, Any]:
    """Rebuild a product envelope from whitelisted fields and identities."""

    if not isinstance(value, Mapping):
        return contract_result()
    parts = _product_parts(value)
    if parts is None:
        return contract_result()
    platforms, window, app_count, limits, results = parts
    if not _matches_expected(
        platforms,
        window,
        app_count,
        limits,
        expected_platforms=expected_platforms,
        expected_app_count=expected_app_count,
        expected_window=expected_window,
        expected_max_pages=expected_max_pages,
        expected_max_items=expected_max_items,
        expected_max_workers=expected_max_workers,
    ):
        return contract_result()
    safe = [
        _resanitize_component(item, platform, max_pages=limits[0])
        for platform, item in zip(platforms, results, strict=True)
    ]
    returned = sum(material_component_item_count(item) for item in safe)
    if returned > limits[1]:
        return contract_result()
    rebuilt = product_envelope(
        safe,
        app_count=app_count,
        window=window,
        platforms=platforms,
        max_pages=limits[0],
        max_items=limits[1],
        max_workers=limits[2],
        returned_items=returned,
    )
    checked = (
        "ok", "status", "exit_code", "error", "platform_count", "total_count",
        "success_count", "failure_count", "returned_items",
    )
    actual = tuple(value.get(key) for key in checked)
    expected = tuple(rebuilt[key] for key in checked)
    exact = all(
        type(found) is type(wanted) and found == wanted
        for found, wanted in zip(actual, expected)
    )
    return rebuilt if exact else contract_result()


def is_material_performance_result(value: Any) -> bool:
    return isinstance(value, Mapping) and value.get("schema_version") == SCHEMA_VERSION


def project_material_performance_result(
    value: Any,
    fields: tuple[str, ...],
    _context: Any,
) -> dict[str, Any]:
    safe = sanitize_product_result(value)
    if not fields or safe.get("status") == "contract_changed":
        return safe
    allowed = _PROJECT_STRUCTURAL | set(fields)
    return {
        key: copy.deepcopy(item)
        for key, item in safe.items()
        if key in allowed
    }


def _resanitize_component(
    value: Any, platform: str, *, max_pages: int
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return contract_component(platform)
    if value.get("platform") != platform:
        return contract_component(platform)
    if value.get("status") == "contract_changed":
        return contract_component(platform)
    batch: dict[str, Any] = {
        "operation_id": value.get("operation_id"),
        "request_id": platform,
        "ok": value.get("ok"),
        "status": value.get("status"),
        "error": value.get("error"),
    }
    if value.get("ok") is True:
        batch["data"] = {
            "schema_version": "gravity-insight.read.v1",
            "operation_id": value.get("operation_id"),
            "status": value.get("status"),
            "error": None,
            "data": value.get("data"),
            "page": value.get("page"),
        }
    return safe_component(batch, platform, max_pages=max_pages)


def _product_parts(
    value: Mapping[str, Any],
) -> tuple[
    tuple[str, ...], tuple[str, str], int, tuple[int, int, int], list[Any]
] | None:
    if (value.get("schema_version"), value.get("operation_id")) != (
        SCHEMA_VERSION, MATERIAL_REPORT_OPERATION
    ):
        return None
    platforms = _product_platforms(value.get("platforms"))
    window = _product_window(value.get("date_range"))
    app_count = value.get("app_count")
    if platforms is None or window is None or not _valid_app_count(app_count):
        return None
    limits = _product_limits(value.get("limits"), len(platforms))
    results = value.get("results")
    if limits is None or not isinstance(results, list):
        return None
    if len(results) != len(platforms):
        return None
    return platforms, window, app_count, limits, results


def _matches_expected(
    platforms: tuple[str, ...],
    window: tuple[str, str],
    app_count: int,
    limits: tuple[int, int, int],
    *,
    expected_platforms: tuple[str, ...] | None,
    expected_app_count: int | None,
    expected_window: tuple[str, str] | None,
    expected_max_pages: int | None,
    expected_max_items: int | None,
    expected_max_workers: int | None,
) -> bool:
    expected = (
        expected_platforms, expected_window, expected_app_count,
        expected_max_pages, expected_max_items, expected_max_workers,
    )
    actual = (platforms, window, app_count, *limits)
    return all(
        wanted is None or wanted == found
        for wanted, found in zip(expected, actual)
    )


def _valid_app_count(value: Any) -> bool:
    return type(value) is int and 1 <= value <= 100


def _product_platforms(value: Any) -> tuple[str, ...] | None:
    if not isinstance(value, list) or not value:
        return None
    if any(not isinstance(item, str) or item not in _PLATFORMS for item in value):
        return None
    selected = tuple(value)
    return selected if len(set(selected)) == len(selected) else None


def _product_window(value: Any) -> tuple[str, str] | None:
    if not isinstance(value, Mapping) or value.get("inclusive") is not True:
        return None
    start, end = value.get("start"), value.get("end")
    if not isinstance(start, str) or not isinstance(end, str):
        return None
    try:
        from .material_performance import normalize_material_window

        return normalize_material_window(start, end)
    except ValueError:
        return None


def _product_limits(value: Any, platform_count: int) -> tuple[int, int, int] | None:
    if not isinstance(value, Mapping):
        return None
    pages = value.get("max_pages_per_platform")
    items = value.get("max_items_shared")
    workers = value.get("platform_workers")
    page_workers = value.get("page_workers_per_platform")
    if (
        type(pages) is not int
        or not 1 <= pages <= 1_000
        or type(items) is not int
        or not platform_count <= items <= 100_000
        or type(workers) is not int
        or not 1 <= workers <= platform_count
        or type(page_workers) is not int
        or page_workers != 1
    ):
        return None
    return pages, items, workers


__all__ = [
    "is_material_performance_result",
    "project_material_performance_result",
    "sanitize_product_result",
]
