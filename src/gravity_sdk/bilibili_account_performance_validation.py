"""Schema validators for Bilibili account performance results."""

from __future__ import annotations

import copy
import math
from collections.abc import Mapping
from typing import Any


ROW_FIELDS = frozenset({
    "advertiser_id",
    "average_cost_per_thousand",
    "click_count",
    "click_rate",
    "cost_per_click",
    "product_name",
    "san_lian_launch_total_consume",
    "show_count",
    "total_cash_consume",
    "total_consume",
    "total_red_packet_consume",
    "total_special_red_packet_consume",
})
TOTAL_FIELDS = ROW_FIELDS - {"advertiser_id", "product_name"}

_COUNT_FIELDS = frozenset({"click_count", "show_count"})
_NATIVE_DATA_FIELDS = frozenset({"list", "page_info", "total"})
_NATIVE_PAGE_FIELDS = frozenset({
    "number", "size", "item_count", "total_pages", "total_items", "has_more",
    "pages_fetched", "fetch_strategy", "max_workers",
})
_PUBLIC_PAGE_FIELDS = _NATIVE_PAGE_FIELDS - {"fetch_strategy", "max_workers"}
_PAGE_INFO_FIELDS = frozenset({"page", "page_size", "total_number", "total_page"})
_PAGE_STRATEGIES = frozenset({
    "single_page", "serial_known_total", "parallel_known_total",
    "serial_unknown_total",
})


def safe_native_payload(
    value: Mapping[str, Any],
    *,
    max_pages: int,
    max_items: int,
    max_workers: int,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None, dict[str, Any]] | None:
    data = value.get("data")
    if not isinstance(data, Mapping) or "list" not in data or set(data) - _NATIVE_DATA_FIELDS:
        return None
    rows = safe_rows(data.get("list"))
    total = safe_total(data.get("total")) if "total" in data else None
    count = len(rows or ())
    page = _safe_native_page(
        value.get("page"), count, max_pages, max_items, max_workers
    )
    if rows is None or total is False or page is None or not _safe_page_info(data.get("page_info")):
        return None
    expected = "empty" if not rows else "success"
    if value.get("status") != expected or count > max_items:
        return None
    return rows, total, page


def safe_rows(value: Any) -> list[dict[str, Any]] | None:
    if not isinstance(value, list):
        return None
    rows = [safe_row(item) for item in value]
    if any(row is None for row in rows):
        return None
    return [dict(row) for row in rows if row is not None]


def safe_row(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping) or set(value) != ROW_FIELDS:
        return None
    if not _identifier(value.get("advertiser_id")):
        return None
    product = value.get("product_name")
    if not isinstance(product, str) or not product or len(product) > 8_192:
        return None
    if not _safe_metrics(value, TOTAL_FIELDS):
        return None
    return copy.deepcopy(dict(value))


def safe_total(value: Any) -> dict[str, Any] | None | bool:
    if value is None:
        return None
    if not isinstance(value, Mapping) or set(value) != TOTAL_FIELDS:
        return False
    return copy.deepcopy(dict(value)) if _safe_metrics(value, TOTAL_FIELDS) else False


def safe_public_page(
    value: Any, count: int, limits: Mapping[str, int]
) -> dict[str, Any] | None:
    if not isinstance(value, Mapping) or set(value) != _PUBLIC_PAGE_FIELDS:
        return None
    positive = ("number", "size", "pages_fetched")
    optional = ("total_pages", "total_items")
    if (
        value.get("item_count") != count
        or any(type(value.get(key)) is not int or value[key] < 1 for key in positive)
        or value.get("pages_fetched") > limits["max_pages"]
        or count > limits["max_items"]
        or any(
            value.get(key) is not None
            and (type(value[key]) is not int or value[key] < 0)
            for key in optional
        )
        or value.get("has_more") is not False
    ):
        return None
    return copy.deepcopy(dict(value))


def request_inputs(window: tuple[str, str], max_items: int) -> dict[str, Any]:
    return {
        "date_list": [window[0], window[1]],
        "filtering": {},
        "filters": [],
        "order_by": [],
        "page": 1,
        "page_size": min(100, max_items),
    }


def _safe_native_page(
    value: Any,
    count: int,
    max_pages: int,
    max_items: int,
    max_workers: int,
) -> dict[str, Any] | None:
    if not isinstance(value, Mapping) or set(value) != _NATIVE_PAGE_FIELDS:
        return None
    if value.get("fetch_strategy") not in _PAGE_STRATEGIES:
        return None
    if value.get("max_workers") != max_workers:
        return None
    public = {key: value[key] for key in _PUBLIC_PAGE_FIELDS}
    limits = {"max_pages": max_pages, "max_items": max_items}
    return safe_public_page(public, count, limits)


def _safe_page_info(value: Any) -> bool:
    return value is None or bool(
        isinstance(value, Mapping)
        and not (set(value) - _PAGE_INFO_FIELDS)
        and all(type(item) is int and item >= 0 for item in value.values())
    )


def _safe_metrics(value: Mapping[str, Any], fields: frozenset[str]) -> bool:
    for field in fields:
        item = value.get(field)
        if field in _COUNT_FIELDS:
            if not _nonnegative_integer(item):
                return False
        elif not _finite_number(item):
            return False
    return True


def _identifier(value: Any) -> bool:
    return type(value) is int and value >= 0 and value.bit_length() <= 256


def _nonnegative_integer(value: Any) -> bool:
    return type(value) is int and value >= 0 and value.bit_length() <= 256


def _finite_number(value: Any) -> bool:
    return (
        type(value) is int and value.bit_length() <= 256
        or isinstance(value, float) and math.isfinite(value)
    )


__all__ = [
    "ROW_FIELDS",
    "TOTAL_FIELDS",
    "request_inputs",
    "safe_native_payload",
    "safe_public_page",
    "safe_row",
    "safe_rows",
    "safe_total",
]
