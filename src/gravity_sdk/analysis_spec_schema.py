"""Machine-readable contract for compact Analysis Query Spec v1."""

from __future__ import annotations

from typing import Any, Mapping

from ._field_policy_shared import (
    ANALYSIS_CONTROL_ID_RE,
    ANALYSIS_CONDITION_OPERATORS,
    ANALYSIS_EVENT_TYPES,
    ANALYSIS_PROPERTY_GROUP_OPERATORS,
    ANALYSIS_QUERY_ID_RE,
    ANALYSIS_TARGET_METHODS,
    ANALYSIS_TIME_GROUPS,
    ANALYSIS_USER_TYPES,
)


SPEC_SCHEMA_VERSION = "gravity-insight.analysis-query-spec.v1"
ANALYSIS_SPEC_KINDS = frozenset(
    {"event", "funnel", "retention", "property", "scatter"}
)


def analysis_query_spec_schema() -> dict[str, Any]:
    """Return the complete offline contract used by CLI and Agent discovery."""

    return {
        "operation_id": "analysis.query.spec_schema",
        "schema_version": SPEC_SCHEMA_VERSION,
        "ok": True,
        "status": "success",
        "offline": True,
        "network_called": False,
        "kinds": sorted(ANALYSIS_SPEC_KINDS),
        "definitions": _definitions(),
        "kind_schemas": _kind_schemas(),
        "handoff": {
            "command": (
                "gravity analysis query --kind <kind> --spec "
                "<json-object-or-file> --app <workspace-alias-or-id>"
            ),
            "dry_run": "append --dry-run; filter values are redacted from stdout",
            "natural_language_auto_execute": False,
        },
    }


def _kind_schemas() -> dict[str, Any]:
    return {
            "event": _dated_spec(
                required=("start", "end", "steps"),
                properties={
                    "steps": _array_ref("event_step", 1, 50),
                    "global_filters": _array_ref("condition", 0, 100),
                    "global_logic": _enum("AND", "OR"),
                    "calculate_layer_y": {"type": "boolean", "default": False},
                    "return_hierarchy_list": {"type": "boolean", "default": False},
                    "aggregate": {"$ref": "#/definitions/aggregate"},
                },
            ),
            "funnel": _dated_spec(
                required=("start", "end", "steps", "window"),
                properties={
                    "steps": _array_ref("event_step", 2, 20),
                    "global_filters": _array_ref("condition", 0, 100),
                    "global_logic": _enum("AND", "OR"),
                    "window": {"$ref": "#/definitions/funnel_window"},
                    "calculate_each_day": {"type": "boolean", "default": False},
                },
                notes={
                    "returns_conversion_rate": False,
                    "count_meaning": (
                        "each step count is the ordered subset that completed "
                        "this step and every earlier step"
                    ),
                    "rate_denominators": {
                        "previous_step": "step_n / step_{n-1}",
                        "first_step": "step_n / step_1",
                    },
                    "denominator_required": (
                        "three or more steps make the two denominators differ; "
                        "the SDK does not choose one or insert a rate"
                    ),
                    "window_funnel_mode": 4,
                },
            ),
            "retention": _dated_spec(
                required=(
                    "start",
                    "end",
                    "steps",
                    "offset",
                    "period_calc_method",
                    "custom_before_method",
                    "total_calc_type",
                    "week_first_day",
                ),
                properties={
                    "steps": _array_ref("event_step", 2, 2),
                    "offset": _integer(1, 365),
                    "period_calc_method": _enum("SUM", "WEIGHTED_AVG"),
                    "custom_before_method": _enum("SUM", "WEIGHTED_AVG"),
                    "total_calc_type": _enum("DAY", "WEEK", "MONTH"),
                    "week_first_day": _integer(1, 7),
                    "query_item_before_after": {
                        "$ref": "#/definitions/retention_before_after",
                        "default": {},
                    },
                    **_shared_filter_properties(),
                },
            ),
            "property": _property_schema(),
            "scatter": _dated_spec(
                required=("start", "end", "steps"),
                properties={
                    "steps": _array_ref("event_step", 1, 1),
                    "zone": {"$ref": "#/definitions/scatter_zone"},
                },
            ),
    }


def _definitions() -> dict[str, Any]:
    return {
        "condition": _condition_definition(),
        **_target_definitions(),
        **_flow_definitions(),
        **_retention_definitions(),
        "aggregate": _aggregate_definition(),
    }


def _condition_definition() -> dict[str, Any]:
    return {
            "type": "object",
            "required": ["operator", "field", "type"],
            "additionalProperties": False,
            "properties": {
                "operator": {"type": "string", "enum": sorted(ANALYSIS_CONDITION_OPERATORS)},
                "field": _bounded_string(),
                "type": {
                    "type": "string",
                    "enum": sorted(ANALYSIS_EVENT_TYPES | ANALYSIS_USER_TYPES | {"user_segment"}),
                },
                "value": {"type": "array", "maxItems": 200, "items": _scalar()},
                "by_list_index": {"type": "boolean"},
                "list_index_val": {"type": "integer"},
                "segment_type": _enum("LATEST", "DYNAMIC_MATCHING", "FIXED_VERSION"),
                "version_id": {"type": ["string", "integer"]},
                "dim_using_table_name": _bounded_string(),
            },
        }


