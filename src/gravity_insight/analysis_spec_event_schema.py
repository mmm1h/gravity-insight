"""Event-specific compact Analysis schema fragments."""

from __future__ import annotations

from typing import Any, Mapping

from .analysis_spec_schema_support import array_ref, dated_spec, enum, integer
from .analysis_spec_validation import event_input_definitions


def event_schema() -> dict[str, Any]:
    schema = dated_spec(
        "event",
        required=(),
        properties={
            "date_ranges": array_ref("date_range", 1, 10),
            "steps": array_ref("event_query_step", 0, 100),
            "formulas": array_ref("event_formula", 0, 100),
            "global_filters": array_ref("event_global_condition", 0, 100),
            "global_logic": enum("AND", "OR"),
            "user_filters": {"type": "object", "maxProperties": 100},
            "calculate_y": {"type": "boolean", "default": False},
            "calculate_layer_y": {"type": "boolean", "default": False},
            "return_hierarchy_list": {"type": "boolean", "default": False},
            "page_size": integer(1, 10_000),
            "aggregate": {"$ref": "#/definitions/aggregate"},
        },
        notes={
            "date_windows": "Use either start/end or 1 through 10 date_ranges.",
            "row_limit": (
                "page_size is an upstream row limit for supported Event shapes; "
                "it is not pagination and never proves completeness"
            ),
        },
    )
    schema["allOf"] = [
        {
            "oneOf": [
                {"required": ["start", "end"], "not": {"required": ["date_ranges"]}},
                {
                    "required": ["date_ranges"],
                    "not": {"anyOf": [{"required": ["start"]}, {"required": ["end"]}]},
                },
            ]
        },
        {
            "anyOf": [
                {"required": ["steps"], "properties": {"steps": {"minItems": 1}}},
                {
                    "required": ["formulas"],
                    "properties": {"formulas": {"minItems": 1}},
                },
            ]
        },
    ]
    return schema


def event_definitions(definitions: Mapping[str, Any]) -> dict[str, Any]:
    result = event_input_definitions(definitions)
    result["date_range"] = {
        "type": "object",
        "required": ["start", "end"],
        "additionalProperties": False,
        "properties": {
            "start": {"type": "string", "format": "date"},
            "end": {"type": "string", "format": "date"},
        },
    }
    result["event_formula"] = {
        "type": "object",
        "required": ["name", "formula", "steps"],
        "additionalProperties": False,
        "properties": {
            "name": {"type": "string", "minLength": 1, "maxLength": 200},
            "formula": {
                "type": "string",
                "minLength": 1,
                "maxLength": 1000,
                "pattern": "^[xX0-9+*/().\\s-]{1,1000}$",
            },
            "steps": array_ref("event_query_step", 1, 100),
            "precision": enum("two_point", "three_point", "four_point"),
        },
    }
    return result


__all__ = ["event_definitions", "event_schema"]
