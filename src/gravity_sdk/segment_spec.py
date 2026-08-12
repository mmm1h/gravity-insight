"""Compile compact segment rules into the existing governed operation input.

This module only translates explicit caller intent.  It does not infer event,
property, segment, or aggregation semantics; the real Insight client's
``validate`` method remains authoritative for contract and metadata checks.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ._field_policy_segment import validate_analysis_segment_rule_shape
from .analysis_spec_preview import redact_analysis_values
from .domains import ANALYSIS_SEGMENT_OPERATIONS
from .errors import InputValidationError
from .segment_spec_schema import segment_rule_spec_schema
from .segment_spec_support import (
    compile_rule_set,
    logic,
    mapping,
    ordered_dates,
    reject_keys,
    text,
)
from .workspace import Workspace, load_workspace


COMPILED_SEGMENT_SCHEMA_VERSION = "gravity-insight.segment-rule-compiled.v1"
SEGMENT_EVALUATE_OPERATION = ANALYSIS_SEGMENT_OPERATIONS["evaluate"]
_SPEC_FIELDS = frozenset(
    {
        "name",
        "remark",
        "update_type",
        "start",
        "end",
        "logic",
        "property_rules",
        "event_rules",
    }
)


@dataclass(frozen=True)
class CompiledSegmentSpec:
    """One compact Segment Rule Spec resolved to an executable operation input."""

    operation_id: str
    inputs: dict[str, Any]


def compile_segment_spec(
    spec: Mapping[str, Any],
    *,
    workspace: Workspace | str | None = None,
    app: str | int | None = None,
    start: str | None = None,
    end: str | None = None,
) -> CompiledSegmentSpec:
    """Compile a compact spec without creating a client or making a request."""

    source = mapping(spec, "spec")
    reject_keys(source, _SPEC_FIELDS, "spec")
    _validate_date_overrides(start, end)
    selected_start = start if start is not None else source.get("start")
    selected_end = end if start is not None else source.get("end")
    start_date, end_date = ordered_dates(selected_start, selected_end, "date_range")
    selected_workspace = (
        workspace if isinstance(workspace, Workspace) else load_workspace(workspace)
    )
    app_id = _resolve_app(selected_workspace, app)
    update_type = source.get("update_type", "Manual")
    if update_type not in {"Manual", "Routine"}:
        raise InputValidationError(
            "update_type must be Manual or Routine", field="update_type"
        )
    inputs = {
        "app_id": str(app_id),
        "name": text(source.get("name"), "name", maximum=128),
        "remark": text(
            source.get("remark", ""),
            "remark",
            maximum=2_000,
            allow_empty=True,
        ),
        "update_type": update_type,
        "date_range": {"start_date": start_date, "end_date": end_date},
        "cond_logic": logic(source.get("logic", "AND"), "logic"),
        "user_property_rules": compile_rule_set(
            source.get("property_rules", {"groups": []}),
            "property_rules",
            events=False,
        ),
        "user_event_rules": compile_rule_set(
            source.get("event_rules", {"groups": []}),
            "event_rules",
            events=True,
        ),
    }
    validate_analysis_segment_rule_shape(inputs)
    return CompiledSegmentSpec(SEGMENT_EVALUATE_OPERATION, inputs)


def validate_segment_spec(
    client: Any,
    spec: Mapping[str, Any],
    **options: Any,
) -> tuple[CompiledSegmentSpec, Mapping[str, Any]]:
    """Compile and delegate authoritative offline/metadata validation to client."""

    compiled = compile_segment_spec(spec, **options)
    validation = client.validate(compiled.operation_id, compiled.inputs)
    if not isinstance(validation, Mapping) or not validation.get("ok"):
        error = validation.get("error") if isinstance(validation, Mapping) else None
        details = error if isinstance(error, Mapping) else {}
        raise InputValidationError(
            str(details.get("message") or "compiled Segment Rule Spec is invalid"),
            field=str(details.get("field") or "spec"),
            next_action=str(
                details.get("next_action")
                or "Correct the Segment Rule Spec and retry the same operation."
            ),
        )
    return compiled, validation


def prepare_segment_spec(
    client: Any,
    spec: Mapping[str, Any],
    **options: Any,
) -> dict[str, Any]:
    """Return a caller-safe offline preview without exposing rule values or labels."""

    compiled, validation = validate_segment_spec(client, spec, **options)
    preview, _ = redact_analysis_values(compiled.inputs)
    preview["name"] = "<redacted>"
    preview["remark"] = "<redacted>"
    return {
        "schema_version": COMPILED_SEGMENT_SCHEMA_VERSION,
        "ok": True,
        "status": "compiled",
        "offline": True,
        "network_called": False,
        "operation_id": compiled.operation_id,
        "compiled_input": preview,
        "input_values_redacted": True,
        "validation": {
            "status": validation.get("status"),
            "live_metadata_dependencies": validation.get(
                "live_metadata_dependencies", []
            ),
        },
        "plan_node": None,
        "next_action": (
            "Execute the original compact spec directly; value-bearing compiled "
            "input and Plan node were intentionally redacted from this preview."
        ),
    }


def _resolve_app(workspace: Workspace, value: Any) -> int:
    try:
        return workspace.resolve_app(value)
    except ValueError:
        raise InputValidationError(
            "app must reference a configured workspace App or positive id", field="app"
        ) from None


def _validate_date_overrides(start: str | None, end: str | None) -> None:
    if start is None and end is not None:
        raise InputValidationError(
            "end override requires start override", field="start/end"
        )


__all__ = [
    "COMPILED_SEGMENT_SCHEMA_VERSION",
    "CompiledSegmentSpec",
    "compile_segment_spec",
    "prepare_segment_spec",
    "segment_rule_spec_schema",
    "validate_segment_spec",
]
