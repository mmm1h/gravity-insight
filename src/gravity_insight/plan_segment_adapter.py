"""Controlled Plan composite for compact Segment Rule Spec evaluation."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from .output_projection import validate_output_fields
from .plan import AdapterContext
from .plan_adapter_support import (
    has_dynamic,
    input_error,
    mapping,
    request_object,
    validate_exact_targets,
)
from .segment_spec import (
    SEGMENT_EVALUATE_OPERATION,
    compile_segment_spec,
    validate_segment_spec,
)
from .actionable_error_values import actual_value


SEGMENT_EVALUATE_NAME = "segment_evaluate"
SEGMENT_EVALUATE_REQUEST_FIELDS = frozenset(
    {"name", "app", "spec", "start", "end"}
)
_SAFE_ENVELOPE_FIELDS = frozenset(
    {
        "schema_version", "ok", "status", "operation_id", "contract_version",
        "source", "fetched_at", "schema_fingerprint", "data", "warnings",
        "error", "output_fields",
    }
)
_SAFE_ERROR_FIELDS = frozenset(
    {"category", "code", "field", "retryable", "retry_after_ms"}
)
_FAILURE_STATUSES = frozenset(
    {"contract_changed", "upstream_changed", "semantic_error", "error", "failed"}
)


def validate_segment_evaluate_plan(
    insight: Any,
    workspace: Any,
    request: Mapping[str, Any],
    context: AdapterContext,
) -> str:
    """Validate the entire literal spec before any Plan node executes."""

    request_object(request, SEGMENT_EVALUATE_REQUEST_FIELDS, "segment_evaluate")
    if request.get("name") != SEGMENT_EVALUATE_NAME:
        raise input_error(
            f"actual value: {actual_value(request.get('name'))}; segment evaluation composite "
            "name is invalid; must match the documented composite name",
            "name",
        )
    validate_exact_targets(context, frozenset({"/app"}))
    if "spec" not in request:
        raise input_error(f"actual value: {actual_value(request.get('spec'))}; " + ("segment evaluation requires spec"), "spec")
    spec = mapping(request.get("spec"), "spec")
    if "app" not in request and not has_dynamic(context, "/app"):
        raise input_error(f"actual value: {actual_value(request.get('app'))}; " + ("segment evaluation requires app"), "app")
    selected_app = 1 if has_dynamic(context, "/app") else request.get("app")
    compiled, _validation = validate_segment_spec(
        insight,
        spec,
        workspace=workspace,
        app=selected_app,
        start=request.get("start"),
        end=request.get("end"),
    )
    if context.output_fields:
        validate_output_fields(
            insight.schema(compiled.operation_id),
            context.output_fields,
            request_inputs=compiled.inputs,
        )
    return compiled.operation_id


def execute_segment_evaluate_plan(
    sdk: Any,
    request: Mapping[str, Any],
    context: AdapterContext,
) -> dict[str, Any]:
    """Revalidate bound app, execute once, and remove all caller rule values."""

    compiled = compile_segment_spec(
        mapping(request.get("spec"), "spec"),
        workspace=context.workspace,
        app=request.get("app"),
        start=request.get("start"),
        end=request.get("end"),
    )
    result = sdk.read(
        compiled.operation_id,
        compiled.inputs,
        output_fields=context.output_fields or None,
    )
    return safe_segment_envelope(
        result, expected_operation=compiled.operation_id
    )


def is_segment_evaluate_result(result: Any) -> bool:
    return isinstance(result, Mapping) and result.get("operation_id") == SEGMENT_EVALUATE_OPERATION


def safe_segment_envelope(
    result: Any, *, expected_operation: str | None = None
) -> dict[str, Any]:
    """Project the native aggregate envelope without request or exception text."""

    if not isinstance(result, Mapping):
        raise input_error(
            f"actual value: {actual_value(type(result).__name__)}; segment evaluation result "
            "is invalid; must be an object envelope",
            "result",
        )
    selected = {
        key: copy.deepcopy(value)
        for key, value in result.items()
        if key in _SAFE_ENVELOPE_FIELDS and key != "error"
    }
    status = str(result.get("status", "")).casefold()
    operation_changed = (
        expected_operation is not None
        and result.get("operation_id") != expected_operation
    )
    if operation_changed or status in _FAILURE_STATUSES:
        selected.update(
            {
                "ok": False,
                "status": "contract_changed" if operation_changed else status,
                "operation_id": expected_operation or SEGMENT_EVALUATE_OPERATION,
                "data": {},
                "error": _safe_failure(result),
            }
        )
        return selected
    error = result.get("error")
    if isinstance(error, Mapping):
        selected["error"] = {
            key: copy.deepcopy(value)
            for key, value in error.items()
            if key in _SAFE_ERROR_FIELDS
        }
    return selected


def _safe_failure(result: Mapping[str, Any]) -> dict[str, Any]:
    error = result.get("error")
    selected = (
        {
            key: copy.deepcopy(value)
            for key, value in error.items()
            if key in _SAFE_ERROR_FIELDS
        }
        if isinstance(error, Mapping)
        else {}
    )
    return {
        **selected,
        "category": selected.get("category", "upstream"),
        "code": selected.get("code", "CONTRACT_CHANGED"),
        "message": "The Segment evaluation no longer matches its governed contract.",
        "next_action": "Inspect contract drift before retrying this Plan node.",
        "retryable": bool(selected.get("retryable", False)),
    }


def project_segment_evaluate_result(
    result: Any, _fields: tuple[str, ...], _context: AdapterContext
) -> dict[str, Any]:
    return safe_segment_envelope(result)


__all__ = [
    "SEGMENT_EVALUATE_NAME",
    "SEGMENT_EVALUATE_REQUEST_FIELDS",
    "execute_segment_evaluate_plan",
    "is_segment_evaluate_result",
    "project_segment_evaluate_result",
    "safe_segment_envelope",
    "validate_segment_evaluate_plan",
]
