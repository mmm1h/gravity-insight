"""Segment-rule validators for the Analysis evaluation DSL."""

from __future__ import annotations

import math
from typing import Any, Mapping

from .actionable_error_values import actual_value, allowed_values
from ._field_policy_conditions import validate_analysis_target
from ._field_policy_shared import (
    ANALYSIS_CONDITION_OPERATORS,
    ANALYSIS_EVENT_TYPES,
    ANALYSIS_USER_TYPES,
    AnalysisReferences,
    new_analysis_references,
    parse_iso_calendar_date,
    reject_sensitive_analysis_field,
    require_exact_mapping,
    validate_scalar_list,
)
from .errors import InputValidationError


SEGMENT_RULE_OPERATORS = ANALYSIS_CONDITION_OPERATORS | frozenset(
    {"TRUE", "FALSE", "CURRENT_DAY", "RELATIVELY_CURRENT_TIME"}
)
SEGMENT_QUICK_RANGES = frozenset(
    {
        "yesterday",
        "today",
        "lastweek",
        "week",
        "lastmonth",
        "month",
        "recent3day",
        "last3day",
        "last7day",
        "last14day",
        "last30day",
        "last90day",
        "last120day",
        "recent7day",
        "recent30day",
    }
)
_SEGMENT_SPEC_SCHEMA_ACTION = "gravity analysis segment evaluate --spec-schema"
_SEGMENT_VERSION_MODES = frozenset({None, "", "LATEST", "DYNAMIC_MATCHING", "FIXED_VERSION"})


def validate_analysis_segment_rule_shape(
    inputs: Mapping[str, Any],
) -> AnalysisReferences:
    require_exact_mapping(
        inputs,
        {
            "app_id",
            "name",
            "remark",
            "update_type",
            "date_range",
            "cond_logic",
            "user_property_rules",
            "user_event_rules",
        },
        "analysis segment evaluation",
    )
    _validate_segment_header(inputs)
    validate_segment_update_date_range(inputs.get("date_range"))
    references = new_analysis_references()
    validate_segment_property_rules(inputs.get("user_property_rules"), references)
    validate_segment_event_rules(inputs.get("user_event_rules"), references)
    return references


def _validate_segment_header(inputs: Mapping[str, Any]) -> None:
    name = inputs.get("name")
    remark = inputs.get("remark", "")
    if not isinstance(name, str) or not name or len(name) > 20:
        raise InputValidationError(
            f"actual value: {actual_value(name)}; allowed value: a non-empty segment "
            "name of at most 20 characters",
            field="name",
        )
    if not isinstance(remark, str) or len(remark) > 2_000:
        raise InputValidationError(
            f"actual value: {len(remark) if isinstance(remark, str) else actual_value(type(remark).__name__)}; "
            "allowed value: a string of at most 2000 characters",
            field="remark",
        )
    update_type = inputs.get("update_type")
    if update_type not in {"Manual", "Routine"}:
        raise InputValidationError(f"actual value: {actual_value(update_type)}; allowed values: \"Manual\", \"Routine\"", field="update_type")
    cond_logic = inputs.get("cond_logic")
    if cond_logic not in {"AND", "OR"}:
        raise InputValidationError(f"actual value: {actual_value(cond_logic)}; allowed values: \"AND\", \"OR\"", field="cond_logic")


def validate_segment_update_date_range(value: Any) -> None:
    require_exact_mapping(
        value, {"start_date", "end_date"}, "analysis segment update date range"
    )
    start = parse_iso_calendar_date(value.get("start_date"), "segment start_date")
    raw_end = value.get("end_date")
    if raw_end is None:
        return
    end = parse_iso_calendar_date(raw_end, "segment end_date")
    if start > end:
        raise InputValidationError(
            f"actual value: {actual_value({'start_date': value.get('start_date'), 'end_date': raw_end})}; "
            "allowed order: start_date must be on or before end_date",
            field="date_range",
        )


def validate_segment_property_rules(
    value: Any, references: AnalysisReferences
) -> None:
    require_exact_mapping(
        value, {"cond_logic", "groups"}, "analysis segment property rules"
    )
    validate_segment_logic(value.get("cond_logic"), "property rules")
    groups = value.get("groups")
    if not isinstance(groups, (list, tuple)) or len(groups) > 50:
        raise InputValidationError(
            f"actual value: {len(groups) if isinstance(groups, (list, tuple)) else actual_value(type(groups).__name__)}; "
            "allowed value: an array with at most 50 property groups",
            field="user_property_rules.groups",
        )
    for group in groups:
        _validate_segment_property_group(group, references)