def _target_definitions() -> dict[str, Any]:
    return {
        "metric": {
            "type": "object",
            "required": ["field", "aggregation"],
            "additionalProperties": False,
            "properties": {
                "field": _bounded_string(),
                "aggregation": {
                    "oneOf": [
                        {"enum": sorted(ANALYSIS_TARGET_METHODS)},
                        {
                            "type": "string",
                            "pattern": "^Quantile(?:_(?:[1-9]|[1-9][0-9]|100))?$",
                        },
                    ]
                },
                "dimension_table": _bounded_string(),
                "quantile": {"type": "number", "exclusiveMinimum": 0, "maximum": 100},
            },
        },
        "property_target": {
            "type": "object",
            "required": ["field", "aggregation", "data_type"],
            "additionalProperties": False,
            "properties": {
                "field": _bounded_string(),
                "aggregation": {"type": "string", "enum": sorted(ANALYSIS_TARGET_METHODS)},
                "data_type": _enum("STRING", "INT", "FLOAT", "BOOL", "DATE", "DATETIME", "LIST"),
                "source": {"type": "string", "enum": sorted(ANALYSIS_USER_TYPES)},
                "label": {"type": "string", "maxLength": 256},
                "dimension_table": _bounded_string(),
            },
        },
    }


def _flow_definitions() -> dict[str, Any]:
    return {
        "event_step": {
            "type": "object",
            "required": ["event", "metric"],
            "additionalProperties": False,
            "properties": {
                "event": _bounded_string(),
                "metric": {"$ref": "#/definitions/metric"},
                "label": {"type": "string", "maxLength": 256},
                "conditions": _array_ref("condition", 0, 100),
                "condition_logic": _enum("AND", "OR"),
            },
        },
        "group_by": {
            "type": "object",
            "required": ["field", "source"],
            "additionalProperties": False,
            "properties": {
                "field": _bounded_string(),
                "source": _enum("event", "user", "segment"),
                "bucket": {
                    "type": "string",
                    "enum": sorted(ANALYSIS_PROPERTY_GROUP_OPERATORS),
                },
                "bucket_values": {"type": "array", "maxItems": 200, "items": _scalar()},
                "segment_type": _enum("LATEST", "DYNAMIC_MATCHING", "FIXED_VERSION"),
                "version_id": {"type": ["string", "integer"]},
                "dimension_table": _bounded_string(),
            },
        },
        "funnel_window": {
            "oneOf": [
                _window_variant("today", 1),
                _window_variant("minute", 60),
                _window_variant("hour", 24),
                _window_variant("day", 30),
            ],
        },
        "scatter_zone": {
            "oneOf": [_simple_zone("default"), _simple_zone("dispersed"), _custom_zone()]
        },
    }


def _retention_definitions() -> dict[str, Any]:
    precision = _enum(
        "two_point", "three_point", "four_point", "percentage", "integer"
    )
    return {
        "retention_target": {
            "type": "object",
            "required": ["name", "field"],
            "additionalProperties": False,
            "properties": {
                "name": {
                    "oneOf": [
                        {"enum": sorted(ANALYSIS_TARGET_METHODS)},
                        {
                            "type": "string",
                            "pattern": "^Quantile(?:_(?:[1-9]|[1-9][0-9]|100))?$",
                        },
                    ]
                },
                "field": _bounded_string(),
                "quantile_level": {
                    "type": "number", "exclusiveMinimum": 0, "maximum": 100
                },
                "dim_using_table_name": _bounded_string(),
            },
        },
        "retention_after_event": _retention_event(False),
        "retention_before_event": _retention_event(True),
        "retention_after_custom": _retention_custom(False),
        "retention_before_custom": _retention_custom(True),
        "retention_before_after": {
            "type": "object",
            "additionalProperties": False,
            "oneOf": [{"maxProperties": 0}, {"required": ["name"]}],
            "properties": {
                "after": {"$ref": "#/definitions/retention_after_event"},
                "after_custom": {"$ref": "#/definitions/retention_after_custom"},
                "before": {"$ref": "#/definitions/retention_before_event"},
                "before_custom": {"$ref": "#/definitions/retention_before_custom"},
                "formula": _enum("+", "-", "*", "/"),
                "decimal_point": precision,
                "before_decimal_point": precision,
                "a_to_b": {"type": "boolean"},
                "name": {"type": "string", "minLength": 1, "maxLength": 20},
            },
        },
    }


def _retention_event(before: bool) -> dict[str, Any]:
    properties = {
        "event_name": _bounded_string(),
        "custom_name": {"type": "string", "maxLength": 256},
        "target": {"$ref": "#/definitions/retention_target"},
        "conditions": _array_ref("condition", 0, 100),
        "cond_logic": _enum("AND", "OR"),
        "prop_to_calc": {"type": "string", "maxLength": 256},
        "prop_to_calc_target": {"type": "string", "maxLength": 256},
    }
    if before:
        properties["customBeforeName"] = {"type": "string", "maxLength": 256}
    return {
        "type": "object",
        "required": ["event_name", "target"],
        "additionalProperties": False,
        "properties": properties,
    }


