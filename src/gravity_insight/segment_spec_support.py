"""Validation and normalization helpers for compact Segment Rule Spec v2."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

from .actionable_error_values import actual_value, allowed_values
from .analysis_execution_support import (
    SEGMENT_EVENT_RULE_GAP_CODE,
    SEGMENT_EVENT_RULE_GAP_MESSAGE,
    SEGMENT_EVENT_RULE_GAP_NEXT_ACTION,
    reject_unsupported_segment_event,
)
from ._field_policy_segment import SEGMENT_QUICK_RANGES, SEGMENT_RULE_OPERATORS
from ._field_policy_shared import (
    ANALYSIS_CONDITION_OPERATORS,
    ANALYSIS_TARGET_METHODS,
    reject_sensitive_analysis_field,
)
from .errors import InputValidationError


_SOURCE_TYPES = {
    "event": "event",
    "user": "user",
    "segment": "user_segment",
}
_CONDITION_FIELDS = frozenset(
    {
        "field",
        "source",
        "operator",
        "values",
        "dimension_table",
        "segment_type",
        "version_id",
        "date_type",
        "date_unit",
        "date_relative_type",
        "date_relative_unit",
        "date_relative_left",
        "date_relative_right",
    }
)


def mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise InputValidationError(
            f"actual value: {actual_value(value)}; allowed type: object", field=field
        )
    return value


def sequence(value: Any, field: str, maximum: int) -> list[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise InputValidationError(
            f"actual value: {actual_value(value)}; allowed type: array", field=field
        )
    result = list(value)
    if len(result) > maximum:
        raise InputValidationError(
            f"actual value: {len(result)} items; allowed maximum: {maximum} items",
            field=field,
        )
    return result


def reject_keys(
    value: Mapping[str, Any],
    allowed: set[str] | frozenset[str],
    field: str,
) -> None:
    unknown = sorted(str(key) for key in set(value) - set(allowed))
    if unknown:
        raise InputValidationError(
            f"actual value: {actual_value(unknown)}; allowed fields: "
            f"{allowed_values(allowed)}",
            field=field,
        )


def text(
    value: Any,
    field: str,
    *,
    maximum: int,
    allow_empty: bool = False,
) -> str:
    if not isinstance(value, str) or len(value) > maximum or "\x00" in value:
        raise InputValidationError(
            f"actual value: {actual_value(value)}; allowed value: a string of at most "
            f"{maximum} characters without NUL",
            field=field,
        )
    if not allow_empty and not value.strip():
        raise InputValidationError(
            f"actual value: {actual_value(value)}; allowed value: a non-empty string",
            field=field,
        )
    return value


def logic(value: Any, field: str) -> str:
    if value not in {"AND", "OR"}:
        raise InputValidationError(
            f"actual value: {actual_value(value)}; allowed values: "
            f"{allowed_values({'AND', 'OR'})}",
            field=field,
        )
    return str(value)


def ordered_dates(start: Any, end: Any, field: str) -> tuple[str, str | None]:
    parsed_start = calendar_date(start, f"{field}.start")
    parsed_end = calendar_date(end, f"{field}.end") if end is not None else None
    if parsed_end is not None and parsed_start > parsed_end:
        raise InputValidationError(
            f"actual value: {actual_value({'start': start, 'end': end})}; allowed "
            "range: start must be on or before end",
            field=field,
        )
    return parsed_start.isoformat(), parsed_end.isoformat() if parsed_end else None


def calendar_date(value: Any, field: str) -> date:
    if not isinstance(value, str):
        raise InputValidationError(
            f"actual value: {actual_value(value)}; allowed format: ISO date", field=field
        )
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise InputValidationError(
            f"actual value: {actual_value(value)}; allowed format: ISO date", field=field
        ) from exc


def compile_rule_set(value: Any, field: str, *, events: bool) -> dict[str, Any]:
    source = mapping(value, field)
    reject_keys(source, {"logic", "groups"}, field)
    groups = sequence(source.get("groups"), f"{field}.groups", 50)
    compiler = compile_event_group if events else compile_property_group
    return {
        "cond_logic": logic(source.get("logic", "AND"), f"{field}.logic"),
        "groups": [
            compiler(item, f"{field}.groups[{index}]")
            for index, item in enumerate(groups)
        ],
    }


def compile_property_group(value: Any, field: str) -> dict[str, Any]:
    source = mapping(value, field)
    reject_keys(source, {"logic", "rules"}, field)
    rules = sequence(source.get("rules"), f"{field}.rules", 100)
    return {
        "cond_logic": logic(source.get("logic", "AND"), f"{field}.logic"),
        "conditions": [
            compile_condition(item, f"{field}.rules[{index}]")
            for index, item in enumerate(rules)
        ],
    }


def compile_event_group(value: Any, field: str) -> dict[str, Any]:
    source = mapping(value, field)
    reject_keys(source, {"logic", "rules"}, field)
    rules = sequence(source.get("rules"), f"{field}.rules", 100)
    return {
        "cond_logic": logic(source.get("logic", "AND"), f"{field}.logic"),
        "conditions": [
            compile_event(item, f"{field}.rules[{index}]")
            for index, item in enumerate(rules)
        ],
    }


def compile_condition(value: Any, field: str) -> dict[str, Any]:
    source = mapping(value, field)
    reject_keys(source, _CONDITION_FIELDS, field)
    name = text(source.get("field"), f"{field}.field", maximum=256)
    reject_sensitive_analysis_field(name)
    source_name = source.get("source")
    if source_name not in _SOURCE_TYPES:
        raise InputValidationError(
            f"actual value: {actual_value(source_name)}; allowed values: "
            f"{allowed_values(_SOURCE_TYPES)}",
            field=f"{field}.source",
        )
    operator = source.get("operator")
    if operator not in SEGMENT_RULE_OPERATORS:
        raise InputValidationError(
            f"actual value: {actual_value(operator)}; allowed values: "
            f"{allowed_values(SEGMENT_RULE_OPERATORS, discovery_action='gravity analysis segment evaluate --spec-schema')}",
            field=f"{field}.operator",
        )
    result: dict[str, Any] = {
        "field": name,
        "type": _SOURCE_TYPES[str(source_name)],
        "operator": operator,
        "value": scalar_values(source.get("values", []), f"{field}.values"),
    }
    _copy_condition_controls(source, result, field)
    _validate_segment_version(result, field)
    return result


def _copy_condition_controls(
    source: Mapping[str, Any], result: dict[str, Any], field: str
) -> None:
    mappings = {
        "dimension_table": "dim_using_table_name",
        "segment_type": "segment_type",
        "version_id": "version_id",
        "date_type": "date_type",
        "date_unit": "date_unit",
        "date_relative_type": "date_relative_type",
        "date_relative_unit": "date_relative_unit",
        "date_relative_left": "date_relative_left",
        "date_relative_right": "date_relative_right",
    }
    for source_key, target_key in mappings.items():
        if source_key in source:
            value = source[source_key]
            if source_key == "dimension_table":
                value = text(value, f"{field}.dimension_table", maximum=256)
            result[target_key] = value


def _validate_segment_version(result: Mapping[str, Any], field: str) -> None:
    segment_type = result.get("segment_type")
    version_id = result.get("version_id")
    if result.get("type") != "user_segment":
        if segment_type is not None or version_id is not None:
            raise InputValidationError(
                f"{field} version controls require source segment", field=field, next_action="Correct that field to a documented value and retry."
            )
        return
    if segment_type not in {None, "LATEST", "DYNAMIC_MATCHING", "FIXED_VERSION"}:
        raise InputValidationError(
            f"actual value: {actual_value(segment_type)}; allowed values: "
            f"{allowed_values({None, 'LATEST', 'DYNAMIC_MATCHING', 'FIXED_VERSION'})}",
            field=f"{field}.segment_type",
        )
    if segment_type == "FIXED_VERSION":
        if not isinstance(version_id, (str, int)) or isinstance(version_id, bool):
            raise InputValidationError(
                f"actual value: {actual_value(version_id)}; allowed value: a string "
                "or integer version id",
                field=f"{field}.version_id",
            )
    elif version_id is not None:
        raise InputValidationError(
            f"actual value: {actual_value(version_id)}; allowed alternative: remove "
            "version_id or set segment_type to FIXED_VERSION",
            field=f"{field}.version_id",
        )


def compile_event(value: Any, field: str) -> dict[str, Any]:
    source = mapping(value, field)
    reject_keys(
        source,
        {
            "event",
            "did",
            "target",
            "did_condition",
            "date_range",
            "logic",
            "conditions",
        },
        field,
    )
    did = source.get("did")
    if not isinstance(did, bool):
        raise InputValidationError(
            f"actual value: {actual_value(did)}; allowed values: true, false",
            field=f"{field}.did",
        )
    conditions = sequence(source.get("conditions", []), f"{field}.conditions", 100)
    event_name = text(source.get("event"), f"{field}.event", maximum=256)
    reject_unsupported_segment_event(event_name, f"{field}.event")
    return {
        "event_name": event_name,
        "did": did,
        "target": compile_target(source.get("target"), f"{field}.target"),
        "did_condition": compile_did_condition(
            source.get("did_condition"), f"{field}.did_condition"
        ),
        "date_range": compile_event_date_range(
            source.get("date_range"), f"{field}.date_range"
        ),
        "cond_logic": logic(source.get("logic", "AND"), f"{field}.logic"),
        "conditions": [
            compile_condition(item, f"{field}.conditions[{index}]")
            for index, item in enumerate(conditions)
        ],
    }


def compile_target(value: Any, field: str) -> dict[str, Any]:
    source = mapping(value, field)
    reject_keys(source, {"field", "aggregation", "dimension_table"}, field)
    name = text(source.get("field"), f"{field}.field", maximum=256)
    reject_sensitive_analysis_field(name)
    aggregation = source.get("aggregation")
    if aggregation not in ANALYSIS_TARGET_METHODS:
        raise InputValidationError(
            f"actual value: {actual_value(aggregation)}; allowed values: "
            f"{allowed_values(ANALYSIS_TARGET_METHODS)}",
            field=f"{field}.aggregation",
        )
    result: dict[str, Any] = {"field": name, "name": aggregation}
    if "dimension_table" in source:
        result["dim_using_table_name"] = text(
            source["dimension_table"], f"{field}.dimension_table", maximum=256
        )
    return result


def compile_did_condition(value: Any, field: str) -> dict[str, Any]:
    source = mapping(value, field)
    reject_keys(source, {"operator", "values"}, field)
    operator = source.get("operator")
    if operator not in ANALYSIS_CONDITION_OPERATORS:
        raise InputValidationError(
            f"actual value: {actual_value(operator)}; allowed values: "
            f"{allowed_values(ANALYSIS_CONDITION_OPERATORS, discovery_action='gravity analysis segment evaluate --spec-schema')}",
            field=f"{field}.operator",
        )
    return {
        "operator": operator,
        "value": scalar_values(source.get("values", []), f"{field}.values"),
    }


def compile_event_date_range(value: Any, field: str) -> dict[str, Any]:
    source = mapping(value, field)
    kind = source.get("type")
    if kind == "static":
        reject_keys(source, {"type", "start", "end"}, field)
        start, end = ordered_dates(source.get("start"), source.get("end"), field)
        return {"date_type": "static", "date": [start, end]}
    if kind == "quick":
        reject_keys(source, {"type", "range"}, field)
        selected = source.get("range")
        if selected not in SEGMENT_QUICK_RANGES:
            raise InputValidationError(
                f"actual value: {actual_value(selected)}; allowed values: "
                f"{allowed_values(SEGMENT_QUICK_RANGES)}",
                field=f"{field}.range",
            )
        return {"date_type": "dynamic", "quick_select": selected}
    if kind == "dynamic":
        return _compile_dynamic_range(source, field)
    raise InputValidationError(
        f"actual value: {actual_value(kind)}; allowed values: "
        f"{allowed_values({'fixed', 'quick', 'dynamic'})}",
        field=f"{field}.type",
    )


def _compile_dynamic_range(
    source: Mapping[str, Any], field: str
) -> dict[str, Any]:
    reject_keys(
        source,
        {
            "type",
            "start_type",
            "end_type",
            "start",
            "start_days_ago",
            "end_days_ago",
        },
        field,
    )
    start_type = source.get("start_type")
    end_type = source.get("end_type")
    if start_type not in {"static", "dynamic"}:
        raise InputValidationError(
            f"actual value: {actual_value(start_type)}; allowed values: "
            f"{allowed_values({'static', 'dynamic'})}",
            field=f"{field}.start_type",
        )
    if end_type not in {"today", "yesterday", "dynamic"}:
        raise InputValidationError(
            f"actual value: {actual_value(end_type)}; allowed values: "
            f"{allowed_values({'today', 'yesterday', 'dynamic'})}",
            field=f"{field}.end_type",
        )
    result: dict[str, Any] = {
        "date_type": "dynamic",
        "dynamic_start_type": start_type,
        "dynamic_end_type": end_type,
    }
    if start_type == "static":
        result["start_date"] = calendar_date(
            source.get("start"), f"{field}.start"
        ).isoformat()
        if "start_days_ago" in source:
            raise InputValidationError(
                f"actual value: {actual_value(source.get('start_days_ago'))}; allowed "
                "alternative: remove start_days_ago or set start_type to dynamic",
                field=f"{field}.start_days_ago",
            )
    else:
        result["start_date_input"] = day_offset(
            source.get("start_days_ago"), f"{field}.start_days_ago"
        )
        if "start" in source:
            raise InputValidationError(
                f"actual value: {actual_value(source.get('start'))}; allowed "
                "alternative: remove start or set start_type to static",
                field=f"{field}.start",
            )
    if end_type == "dynamic":
        result["end_date_input"] = day_offset(
            source.get("end_days_ago"), f"{field}.end_days_ago"
        )
    elif "end_days_ago" in source:
        raise InputValidationError(
            f"actual value: {actual_value(source.get('end_days_ago'))}; allowed "
            "alternative: remove end_days_ago or set end_type to dynamic",
            field=f"{field}.end_days_ago",
        )
    return result


def scalar_values(value: Any, field: str) -> list[Any]:
    result = sequence(value, field, 200)
    for item in result:
        if item is not None and (
            not isinstance(item, (str, int, float, bool))
            or isinstance(item, str)
            and len(item) > 4_096
            or isinstance(item, float)
            and not math.isfinite(item)
        ):
            raise InputValidationError(
                f"{field} must contain scalar values", field=field
            )
    return result


def day_offset(value: Any, field: str) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or not 0 <= value <= 3_650
    ):
        raise InputValidationError(
            f"actual value: {actual_value(value)}; allowed range: integer from 0 "
            "through 3650",
            field=field,
        )
    return value


__all__ = [
    "SEGMENT_EVENT_RULE_GAP_CODE",
    "SEGMENT_EVENT_RULE_GAP_MESSAGE",
    "SEGMENT_EVENT_RULE_GAP_NEXT_ACTION",
    "compile_rule_set",
    "logic",
    "mapping",
    "ordered_dates",
    "reject_keys",
    "text",
]