def _validate_segment_property_group(
    group: Any, references: AnalysisReferences
) -> None:
    require_exact_mapping(
        group, {"cond_logic", "conditions"}, "analysis segment property group"
    )
    validate_segment_logic(group.get("cond_logic"), "property group")
    conditions = group.get("conditions")
    if not isinstance(conditions, (list, tuple)) or len(conditions) > 100:
        raise InputValidationError(
            f"actual value: {len(conditions) if isinstance(conditions, (list, tuple)) else actual_value(type(conditions).__name__)}; "
            "allowed value: an array with at most 100 property conditions",
            field="user_property_rules.groups[].conditions",
        )
    for condition in conditions:
        validate_segment_rule_condition(condition, references)


def validate_segment_event_rules(
    value: Any, references: AnalysisReferences
) -> None:
    require_exact_mapping(
        value, {"cond_logic", "groups"}, "analysis segment event rules"
    )
    validate_segment_logic(value.get("cond_logic"), "event rules")
    groups = value.get("groups")
    if not isinstance(groups, (list, tuple)) or len(groups) > 50:
        raise InputValidationError(
            f"actual value: {len(groups) if isinstance(groups, (list, tuple)) else actual_value(type(groups).__name__)}; "
            "allowed value: an array with at most 50 event groups",
            field="user_event_rules.groups",
        )
    for group in groups:
        _validate_segment_event_group(group, references)


def _validate_segment_event_group(
    group: Any, references: AnalysisReferences
) -> None:
    require_exact_mapping(
        group, {"cond_logic", "conditions"}, "analysis segment event group"
    )
    validate_segment_logic(group.get("cond_logic"), "event group")
    events = group.get("conditions")
    if not isinstance(events, (list, tuple)) or len(events) > 100:
        raise InputValidationError(
            f"actual value: {len(events) if isinstance(events, (list, tuple)) else actual_value(type(events).__name__)}; "
            "allowed value: an array with at most 100 event rules",
            field="user_event_rules.groups[].conditions",
        )
    for event in events:
        validate_segment_rule_event(event, references)


def validate_segment_rule_event(
    value: Any, references: AnalysisReferences
) -> None:
    require_exact_mapping(
        value,
        {
            "event_name",
            "did",
            "target",
            "did_condition",
            "date_range",
            "cond_logic",
            "conditions",
        },
        "analysis segment event",
    )
    event_name = value.get("event_name")
    if not isinstance(event_name, str) or not event_name or len(event_name) > 256:
        raise InputValidationError(
            f"actual value: {actual_value(event_name)}; allowed value: a non-empty "
            "event name of at most 256 characters",
            field="user_event_rules.groups[].conditions[].event_name",
            next_action="Run `gravity metadata events \"\"` and retry with a listed event.",
        )
    references.events.add(event_name)
    if not isinstance(value.get("did"), bool):
        raise InputValidationError(f"actual value: {actual_value(value.get('did'))}; allowed values: true, false", field="user_event_rules.groups[].conditions[].did")
    _validate_segment_event_target(value.get("target"), references)
    _validate_did_condition(value.get("did_condition"))
    validate_segment_event_date_range(value.get("date_range"))
    validate_segment_logic(value.get("cond_logic"), "event")
    conditions = value.get("conditions")
    if not isinstance(conditions, (list, tuple)) or len(conditions) > 100:
        raise InputValidationError(
            f"actual value: {len(conditions) if isinstance(conditions, (list, tuple)) else actual_value(type(conditions).__name__)}; "
            "allowed value: an array with at most 100 event-property conditions",
            field="user_event_rules.groups[].conditions[].conditions",
        )
    for condition in conditions:
        validate_segment_rule_condition(condition, references)


def _validate_segment_event_target(
    target: Any, references: AnalysisReferences
) -> None:
    require_exact_mapping(
        target,
        {"name", "field", "dim_using_table_name"},
        "analysis segment event target",
    )
    validate_analysis_target(
        target, references.event_fields, references.event_dimension_tables
    )


