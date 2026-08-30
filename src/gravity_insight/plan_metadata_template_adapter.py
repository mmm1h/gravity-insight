"""Explicit-confirmation Plan adapter for metadata-template mutations."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from .actionable_error_values import actual_value
from .errors import InputValidationError
from .metadata_template_mutation import metadata_template_mutation_schema
from .plan import AdapterContext
from .plan_adapter_support import validate_exact_targets, validate_selected_fields


NAME = "metadata_template_mutation"
_REQUEST_FIELDS = frozenset({"name", "mode", "inputs"})
_OUTPUT_FIELDS = frozenset({
    "operation_id", "effect", "offline", "network_called", "write_sent",
    "dry_run", "confirmation_required", "automatic_retry", "attempts",
    "target", "preimage", "impact", "preconditions", "request",
    "normalized_input", "mutation", "next_action", "error", "idempotent_reuse",
})


def validate_metadata_template_plan(
    request: Mapping[str, Any], context: AdapterContext
) -> None:
    if set(request) - _REQUEST_FIELDS or request.get("name") != NAME:
        raise metadata_template_plan_error(
            actual_value(sorted(request)), actual_value(sorted(_REQUEST_FIELDS)),
            "request", "Use exactly name, mode, and inputs for this composite node.",
        )
    mode = request.get("mode")
    if mode not in {"preview", "execute"}:
        raise metadata_template_plan_error(
            actual_value(mode), "preview or execute", "request.mode",
            "Choose preview first, review it, then change only mode to execute.",
        )
    supplied = request.get("inputs")
    if not isinstance(supplied, Mapping):
        raise metadata_template_plan_error(
            actual_value(type(supplied).__name__), "an action/input object",
            "request.inputs", "Pass action plus an exact nested input object.",
        )
    action, action_inputs = supplied.get("action"), supplied.get("inputs")
    actions = metadata_template_mutation_schema()["actions"]
    if action not in actions or not isinstance(action_inputs, Mapping) or set(supplied) != {"action", "inputs"}:
        raise metadata_template_plan_error(
            actual_value({"action": action, "fields": sorted(supplied)}),
            actual_value({"actions": sorted(actions), "fields": ["action", "inputs"]}),
            "request.inputs", "Choose one schema action and its exact nested input object.",
        )
    allowed = set(actions[action]["required"]) | set(actions[action]["optional"])
    missing = set(actions[action]["required"]) - set(action_inputs)
    unknown = set(action_inputs) - allowed
    if missing or unknown:
        raise metadata_template_plan_error(
            actual_value({"missing": sorted(missing), "unknown": sorted(unknown)}),
            actual_value(sorted(allowed)), "request.inputs.inputs",
            "Correct the action input fields, validate the Plan, then run preview.",
        )
    validate_exact_targets(context, frozenset())
    validate_selected_fields(context.output_fields, _OUTPUT_FIELDS, "output_fields")


def execute_metadata_template_plan(
    sdk: Any, request: Mapping[str, Any], context: AdapterContext
) -> dict[str, Any]:
    validate_metadata_template_plan(request, context)
    supplied = request["inputs"]
    return sdk.metadata_template_mutation(
        str(supplied["action"]), supplied["inputs"],
        execute=request["mode"] == "execute",
    )


def is_metadata_template_result(value: Any) -> bool:
    return isinstance(value, Mapping) and value.get("schema_version") == "gravity-insight.metadata-template-mutation.v1"


def project_metadata_template_result(
    result: Any, fields: tuple[str, ...], _context: AdapterContext
) -> dict[str, Any]:
    if not isinstance(result, Mapping):
        raise metadata_template_plan_error(
            actual_value(type(result).__name__), "a metadata-template result object",
            "result", "Inspect the adapter result contract before rerunning the Plan.",
        )
    selected = {"schema_version", "ok", "status", "result_source"} | set(fields or _OUTPUT_FIELDS)
    return {key: copy.deepcopy(value) for key, value in result.items() if key in selected}


def metadata_template_plan_error(
    actual: str, allowed: str, field: str, next_action: str
) -> InputValidationError:
    return InputValidationError(
        f"actual value: {actual}; allowed value: {allowed}",
        field=field, next_action=next_action,
    )


__all__ = [
    "NAME", "execute_metadata_template_plan", "is_metadata_template_result",
    "project_metadata_template_result", "validate_metadata_template_plan",
]
