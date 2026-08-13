"""Compact controls that compile directly to proven Analysis wire fields."""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from typing import Any

from .errors import InputValidationError


def retention_controls(spec: Mapping[str, Any]) -> dict[str, Any]:
    offset = spec.get("offset")
    if not isinstance(offset, int) or isinstance(offset, bool) or not 1 <= offset <= 365:
        raise InputValidationError(
            "retention offset must be an integer from 1 through 365", field="offset"
        )
    controls = {
        "offset": offset,
        "period_calc_method": _choice(
            spec.get("period_calc_method"), {"SUM", "WEIGHTED_AVG"}, "period_calc_method"
        ),
        "custom_before_method": _choice(
            spec.get("custom_before_method"), {"SUM", "WEIGHTED_AVG"}, "custom_before_method"
        ),
        "total_calc_type": _choice(
            spec.get("total_calc_type"), {"DAY", "WEEK", "MONTH"}, "total_calc_type"
        ),
        "week_first_day": _integer_range(spec.get("week_first_day"), 1, 7, "week_first_day"),
    }
    if "query_item_before_after" in spec:
        controls["query_item_before_after"] = copy.deepcopy(
            dict(_mapping(spec["query_item_before_after"], "query_item_before_after"))
        )
    return controls


def funnel_window(value: Any) -> dict[str, Any]:
    item = _mapping(value, "window")
    _reject_keys(item, {"unit", "value"}, "window")
    unit = _choice(
        item.get("unit"), {"today", "minute", "hour", "day"}, "window.unit"
    )
    limit = {"today": 1, "minute": 60, "hour": 24, "day": 30}[unit]
    return {
        "type": unit,
        "val": _integer_range(item.get("value"), 1, limit, "window.value"),
    }


def apply_scatter_zone(step: dict[str, Any], value: Any) -> None:
    if value is None:
        step["calc_zone"] = {"zone_type": "default"}
        return
    item = _mapping(value, "zone")
    _reject_keys(item, {"type", "ranges"}, "zone")
    zone_type = _choice(
        item.get("type"), {"default", "dispersed", "custom"}, "zone.type"
    )
    step["calc_zone"] = {"zone_type": zone_type}
    if zone_type == "dispersed":
        step["calc_zone"]["range_list"] = []
    if zone_type == "custom":
        step["calc_zone"]["range_list"] = _list(item.get("ranges"), "zone.ranges", 100)
    elif "ranges" in item:
        raise InputValidationError(
            f"{zone_type} zone does not accept ranges", field="zone.ranges"
        )


def _reject_keys(value: Mapping[str, Any], allowed: set[str], field: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise InputValidationError(
            f"{field} contains unsupported fields: {', '.join(unknown)}", field=field
        )


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise InputValidationError(f"{field} must be an object", field=field)
    return value


def _list(value: Any, field: str, maximum: int) -> list[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise InputValidationError(f"{field} must be an array", field=field)
    items = list(value)
    if len(items) > maximum:
        raise InputValidationError(f"{field} exceeds its {maximum}-item limit", field=field)
    return items


def _choice(value: Any, allowed: set[str], field: str) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise InputValidationError(
            f"{field} must be one of: {', '.join(sorted(allowed))}", field=field
        )
    return value


def _integer_range(value: Any, minimum: int, maximum: int, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not minimum <= value <= maximum:
        raise InputValidationError(
            f"{field} must be an integer from {minimum} through {maximum}", field=field
        )
    return value


__all__ = ["apply_scatter_zone", "funnel_window", "retention_controls"]