def _validate_did_condition(value: Any) -> None:
    require_exact_mapping(
        value, {"operator", "value"}, "analysis segment did condition"
    )
    # The request codec copies this control verbatim.  Unlike ordinary rule
    # conditions it has no frontend transformation for relative/boolean
    # pseudo-operators, so only the proven base operator vocabulary is valid.
    if value.get("operator") not in ANALYSIS_CONDITION_OPERATORS:
        raise InputValidationError(f"actual value: {actual_value(value.get('operator'))}; allowed operators: {allowed_values(ANALYSIS_CONDITION_OPERATORS, discovery_action=_SEGMENT_SPEC_SCHEMA_ACTION)}", field="user_event_rules.groups[].conditions[].did_condition.operator")
    validate_scalar_list(value.get("value"), "analysis segment did condition value")


def validate_segment_rule_condition(
    value: Any, references: AnalysisReferences
) -> None:
    require_exact_mapping(
        value,
        {
            "field",
            "type",
            "operator",
            "value",
            "dim_using_table_name",
            "segment_type",
            "version_id",
            "date_type",
            "date_unit",
            "date_relative_type",
            "date_relative_unit",
            "date_relative_left",
            "date_relative_right",
        },
        "analysis segment condition",
    )
    field = value.get("field")
    if not isinstance(field, str) or not field or len(field) > 256:
        raise InputValidationError(
            f"actual value: {actual_value(field)}; allowed value: a non-empty metadata "
            "field name of at most 256 characters",
            field="conditions[].field",
            next_action="Run `gravity metadata properties \"\"` or `gravity metadata events \"\"` and retry with a listed field.",
        )
    reject_sensitive_analysis_field(field)
    if value.get("operator") not in SEGMENT_RULE_OPERATORS:
        raise InputValidationError(f"actual value: {actual_value(value.get('operator'))}; allowed operators: {allowed_values(SEGMENT_RULE_OPERATORS, discovery_action=_SEGMENT_SPEC_SCHEMA_ACTION)}", field="conditions[].operator")
    validate_scalar_list(value.get("value"), "analysis segment condition value")
    _validate_segment_operator_shape(value)
    is_segment = _add_segment_condition_reference(value, field, references)
    _add_segment_condition_dimension(value, field, is_segment, references)
    validate_segment_condition_date_controls(value)


_SEGMENT_DATE_CONTROLS = frozenset(
    {
        "date_type",
        "date_unit",
        "date_relative_type",
        "date_relative_unit",
        "date_relative_left",
        "date_relative_right",
    }
)


def _validate_segment_operator_shape(value: Mapping[str, Any]) -> None:
    """Reject controls the wire codec would otherwise ignore or misinterpret."""

    operator = value.get("operator")
    values = list(value.get("value", ()))
    if value.get("type") == "user_segment":
        if operator != "TRUE" or values:
            raise InputValidationError(
                f"actual value: {actual_value({'operator': operator, 'value_count': len(values)})}; "
                "allowed shape: a segment reference must use operator TRUE with an empty value array",
                field="conditions[]",
            )
        _reject_segment_date_controls(value)
        return
    if operator in {"TRUE", "FALSE"}:
        if values:
            raise InputValidationError(f"actual value: {len(values)} condition values; allowed value: an empty array when operator is {operator}", field="conditions[].value")
        _reject_segment_date_controls(value)
        return
    if operator == "CURRENT_DAY":
        _require_numeric_values(values, 1, "current-day")
        _require_choices(value, "date_type", {"past", "future"})
        _require_choices(value, "date_unit", {"within", "outside"})
        _reject_segment_date_controls(value, allowed={"date_type", "date_unit"})
        return
    if operator == "RELATIVE_DAY":
        _require_numeric_values(values, 2, "relative-day")
        _require_choices(value, "date_type", {"past", "future"})
        _reject_segment_date_controls(value, allowed={"date_type"})
        return
    if operator == "RELATIVELY_CURRENT_TIME":
        _validate_relative_time_shape(value, values)
        return
    _reject_segment_date_controls(value)


