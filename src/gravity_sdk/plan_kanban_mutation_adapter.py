"""Explicit-confirmation Plan composite for governed Kanban mutations."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from .errors import InputValidationError
from .kanban_mutation import kanban_mutation_schema
from .plan import AdapterContext
from .plan_adapter_support import validate_exact_targets, validate_selected_fields


NAME = "kanban_mutation"
_REQUEST_FIELDS = frozenset({"name", "mode", "inputs"})
_OUTPUT_FIELDS = frozenset(
    {
        "operation_id", "effect", "offline", "network_called", "write_sent",
        "dry_run", "confirmation_required", "automatic_retry", "attempts",
        "read_attempts", "target", "preimage", "impact", "cascade",
        "preconditions", "request", "normalized_input", "preview_fingerprint",
        "mutation", "next_action", "error",
    }
)


def validate_kanban_plan(request: Mapping[str, Any], context: AdapterContext) -> None:
    if set(request) - _REQUEST_FIELDS or request.get("name") != NAME:
        raise _input(
            "actual value: mismatched Kanban Plan fields; allowed value: exactly name, mode, and inputs",
            "request",
        )
    mode = request.get("mode")
    if mode not in {"preview", "execute"}:
        raise _input("actual value: unsupported mode; allowed values: preview or execute", "request.mode")
    supplied = request.get("inputs")
    if not isinstance(supplied, Mapping):
        raise _input("actual value: non-object inputs; allowed value: an input object", "request.inputs")
    action = supplied.get("action")
    action_inputs = supplied.get("inputs")
    schema = kanban_mutation_schema()["actions"]
    if action not in schema or not isinstance(action_inputs, Mapping):
        raise _input(
            "actual value: invalid action or nested input; allowed value: an allowlisted action and input object",
            "request.inputs",
        )
    allowed = set(schema[action]["required"]) | set(schema[action]["optional"])
    missing = set(schema[action]["required"]) - set(action_inputs)
    unknown = set(action_inputs) - allowed
    if missing or unknown or set(supplied) != {"action", "inputs"}:
        raise _input(
            "actual value: missing or unknown action fields; allowed value: the exact selected action schema",
            "request.inputs.inputs",
        )
    validate_exact_targets(context, frozenset())
    validate_selected_fields(context.output_fields, _OUTPUT_FIELDS, "output_fields")


def execute_kanban_plan(
    sdk: Any, request: Mapping[str, Any], context: AdapterContext
) -> dict[str, Any]:
    validate_kanban_plan(request, context)
    supplied = request["inputs"]
    return sdk.kanban_mutation(
        str(supplied["action"]),
        supplied["inputs"],
        execute=request["mode"] == "execute",
    )


def is_kanban_result(value: Any) -> bool:
    return isinstance(value, Mapping) and value.get("schema_version") == "gravity-insight.kanban-mutation.v1"


def project_kanban_result(
    result: Any, fields: tuple[str, ...], _context: AdapterContext
) -> dict[str, Any]:
    if not isinstance(result, Mapping):
        raise _input("actual value: invalid result; allowed value: a Kanban mutation result object", "result")
    structural = {"schema_version", "ok", "status", "result_source"}
    selected = structural | set(fields or _OUTPUT_FIELDS)
    return {key: copy.deepcopy(value) for key, value in result.items() if key in selected}


def _input(message: str, field: str) -> InputValidationError:
    return InputValidationError(
        f"actual value: invalid Kanban Plan request; allowed value: {message}",
        field=field,
        next_action="Correct the `kanban_mutation` composite node, run Plan validation, then execute preview before execute mode.",
    )


__all__ = [
    "NAME",
    "execute_kanban_plan",
    "is_kanban_result",
    "project_kanban_result",
    "validate_kanban_plan",
]
