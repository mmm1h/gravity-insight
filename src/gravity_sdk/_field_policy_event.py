"""Event, funnel, and scatter validators for the Analysis query DSL."""

from __future__ import annotations

import re
from typing import Any, Mapping

from ._field_policy_conditions import (
    validate_analysis_conditions,
    validate_analysis_group_by,
    validate_analysis_target,
)
from ._field_policy_shared import (
    ANALYSIS_CONTROL_ID_RE,
    ANALYSIS_EVENT_TYPES,
    ANALYSIS_FORMULA_RE,
    ANALYSIS_TARGET_METHODS,
    AnalysisReferences,
    reject_sensitive_analysis_field,
    require_exact_mapping,
    validate_optional_label,
)
from .errors import InputValidationError


def validate_analysis_event_items(
    value: Any,
    references: AnalysisReferences,
    *,
    minimum: int,
    maximum: int,
) -> None:
    if not isinstance(value, (list, tuple)) or not minimum <= len(value) <= maximum:
        raise InputValidationError(
            "analysis query_item_list has an invalid step count; request was not sent"
        )
    for item in value:
        _validate_analysis_event_item(item, references)


def _validate_analysis_event_item(item: Any, references: AnalysisReferences) -> None:
    require_exact_mapping(
        item,
        {
            "event_name",
            "event_label",
            "custom_name",
            "target",
            "conditions",
            "cond_logic",
            "event_index",
            "split_event",
        },
        "analysis query item",
    )
    event_name = item.get("event_name")
    if not isinstance(event_name, str) or not event_name or len(event_name) > 256:
        raise InputValidationError(
            "analysis event_name is invalid; request was not sent"
        )
    references.events.add(event_name)
    validate_optional_label(item.get("event_label"), "event_label")
    validate_optional_label(item.get("custom_name"), "custom_name")
    if item.get("cond_logic", "AND") not in {"AND", "OR"}:
        raise InputValidationError(
            "analysis cond_logic is not supported; request was not sent"
        )
    _validate_event_index(item.get("event_index"))
    if item.get("split_event") is not None and item.get("split_event") not in {
        0,
        1,
        False,
        True,
    }:
        raise InputValidationError(
            "analysis split_event flag is invalid; request was not sent"
        )
    validate_analysis_target(
        item.get("target"),
        references.event_fields,
        references.event_dimension_tables,
    )
    validate_analysis_conditions(
        item.get("conditions", ()), references, "query item conditions"
    )


def _validate_event_index(value: Any) -> None:
    if value is not None and (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < 0
        or value > 49
    ):
        raise InputValidationError(
            "analysis event_index is invalid; request was not sent"
        )


def validate_event_query_labels(value: Any) -> None:
    if not isinstance(value, (list, tuple)):
        raise InputValidationError(
            "analysis event labels are invalid; request was not sent"
        )
    for item in value:
        custom_name = item.get("custom_name") if isinstance(item, Mapping) else None
        if not isinstance(custom_name, str) or not custom_name:
            raise InputValidationError(
                "analysis event custom_name must be non-empty; request was not sent"
            )
        reject_sensitive_analysis_field(custom_name)


def validate_analysis_scatter_items(
    value: Any,
    references: AnalysisReferences,
    *,
    minimum: int,
    maximum: int,
) -> None:
    if not isinstance(value, (list, tuple)) or not minimum <= len(value) <= maximum:
        raise InputValidationError(
            "analysis scatter query_item_list is invalid; request was not sent"
        )
    for item in value:
        _validate_analysis_scatter_item(item, references)


def _validate_analysis_scatter_item(
    item: Any, references: AnalysisReferences
) -> None:
    scatter_keys = {
        "calc_zone",
        "prop_to_calc",
        "prop_to_calc_sub",
        "dim_using_table_name",
    }
    base_keys = {
        "event_name",
        "event_label",
        "custom_name",
        "target",
        "conditions",
        "cond_logic",
        "event_index",
        "split_event",
    }
    require_exact_mapping(item, base_keys | scatter_keys, "analysis scatter query item")
    validate_analysis_event_items(
        [{key: item[key] for key in base_keys if key in item}],
        references,
        minimum=1,
        maximum=1,
    )
    validate_analysis_scatter_config(item.get("calc_zone"))
    field = _validate_scatter_property(item)
    references.event_fields.add(field)
    _validate_scatter_aggregate(item.get("prop_to_calc_sub"))
    table = item.get("dim_using_table_name")
    if table not in {None, ""}:
        if not isinstance(table, str) or len(table) > 256:
            raise InputValidationError(
                "analysis dimension table is invalid; request was not sent"
            )
        references.event_dimension_tables.add((field, table))


def _validate_scatter_property(item: Mapping[str, Any]) -> str:
    field = item.get("prop_to_calc")
    if not isinstance(field, str) or not field or len(field) > 256:
        raise InputValidationError(
            "analysis scatter property is invalid; request was not sent"
        )
    reject_sensitive_analysis_field(field)
    return field


def _validate_scatter_aggregate(value: Any) -> None:
    if value in {None, ""}:
        return
    if not isinstance(value, str) or not (
        value in ANALYSIS_TARGET_METHODS
        or re.fullmatch(r"Quantile(?:_(?:[1-9]|[1-9][0-9]|100))?", value)
    ):
        raise InputValidationError(
            "analysis scatter aggregate is not registered; request was not sent"
        )