def _validate_relative_time_shape(
    value: Mapping[str, Any], values: list[Any]
) -> None:
    relative_type = value.get("date_relative_type")
    if relative_type == "range":
        _require_numeric_values(values, 2, "relative-time range")
        _require_choices(
            value, "date_relative_unit", {"minute", "hour", "day"}
        )
        _require_choices(value, "date_relative_left", {"past", "future"})
        _require_choices(value, "date_relative_right", {"past", "future"})
        _reject_segment_date_controls(
            value,
            allowed={
                "date_relative_type",
                "date_relative_unit",
                "date_relative_left",
                "date_relative_right",
            },
        )
        return
    if relative_type not in {"day", "week", "month"} or values:
        raise InputValidationError(
            f"actual value: {actual_value({'date_relative_type': relative_type, 'value_count': len(values)})}; "
            "allowed values: date_relative_type day, week, or month with an empty value array",
            field="conditions[]",
        )
    _reject_segment_date_controls(value, allowed={"date_relative_type"})


def _require_numeric_values(values: list[Any], count: int, label: str) -> None:
    if len(values) != count or any(
        isinstance(item, bool)
        or not isinstance(item, (int, float))
        or isinstance(item, float) and not math.isfinite(item)
        or item < 0
        for item in values
    ):
        raise InputValidationError(
            f"actual value: {actual_value({'count': len(values), 'types': [type(item).__name__ for item in values]})}; "
            f"allowed value: exactly {count} finite, non-negative numeric {label} values",
            field="conditions[].value",
        )


def _require_choices(
    value: Mapping[str, Any], key: str, allowed: set[str]
) -> None:
    if value.get(key) not in allowed:
        raise InputValidationError(f"actual value: {actual_value(value.get(key))}; allowed values: {allowed_values(allowed)}", field=f"conditions[].{key}")


def _reject_segment_date_controls(
    value: Mapping[str, Any], *, allowed: set[str] | frozenset[str] = frozenset()
) -> None:
    invalid = [
        key
        for key in _SEGMENT_DATE_CONTROLS - set(allowed)
        if value.get(key) not in {None, ""}
    ]
    if invalid:
        raise InputValidationError(
            f"actual value: {actual_value(invalid)}; allowed controls for operator "
            f"{actual_value(value.get('operator'))}: {allowed_values(allowed)}",
            field="conditions[]",
        )


def _add_segment_condition_reference(
    value: Mapping[str, Any], field: str, references: AnalysisReferences
) -> bool:
    field_type = value.get("type")
    segment_type = value.get("segment_type")
    version_id = value.get("version_id")
    is_segment = field_type == "user_segment" or segment_type not in {None, ""}
    if is_segment:
        if field_type != "user_segment":
            raise InputValidationError(f"actual value: {actual_value(field_type)}; allowed value: \"user_segment\" when segment_type is present", field="conditions[].type")
        effective_type = _validate_segment_version(segment_type, version_id)
        references.segment_fields.add((field, effective_type, str(version_id or "")))
    elif field_type in ANALYSIS_EVENT_TYPES:
        references.event_fields.add(field)
    elif field_type in ANALYSIS_USER_TYPES:
        references.user_fields.add(field)
    else:
        raise InputValidationError(f"actual value: {actual_value(field_type)}; allowed values: {allowed_values(ANALYSIS_EVENT_TYPES | ANALYSIS_USER_TYPES | frozenset({'user_segment'}))}", field="conditions[].type")
    return is_segment


def _validate_segment_version(segment_type: Any, version_id: Any) -> str:
    if segment_type not in _SEGMENT_VERSION_MODES:
        raise InputValidationError(f"actual value: {actual_value(segment_type)}; allowed values: {allowed_values(_SEGMENT_VERSION_MODES)}", field="conditions[].segment_type")
    effective_type = str(segment_type or "LATEST")
    if effective_type == "FIXED_VERSION":
        if not isinstance(version_id, (str, int)) or isinstance(version_id, bool):
            raise InputValidationError(f"actual value: {actual_value(version_id)}; allowed value: a string or integer version id when segment_type is FIXED_VERSION", field="conditions[].version_id")
    elif version_id not in {None, ""}:
        raise InputValidationError(f"actual value: {actual_value(version_id)}; allowed value: null or \"\" unless segment_type is FIXED_VERSION", field="conditions[].version_id")
    return effective_type


