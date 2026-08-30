"""Closed JSON Schema 2020-12 contracts for the pilot Tool surface."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from functools import lru_cache
from typing import Any

from ..compiler import ContractError, JsonSchemaValidator


JSON_SCHEMA_VERSION = "https://json-schema.org/draft/2020-12/schema"
MAX_OUTPUT_BYTES = 100_000
_OBJECT = {"type": "object", "additionalProperties": True}
_OUTPUT_BUDGET = {
    "type": "integer",
    "minimum": 1_024,
    "maximum": MAX_OUTPUT_BYTES,
}


class MCPInputError(ValueError):
    """A known Tool received arguments outside its published contract."""


def _object_schema(
    properties: Mapping[str, Any],
    *,
    required: tuple[str, ...] = (),
) -> dict[str, Any]:
    return {
        "$schema": JSON_SCHEMA_VERSION,
        "type": "object",
        "properties": dict(properties),
        "required": list(required),
        "additionalProperties": False,
    }


INPUT_SCHEMAS: dict[str, dict[str, Any]] = {
    "gravity.inspect": {
        "$schema": JSON_SCHEMA_VERSION,
        "oneOf": [
            _object_schema({"kind": {"const": "server"}}, required=("kind",)),
            _object_schema(
                {
                    "kind": {
                        "const": "journey",
                        "description": "Select Journey for a registered business task and its acceptance contract, not an installed Skill workflow package.",
                    },
                    "identifier": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 256,
                        "description": "Exact registered Journey ID; omit only to list Journey metadata.",
                    },
                },
                required=("kind",),
            ),
            _object_schema(
                {
                    "kind": {
                        "const": "skill",
                        "description": "Select Skill for an installed versioned workflow or method package, not a Journey task/readiness contract.",
                    },
                    "identifier": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 512,
                        "description": "Exact installed Skill URI or ID; omit only to list Skill metadata.",
                    },
                },
                required=("kind",),
            ),
        ],
    },
    "gravity.journey_can_run": _object_schema(
        {
            "journey_id": {"type": "string", "minLength": 1, "maxLength": 256},
            "inputs": _OBJECT,
            "max_output_bytes": _OUTPUT_BUDGET,
        },
        required=("journey_id",),
    ),
    "gravity.capability_describe": _object_schema(
        {
            "identity_kind": {
                "type": "string",
                "enum": ["operation", "product", "composite"],
                "description": "Exact same-layer identity: operation is one atomic wire contract; product is one governed question-level capability; composite is one bounded multi-component capability. Do not substitute or infer across layers.",
            },
            "selector": {
                "type": "string",
                "minLength": 1,
                "maxLength": 512,
                "description": "Exact selector owned by the identity_kind layer; it is not a Journey ID or Skill ID.",
            },
            "max_output_bytes": _OUTPUT_BUDGET,
        },
        required=("identity_kind", "selector"),
    ),
    "gravity.execute": _object_schema(
        {
            "journey_id": {"type": "string", "minLength": 1, "maxLength": 256},
            "inputs": _OBJECT,
            "max_output_bytes": _OUTPUT_BUDGET,
        },
        required=("journey_id", "inputs"),
    ),
    "gravity.export": _object_schema(
        {
            "analysis_result": _OBJECT,
            "format": {"type": "string", "enum": ["json", "markdown"]},
            "destination": {"type": "string", "minLength": 1, "maxLength": 2_048},
            "confirm": {"type": "boolean", "const": True},
            "max_output_bytes": _OUTPUT_BUDGET,
        },
        required=("analysis_result", "format", "destination", "confirm"),
    ),
    "gravity.context_pack": _object_schema(
        {
            "root": {"type": "string", "minLength": 1, "maxLength": 2_048},
            "project_id": {
                "type": "string",
                "pattern": "[a-z][a-z0-9.-]*",
                "maxLength": 128,
            },
            "requirement": _OBJECT,
            "requested_time": _OBJECT,
            "entity_aliases": {
                "type": "object",
                "additionalProperties": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 512,
                },
            },
            "max_output_bytes": _OUTPUT_BUDGET,
        },
        required=("root", "project_id", "requirement", "requested_time"),
    ),
}


OUTPUT_SCHEMA: dict[str, Any] = _object_schema(
    {
        "schema_version": {"const": "gravity.mcp-tool-result.v1"},
        "tool": {"type": "string", "minLength": 1, "maxLength": 128},
        "ok": {"type": "boolean"},
        "status": {"type": "string", "minLength": 1, "maxLength": 64},
        "result": _OBJECT,
    },
    required=("schema_version", "tool", "ok", "status", "result"),
)


def input_schema(tool_name: str) -> dict[str, Any]:
    _validator(tool_name)
    return copy.deepcopy(INPUT_SCHEMAS[tool_name])


def output_schema() -> dict[str, Any]:
    _output_validator()
    return copy.deepcopy(OUTPUT_SCHEMA)


def validate_arguments(tool_name: str, value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise MCPInputError("Tool arguments must be one JSON object")
    selected = dict(value)
    try:
        _validator(tool_name).validate(selected)
    except ContractError as exc:
        raise MCPInputError("Tool arguments do not match the published input schema") from exc
    return selected


def validate_output(value: Any) -> None:
    try:
        _output_validator().validate(value)
    except ContractError as exc:
        raise MCPInputError("Tool result does not match the published output schema") from exc


@lru_cache(maxsize=None)
def _validator(tool_name: str) -> JsonSchemaValidator:
    try:
        schema = INPUT_SCHEMAS[tool_name]
    except KeyError as exc:
        raise MCPInputError("Unknown MCP Tool") from exc
    return JsonSchemaValidator(schema, f"{tool_name} input")


@lru_cache(maxsize=1)
def _output_validator() -> JsonSchemaValidator:
    return JsonSchemaValidator(OUTPUT_SCHEMA, "MCP Tool output")


__all__ = [
    "INPUT_SCHEMAS",
    "JSON_SCHEMA_VERSION",
    "MAX_OUTPUT_BYTES",
    "MCPInputError",
    "OUTPUT_SCHEMA",
    "input_schema",
    "output_schema",
    "validate_arguments",
    "validate_output",
]