def _retention_custom(before: bool) -> dict[str, Any]:
    properties = {
        "list": {
            "type": "array",
            "minItems": 1,
            "maxItems": 50,
            "items": {
                "$ref": (
                    "#/definitions/retention_before_event"
                    if before else "#/definitions/retention_after_event"
                )
            },
        },
        "conditions": _array_ref("condition", 0, 100),
        "cond_logic": _enum("AND", "OR"),
        "formula": {
            "type": "string", "minLength": 1, "maxLength": 256,
            "pattern": "^[xX0-9+*/().\\s-]{1,256}$",
        },
    }
    if before:
        properties["customBeforeName"] = {"type": "string", "maxLength": 256}
    return {
        "type": "object",
        "required": ["list", "formula"],
        "additionalProperties": False,
        "properties": properties,
    }


def _property_schema() -> dict[str, Any]:
    return _base_spec(
        required=("property",),
        properties={
            "property": {"$ref": "#/definitions/property_target"},
            "conditions": _array_ref("condition", 0, 100),
            "order_by": {
                "type": "array",
                "maxItems": 20,
                "items": {
                    "type": "object",
                    "required": ["field", "sort"],
                    "additionalProperties": False,
                    "properties": {
                        "field": _bounded_string(),
                        "sort": {"enum": [0, 1, -1, "asc", "desc", "ASC", "DESC"]},
                        "data_type": _enum(
                            "STRING", "INT", "FLOAT", "BOOL", "DATE", "DATETIME", "LIST"
                        ),
                    },
                },
            },
            **_shared_filter_properties(),
        },
    )


def _aggregate_definition() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "to_calc_type": _enum("approximate", "precise"),
            "period_calc_method_map": {
                "type": "object",
                "maxProperties": 50,
                "propertyNames": {"pattern": ANALYSIS_CONTROL_ID_RE.pattern},
                "additionalProperties": {
                    "enum": ["SUM", "WEIGHTED_AVG", "AVG", "MAX", "MIN"]
                },
            },
        },
    }


def _base_spec(*, required: tuple[str, ...], properties: dict[str, Any]) -> dict[str, Any]:
    common = {
        "app": {"type": ["string", "integer"]},
        "query_id": {
            "type": "string",
            "pattern": ANALYSIS_QUERY_ID_RE.pattern,
        },
        "group_by": _array_ref("group_by", 0, 20),
    }
    return {
        "type": "object",
        "required": list(required),
        "additionalProperties": False,
        "properties": {**common, **properties},
    }


def _dated_spec(
    *,
    required: tuple[str, ...],
    properties: dict[str, Any],
    notes: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    spec = _base_spec(
        required=required,
        properties={
            "start": {"type": "string", "format": "date"},
            "end": {"type": "string", "format": "date"},
            "time_grain": {"type": "string", "enum": sorted(ANALYSIS_TIME_GROUPS)},
            **properties,
        },
    )
    if notes:
        spec["notes"] = dict(notes)
    return spec


def _shared_filter_properties() -> dict[str, Any]:
    return {
        "user_filters": {"type": "object"},
        "user_reattribute_filters": {"type": "object"},
        "user_logic": _enum("AND", "OR"),
        "property_conditions": _array_ref("condition", 0, 100),
    }


def _array_ref(name: str, minimum: int, maximum: int) -> dict[str, Any]:
    return {
        "type": "array",
        "minItems": minimum,
        "maxItems": maximum,
        "items": {"$ref": f"#/definitions/{name}"},
    }


def _window_variant(unit: str, maximum: int) -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["unit", "value"],
        "additionalProperties": False,
        "properties": {
            "unit": {"const": unit},
            "value": _integer(1, maximum),
        }
    }


def _simple_zone(zone_type: str) -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["type"],
        "additionalProperties": False,
        "properties": {"type": {"const": zone_type}},
    }


def _custom_zone() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["type", "ranges"],
        "additionalProperties": False,
        "properties": {
            "type": {"const": "custom"},
            "ranges": {
                "type": "array",
                "minItems": 1,
                "maxItems": 100,
                "items": {"type": "number"},
            },
        },
    }


def _scalar() -> dict[str, Any]:
    return {"type": ["string", "number", "boolean", "null"]}


def _bounded_string() -> dict[str, Any]:
    return {"type": "string", "minLength": 1, "maxLength": 256}


def _integer(minimum: int, maximum: int) -> dict[str, Any]:
    return {"type": "integer", "minimum": minimum, "maximum": maximum}


def _enum(*values: str) -> dict[str, Any]:
    return {"type": "string", "enum": list(values)}


__all__ = ["ANALYSIS_SPEC_KINDS", "SPEC_SCHEMA_VERSION", "analysis_query_spec_schema"]