def _add_segment_condition_dimension(
    value: Mapping[str, Any],
    field: str,
    is_segment: bool,
    references: AnalysisReferences,
) -> None:
    table = value.get("dim_using_table_name")
    if table in {None, ""}:
        return
    if is_segment or not isinstance(table, str) or len(table) > 256:
        raise InputValidationError(
            f"actual value: {actual_value(table)}; allowed value: a metadata dimension "
            "table name of at most 256 characters on an event or user condition",
            field="conditions[].dim_using_table_name",
            next_action="Run `gravity metadata properties \"\"` and retry with the field's listed dimension table.",
        )
    if value.get("type") in ANALYSIS_EVENT_TYPES:
        references.event_dimension_tables.add((field, table))
    else:
        references.user_dimension_tables.add((field, table))


def validate_segment_condition_date_controls(value: Mapping[str, Any]) -> None:
    enums = {
        "date_type": {"past", "future"},
        "date_unit": {"within", "outside"},
        "date_relative_type": {"range", "day", "week", "month"},
        "date_relative_unit": {"minute", "hour", "day", "week", "month"},
        "date_relative_left": {"past", "future"},
        "date_relative_right": {"past", "future"},
    }
    for key, allowed in enums.items():
        item = value.get(key)
        if item not in {None, ""} and item not in allowed:
            raise InputValidationError(f"actual value: {actual_value(item)}; allowed values: null, \"\", {allowed_values(allowed)}", field=f"conditions[].{key}")


def validate_segment_event_date_range(value: Any) -> None:
    require_exact_mapping(
        value,
        {
            "date_type",
            "date",
            "quick_select",
            "start_date",
            "dynamic_start_type",
            "dynamic_end_type",
            "start_date_input",
            "end_date_input",
        },
        "analysis segment event date range",
    )
    date_type = value.get("date_type")
    if date_type not in {"static", "dynamic"}:
        raise InputValidationError(f"actual value: {actual_value(date_type)}; allowed values: \"dynamic\", \"static\"", field="date_range.date_type")
    quick_select = value.get("quick_select")
    if quick_select not in {None, ""}:
        if quick_select not in SEGMENT_QUICK_RANGES:
            raise InputValidationError(f"actual value: {actual_value(quick_select)}; allowed values: {allowed_values(SEGMENT_QUICK_RANGES)}", field="date_range.quick_select")
        return
    if date_type == "static":
        _validate_static_event_date_range(value.get("date"))
        return
    _validate_dynamic_event_date_range(value)


def _validate_static_event_date_range(value: Any) -> None:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise InputValidationError(
            f"actual value: {actual_value(value)}; allowed value: exactly two ISO "
            "calendar dates [start, end]",
            field="date_range.date",
        )
    start = parse_iso_calendar_date(value[0], "segment event start date")
    end = parse_iso_calendar_date(value[1], "segment event end date")
    if start > end:
        raise InputValidationError(
            f"actual value: {actual_value(value)}; allowed order: start date must be on "
            "or before end date",
            field="date_range.date",
        )


def _validate_dynamic_event_date_range(value: Mapping[str, Any]) -> None:
    start_type = value.get("dynamic_start_type")
    end_type = value.get("dynamic_end_type")
    if start_type not in {"static", "dynamic"} or end_type not in {
        "today",
        "yesterday",
        "dynamic",
    }:
        raise InputValidationError(
            f"actual value: {actual_value({'dynamic_start_type': start_type, 'dynamic_end_type': end_type})}; "
            "allowed values: start type static/dynamic and end type today/yesterday/dynamic",
            field="date_range",
        )
    if start_type == "static":
        parse_iso_calendar_date(value.get("start_date"), "segment dynamic start date")
    else:
        validate_segment_day_offset(value.get("start_date_input"), "start")
    if end_type == "dynamic":
        validate_segment_day_offset(value.get("end_date_input"), "end")


def validate_segment_day_offset(value: Any, label: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 3_650:
        raise InputValidationError(f"actual value: {actual_value(value)}; allowed range: an integer from 0 through 3650", field=f"date_range.{label}_date_input")


def validate_segment_logic(value: Any, label: str) -> None:
    if value not in {"AND", "OR"}:
        raise InputValidationError(f"actual value: {actual_value(value)}; allowed values: \"AND\", \"OR\"", field=f"{label}.cond_logic")
