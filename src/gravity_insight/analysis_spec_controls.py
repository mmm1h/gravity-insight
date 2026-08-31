"""Compact controls that compile directly to proven Analysis wire fields."""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from typing import Any

from .actionable_error_values import actual_value, allowed_values
from .errors import InputValidationError


def validate_time_grain(
    kind: str, value: Any, allowed: frozenset[str]
) -> None:
    """Reject compact grains that lack evidence for the selected kind."""

    if value is None:
        return
    if isinstance(value, str) and value in allowed:
        return
    next_action = None
    if kind == "event" and value in {"hour", "minute"}:
        next_action = (
            "Change only `time_grain` to `day` and rerun `gravity analysis query "
            "--kind event --app <authorized-alias> --spec <day-spec>` to keep the "
            "verified calendar-day boundary. No SDK path has verified the exact "
            "first-traffic hour or minute; do not retry this request or substitute "
            "`analysis.user_event.list`, which requires user-level ClientID. "
            f"Re-enable `{value}` only after a sanitized `analysis.event.query` "
            f"with `create_time/{value}` succeeds."
        )
    raise InputValidationError(
        f"actual value: {actual_value(value)}; {kind} time_grain is not supported "
        f"by current upstream evidence; allowed values: {allowed_values(allowed)}",
        field="time_grain",
        next_action=next_action,
    )


def retention_controls(spec: Mapping[str, Any]) -> dict[str, Any]:
    _reject_unsupported_retention_cohorts(spec)
    offset = spec.get("offset")
    if not isinstance(offset, int) or isinstance(offset, bool) or not 1 <= offset <= 365:
        raise InputValidationError(
            f"actual value: {actual_value(offset)}; retention offset must be an "
            "integer from 1 through 365",
            field="offset",
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


def _reject_unsupported_retention_cohorts(spec: Mapping[str, Any]) -> None:
    property_conditions = spec.get("property_conditions")
    if (
        isinstance(property_conditions, Sequence)
        and not isinstance(property_conditions, (str, bytes))
        and len(property_conditions) > 0
    ):
        raise InputValidationError(
            f"actual value: {actual_value({'count': len(property_conditions)})}; "
            "Retention property_conditions are not supported by the upstream "
            "Retention endpoint",
            field="property_conditions",
            next_action=(
                "Use `gravity analysis segment evaluate --spec-schema`; evaluate "
                "the first-pay property cohort once for the denominator and the "
                "same cohort AND the next-day launch event for the numerator, then "
                "compute numerator.part / denominator.part. Do not retry this "
                "Retention spec."
            ),
        )

    before_after = spec.get("query_item_before_after")
    if not isinstance(before_after, Mapping):
        return
    before_custom = before_after.get("before_custom")
    if isinstance(before_custom, Mapping) and before_custom:
        raise InputValidationError(
            f"actual value: {actual_value({'non_empty': True})}; Retention "
            "query_item_before_after.before_custom is not supported by the "
            "upstream Retention endpoint",
            field="query_item_before_after.before_custom",
            next_action=(
                "Use a one-day `gravity analysis query --kind funnel` with the "
                "supported `type=user` filter; persist matched step 1 with "
                "`gravity analysis segment create-from-analysis --step 1 "
                "--matched`; evaluate that segment alone and AND the next-day "
                "launch event with `gravity analysis segment evaluate`; then "
                "compute numerator.part / denominator.part. Do not retry this "
                "Retention spec."
            ),
        )


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
            f"actual value: {actual_value(item.get('ranges'))}; {zone_type} zone "
            "does not accept ranges; remove zone.ranges or use zone.type custom",
            field="zone.ranges",
        )


def _reject_keys(value: Mapping[str, Any], allowed: set[str], field: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise InputValidationError(
            f"actual value: {actual_value(unknown)}; allowed fields: "
            f"{allowed_values(allowed)}",
            field=field,
        )


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise InputValidationError(
            f"actual value: {actual_value(value)}; allowed type: object", field=field
        )
    return value


def _list(value: Any, field: str, maximum: int) -> list[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise InputValidationError(
            f"actual value: {actual_value(value)}; allowed type: array", field=field
        )
    items = list(value)
    if len(items) > maximum:
        raise InputValidationError(
            f"actual value: {len(items)} items; allowed maximum: {maximum} items",
            field=field,
        )
    return items


def _choice(value: Any, allowed: set[str], field: str) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise InputValidationError(
            f"actual value: {actual_value(value)}; allowed values: "
            f"{allowed_values(allowed)}",
            field=field,
        )
    return value


def _integer_range(value: Any, minimum: int, maximum: int, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not minimum <= value <= maximum:
        raise InputValidationError(
            f"actual value: {actual_value(value)}; allowed range: integer from "
            f"{minimum} through {maximum}",
            field=field,
        )
    return value


__all__ = [
    "apply_scatter_zone",
    "funnel_window",
    "retention_controls",
    "validate_time_grain",
]
