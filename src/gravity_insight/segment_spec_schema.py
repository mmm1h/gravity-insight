"""Machine-readable contract for compact Segment Rule Spec v2."""

from __future__ import annotations

from typing import Any

from .analysis_execution_support import segment_event_support_metadata
from ._field_policy_segment import SEGMENT_QUICK_RANGES, SEGMENT_RULE_OPERATORS
from ._field_policy_shared import ANALYSIS_CONDITION_OPERATORS, ANALYSIS_TARGET_METHODS
from .domains import ANALYSIS_SEGMENT_OPERATIONS


SEGMENT_SPEC_SCHEMA_VERSION = "gravity-insight.segment-rule-spec.v2"


def segment_rule_spec_schema() -> dict[str, Any]:
    """Return the complete offline schema for the compact segment-rule DSL."""

    return {
        "schema_version": SEGMENT_SPEC_SCHEMA_VERSION,
        "ok": True,
        "status": "success",
        "offline": True,
        "network_called": False,
        "operation_id": ANALYSIS_SEGMENT_OPERATIONS["evaluate"],
        "spec_schema": _spec_schema(),
        "definitions": _definitions(),
        "event_support": segment_event_support_metadata(),
        "handoff": {
            "natural_language_auto_execute": False,
            "metadata_validation": "delegate the compiled input to client.validate",
        },
    }


def _spec_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["name", "start"],
        "additionalProperties": False,
        "properties": {
            "name": _string(20),
            "remark": {"type": "string", "maxLength": 2_000},
            "update_type": _enum("Manual", "Routine"),
            "start": {"type": "string", "format": "date"},
            "end": {"type": ["string", "null"], "format": "date"},
            "logic": _enum("AND", "OR"),
            "property_rules": {"$ref": "#/definitions/property_rule_set"},
            "event_rules": {"$ref": "#/definitions/event_rule_set"},
        },
    }


def _definitions() -> dict[str, Any]:
    return {
        "condition": _condition(),
        "event_target": _event_target(),
        "did_condition": _did_condition(),
        "event_date_range": _event_date_range(),
        "event_rule": _event_rule(),
        "property_group": _group("condition"),
        "event_group": _group("event_rule"),
        "property_rule_set": _rule_set("property_group"),
        "event_rule_set": _rule_set("event_group"),
    }


def _condition() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["field", "source", "operator"],
        "additionalProperties": False,
        "properties": {
            "field": _string(256),
            "source": _enum("event", "user", "segment"),
            "operator": {
                "type": "string",
                "enum": sorted(SEGMENT_RULE_OPERATORS),
            },
            "values": _scalar_array(200),
            "dimension_table": _string(256),
            "segment_type": _enum("LATEST", "DYNAMIC_MATCHING", "FIXED_VERSION"),
            "version_id": {"type": ["string", "integer"]},
            "date_type": _enum("past", "future"),
            "date_unit": _enum("within", "outside"),
            "date_relative_type": _enum("range", "day", "week", "month"),
            "date_relative_unit": _enum("minute", "hour", "day", "week", "month"),
            "date_relative_left": _enum("past", "future"),
            "date_relative_right": _enum("past", "future"),
        },
        "oneOf": [_segment_condition(), _property_condition()],
    }


def _segment_condition() -> dict[str, Any]:
    return {
        "properties": {
            "source": {"const": "segment"},
            "operator": {"const": "TRUE"},
            "values": {"type": "array", "maxItems": 0},
        },
        "allOf": [
            {
                "if": {
                    "required": ["segment_type"],
                    "properties": {"segment_type": {"const": "FIXED_VERSION"}},
                },
                "then": {"required": ["version_id"]},
                "else": {"not": {"required": ["version_id"]}},
            }
        ],
    }


def _property_condition() -> dict[str, Any]:
    return {
        "properties": {"source": _enum("event", "user")},
        "not": {
            "anyOf": [
                {"required": ["segment_type"]},
                {"required": ["version_id"]},
            ]
        },
    }