def validate_analysis_custom_items(
    value: Any, references: AnalysisReferences
) -> None:
    if not isinstance(value, (list, tuple)) or len(value) > 50:
        raise InputValidationError(
            "analysis custom_query_item_list is invalid; request was not sent"
        )
    for item in value:
        _validate_analysis_custom_item(item, references)


def _validate_analysis_custom_item(item: Any, references: AnalysisReferences) -> None:
    require_exact_mapping(
        item,
        {"custom_name", "formula", "query_item_list", "decimal_point", "event_index"},
        "analysis custom query item",
    )
    validate_optional_label(item.get("custom_name"), "custom_name")
    formula = item.get("formula")
    if not isinstance(formula, str) or not ANALYSIS_FORMULA_RE.fullmatch(formula):
        raise InputValidationError(
            "analysis formula accepts arithmetic placeholders only; request was not sent"
        )
    nested = item.get("query_item_list")
    validate_analysis_event_items(nested, references, minimum=1, maximum=20)
    if formula.lower().count("x") != len(nested):
        raise InputValidationError(
            "analysis formula placeholder count is invalid; request was not sent"
        )
    if item.get("decimal_point") not in {
        None,
        "zero_point",
        "one_point",
        "two_point",
        "three_point",
        "four_point",
    }:
        raise InputValidationError(
            "analysis decimal_point is not registered; request was not sent"
        )
    _validate_event_index(item.get("event_index"))


def validate_analysis_window(value: Any) -> None:
    require_exact_mapping(value, {"type", "val"}, "analysis funnel window")
    window_type = value.get("type")
    window_value = value.get("val")
    limits = {"today": 1, "day": 30, "hour": 24, "minute": 60}
    if window_type not in limits or (
        not isinstance(window_value, int)
        or isinstance(window_value, bool)
        or not 1 <= window_value <= limits[window_type]
    ):
        raise InputValidationError(
            "analysis funnel window is outside the controlled range; request was not sent"
        )


def validate_analysis_scatter_config(value: Any) -> None:
    require_exact_mapping(value, {"zone_type", "range_list"}, "analysis scatter calc_zone")
    zone_type = value.get("zone_type")
    if zone_type not in {"default", "dispersed", "custom"}:
        raise InputValidationError(
            "analysis scatter zone is not registered; request was not sent"
        )
    ranges = value.get("range_list", ())
    if zone_type == "custom":
        if not _valid_scatter_ranges(ranges):
            raise InputValidationError(
                "analysis custom scatter range is invalid; request was not sent"
            )
    elif ranges not in (None, (), []):
        raise InputValidationError(
            "analysis scatter range requires custom mode; request was not sent"
        )


def _valid_scatter_ranges(value: Any) -> bool:
    return (
        isinstance(value, (list, tuple))
        and bool(value)
        and len(value) <= 100
        and all(
            isinstance(item, (int, float))
            and not isinstance(item, bool)
            and float("-inf") < float(item) < float("inf")
            for item in value
        )
    )


def validate_analysis_split_event(
    value: Any, references: AnalysisReferences
) -> None:
    if value in (None, {}):
        return
    require_exact_mapping(
        value, {"order", "event_list", "group_by_list"}, "analysis split_event"
    )
    if value.get("order") not in {"before", "after"}:
        raise InputValidationError(
            "analysis split-event order is not registered; request was not sent"
        )
    event_list = value.get("event_list")
    if not _valid_event_name_list(event_list):
        raise InputValidationError(
            "analysis split-event event_list is invalid; request was not sent"
        )
    references.events.update(event_list)
    groups = value.get("group_by_list")
    if not isinstance(groups, (list, tuple)) or any(
        not isinstance(item, Mapping) or item.get("type") not in ANALYSIS_EVENT_TYPES
        for item in groups
    ):
        raise InputValidationError(
            "analysis split-event groups must be event properties; request was not sent"
        )
    validate_analysis_group_by(groups, references)


def _valid_event_name_list(value: Any) -> bool:
    return (
        isinstance(value, (list, tuple))
        and bool(value)
        and len(value) <= 50
        and all(isinstance(item, str) and bool(item) and len(item) <= 256 for item in value)
    )


def validate_analysis_aggregate_config(value: Any) -> None:
    require_exact_mapping(
        value, {"to_calc_type", "period_calc_method_map"}, "aggregate_config"
    )
    calc_type = value.get("to_calc_type")
    if calc_type is not None and calc_type not in {"approximate", "precise"}:
        raise InputValidationError(
            "analysis aggregate calculation type is invalid; request was not sent"
        )
    methods = value.get("period_calc_method_map", {})
    if not isinstance(methods, Mapping) or len(methods) > 50:
        raise InputValidationError(
            "analysis period calculation map is invalid; request was not sent"
        )
    for key, item in methods.items():
        if (
            not isinstance(key, str)
            or not ANALYSIS_CONTROL_ID_RE.fullmatch(key)
            or item not in {"SUM", "WEIGHTED_AVG", "AVG", "MAX", "MIN"}
        ):
            raise InputValidationError(
                "analysis period calculation map is invalid; request was not sent"
            )


def validate_analysis_extra_data(value: Any) -> None:
    require_exact_mapping(value, {"client_server_time"}, "analysis extra_data")
    timestamp = value.get("client_server_time")
    if timestamp is not None and (
        not isinstance(timestamp, (str, int, float))
        or isinstance(timestamp, bool)
        or (isinstance(timestamp, str) and len(timestamp) > 64)
    ):
        raise InputValidationError(
            "analysis client_server_time is invalid; request was not sent"
        )
