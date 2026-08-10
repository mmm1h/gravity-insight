"""Segment-rule validators for the Analysis evaluation DSL."""

from __future__ import annotations

from typing import Any, Mapping

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
    if not isinstance(name, str) or not name or len(name) > 128:
        raise InputValidationError(
            "analysis segment name is invalid; request was not sent"
        )
    if not isinstance(remark, str) or len(remark) > 2_000:
        raise InputValidationError(
            "analysis segment remark is invalid; request was not sent"
        )
    if inputs.get("update_type") not in {"Manual", "Routine"}:
        raise InputValidationError(
            "analysis segment update_type is invalid; request was not sent"
        )
    if inputs.get("cond_logic") not in {"AND", "OR"}:
        raise InputValidationError(
            "analysis segment cond_logic is invalid; request was not sent"
        )


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
            "analysis segment date range is reversed; request was not sent"
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
            "analysis segment property groups are invalid; request was not sent"
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
            "analysis segment property conditions are invalid; request was not sent"
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
            "analysis segment event groups are invalid; request was not sent"
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
            "analysis segment events are invalid; request was not sent"
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
            "analysis segment event_name is invalid; request was not sent"
        )
    references.events.add(event_name)
    if not isinstance(value.get("did"), bool):
        raise InputValidationError(
            "analysis segment event did flag is invalid; request was not sent"
        )
    _validate_segment_event_target(value.get("target"), references)
    _validate_did_condition(value.get("did_condition"))
    validate_segment_event_date_range(value.get("date_range"))
    validate_segment_logic(value.get("cond_logic"), "event")
    conditions = value.get("conditions")
    if not isinstance(conditions, (list, tuple)) or len(conditions) > 100:
        raise InputValidationError(
            "analysis segment event conditions are invalid; request was not sent"
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
    if value.get("operator") not in SEGMENT_RULE_OPERATORS:
        raise InputValidationError(
            "analysis segment did operator is invalid; request was not sent"
        )
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
            "analysis segment condition field is invalid; request was not sent"
        )
    reject_sensitive_analysis_field(field)
    if value.get("operator") not in SEGMENT_RULE_OPERATORS:
        raise InputValidationError(
            "analysis segment condition operator is invalid; request was not sent"
        )
    validate_scalar_list(value.get("value"), "analysis segment condition value")
    is_segment = _add_segment_condition_reference(value, field, references)
    _add_segment_condition_dimension(value, field, is_segment, references)
    validate_segment_condition_date_controls(value)


def _add_segment_condition_reference(
    value: Mapping[str, Any], field: str, references: AnalysisReferences
) -> bool:
    field_type = value.get("type")
    segment_type = value.get("segment_type")
    version_id = value.get("version_id")
    is_segment = field_type == "user_segment" or segment_type not in {None, ""}
    if is_segment:
        if field_type != "user_segment":
            raise InputValidationError(
                "analysis segment condition type is invalid; request was not sent"
            )
        effective_type = _validate_segment_version(segment_type, version_id)
        references.segment_fields.add((field, effective_type, str(version_id or "")))
    elif field_type in ANALYSIS_EVENT_TYPES:
        references.event_fields.add(field)
    elif field_type in ANALYSIS_USER_TYPES:
        references.user_fields.add(field)
    else:
        raise InputValidationError(
            "analysis segment condition type is invalid; request was not sent"
        )
    return is_segment


def _validate_segment_version(segment_type: Any, version_id: Any) -> str:
    if segment_type not in {None, "", "LATEST", "DYNAMIC_MATCHING", "FIXED_VERSION"}:
        raise InputValidationError(
            "analysis segment condition version mode is invalid; request was not sent"
        )
    effective_type = str(segment_type or "LATEST")
    if effective_type == "FIXED_VERSION":
        if not isinstance(version_id, (str, int)) or isinstance(version_id, bool):
            raise InputValidationError(
                "analysis fixed segment version is invalid; request was not sent"
            )
    elif version_id not in {None, ""}:
        raise InputValidationError(
            "analysis segment version requires FIXED_VERSION; request was not sent"
        )
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
            "analysis segment dimension table is invalid; request was not sent"
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
            raise InputValidationError(
                f"analysis segment {key} is invalid; request was not sent"
            )


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
        raise InputValidationError(
            "analysis segment event date_type is invalid; request was not sent"
        )
    quick_select = value.get("quick_select")
    if quick_select not in {None, ""}:
        if quick_select not in SEGMENT_QUICK_RANGES:
            raise InputValidationError(
                "analysis segment quick date range is invalid; request was not sent"
            )
        return
    if date_type == "static":
        _validate_static_event_date_range(value.get("date"))
        return
    _validate_dynamic_event_date_range(value)


def _validate_static_event_date_range(value: Any) -> None:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise InputValidationError(
            "analysis segment static date range is invalid; request was not sent"
        )
    start = parse_iso_calendar_date(value[0], "segment event start date")
    end = parse_iso_calendar_date(value[1], "segment event end date")
    if start > end:
        raise InputValidationError(
            "analysis segment event date range is reversed; request was not sent"
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
            "analysis segment dynamic date range is invalid; request was not sent"
        )
    if start_type == "static":
        parse_iso_calendar_date(value.get("start_date"), "segment dynamic start date")
    else:
        validate_segment_day_offset(value.get("start_date_input"), "start")
    if end_type == "dynamic":
        validate_segment_day_offset(value.get("end_date_input"), "end")


def validate_segment_day_offset(value: Any, label: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 3_650:
        raise InputValidationError(
            f"analysis segment {label} day offset is invalid; request was not sent"
        )


def validate_segment_logic(value: Any, label: str) -> None:
    if value not in {"AND", "OR"}:
        raise InputValidationError(
            f"analysis segment {label} logic is invalid; request was not sent"
        )