def _event_target() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["field", "aggregation"],
        "additionalProperties": False,
        "properties": {
            "field": _string(256),
            "aggregation": {"type": "string", "enum": sorted(ANALYSIS_TARGET_METHODS)},
            "dimension_table": _string(256),
        },
    }


def _did_condition() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["operator"],
        "additionalProperties": False,
        "properties": {
            "operator": {
                "type": "string",
                "enum": sorted(ANALYSIS_CONDITION_OPERATORS),
            },
            "values": _scalar_array(200),
        },
    }


def _event_rule() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["event", "did", "target", "did_condition", "date_range"],
        "additionalProperties": False,
        "properties": {
            "event": _string(256),
            "did": {"type": "boolean"},
            "target": {"$ref": "#/definitions/event_target"},
            "did_condition": {"$ref": "#/definitions/did_condition"},
            "date_range": {"$ref": "#/definitions/event_date_range"},
            "logic": _enum("AND", "OR"),
            "conditions": {
                "type": "array",
                "maxItems": 100,
                "items": {"$ref": "#/definitions/condition"},
            },
        },
    }


def _event_date_range() -> dict[str, Any]:
    return {
        "oneOf": [
            {
                "type": "object",
                "required": ["type", "start", "end"],
                "additionalProperties": False,
                "properties": {
                    "type": {"const": "static"},
                    "start": {"type": "string", "format": "date"},
                    "end": {"type": "string", "format": "date"},
                },
            },
            {
                "type": "object",
                "required": ["type", "range"],
                "additionalProperties": False,
                "properties": {
                    "type": {"const": "quick"},
                    "range": {"type": "string", "enum": sorted(SEGMENT_QUICK_RANGES)},
                },
            },
            {
                "type": "object",
                "required": ["type", "start_type", "end_type"],
                "additionalProperties": False,
                "properties": {
                    "type": {"const": "dynamic"},
                    "start_type": _enum("static", "dynamic"),
                    "end_type": _enum("today", "yesterday", "dynamic"),
                    "start": {"type": "string", "format": "date"},
                    "start_days_ago": {"type": "integer", "minimum": 0, "maximum": 3_650},
                    "end_days_ago": {"type": "integer", "minimum": 0, "maximum": 3_650},
                },
                "allOf": [
                    {
                        "if": {
                            "required": ["start_type"],
                            "properties": {"start_type": {"const": "static"}},
                        },
                        "then": {
                            "required": ["start"],
                            "not": {"required": ["start_days_ago"]},
                        },
                        "else": {
                            "required": ["start_days_ago"],
                            "not": {"required": ["start"]},
                        },
                    },
                    {
                        "if": {
                            "required": ["end_type"],
                            "properties": {"end_type": {"const": "dynamic"}},
                        },
                        "then": {"required": ["end_days_ago"]},
                        "else": {"not": {"required": ["end_days_ago"]}},
                    },
                ],
            },
        ]
    }


def _group(item: str) -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["rules"],
        "additionalProperties": False,
        "properties": {
            "logic": _enum("AND", "OR"),
            "rules": {
                "type": "array",
                "maxItems": 100,
                "items": {"$ref": f"#/definitions/{item}"},
            },
        },
    }


def _rule_set(group: str) -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["groups"],
        "additionalProperties": False,
        "properties": {
            "logic": _enum("AND", "OR"),
            "groups": {
                "type": "array",
                "maxItems": 50,
                "items": {"$ref": f"#/definitions/{group}"},
            },
        },
    }


def _scalar_array(maximum: int) -> dict[str, Any]:
    return {
        "type": "array",
        "maxItems": maximum,
        "items": {"type": ["string", "number", "boolean", "null"]},
    }


def _string(maximum: int) -> dict[str, Any]:
    return {"type": "string", "minLength": 1, "maxLength": maximum}


def _enum(*values: str) -> dict[str, Any]:
    return {"type": "string", "enum": list(values)}


__all__ = ["SEGMENT_SPEC_SCHEMA_VERSION", "segment_rule_spec_schema"]
