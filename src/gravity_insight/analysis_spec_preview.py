"""Caller-safe preview projection for compiled Analysis inputs."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any


def prepare_query_spec_preview(
    client: Any,
    kind: str,
    spec: Mapping[str, Any],
    *,
    validate_query_spec: Callable[..., tuple[Any, Mapping[str, Any]]],
    schema_version: str,
    gap_error_type: type[BaseException],
    gap_code: str,
    gap_journey: str,
    gap_reason: str,
    gap_next_action: str,
    gap_operation_id: str,
    **options: Any,
) -> dict[str, Any]:
    """Run offline validation and return either a safe preview or named gap."""

    try:
        compiled, validation = validate_query_spec(client, kind, spec, **options)
    except gap_error_type as error:
        if getattr(error, "code", None) != gap_code:
            raise
        return _retention_additive_followup_gap(
            error,
            schema_version=schema_version,
            code=gap_code,
            journey=gap_journey,
            reason=gap_reason,
            next_action=gap_next_action,
            operation_id=gap_operation_id,
        )
    preview, values_redacted = redact_analysis_values(compiled.inputs)
    plan_node = None if values_redacted else compiled.plan_node()
    next_action = (
        "Execute the original compact spec directly; value-bearing compiled "
        "input and Plan node were intentionally redacted from this preview."
        if values_redacted
        else (
            "Execute compiled_input through this operation, or place plan_node "
            "inside a gravity plan run input."
        )
    )
    return {
        "schema_version": schema_version,
        "ok": True,
        "status": "compiled",
        "offline": True,
        "network_called": False,
        "kind": compiled.kind,
        "operation_id": compiled.operation_id,
        "compiled_input": preview,
        "input_values_redacted": values_redacted,
        "validation": {
            "status": validation.get("status"),
            "live_metadata_dependencies": validation.get(
                "live_metadata_dependencies", []
            ),
        },
        "plan_node": plan_node,
        "next_action": next_action,
    }


def _retention_additive_followup_gap(
    error: BaseException,
    *,
    schema_version: str,
    code: str,
    journey: str,
    reason: str,
    next_action: str,
    operation_id: str,
) -> dict[str, Any]:
    gap: dict[str, Any] = {
        "kind": "capability_gap",
        "code": code,
        "journey": journey,
        "query": "retention cohort additive follow-up SumCount",
        "reason": reason,
        "next_action": next_action,
        "weak_matches": [],
        "network_called": False,
    }
    gap.update(
        {
            "schema_version": schema_version,
            "ok": False,
            "status": "capability_gap",
            "offline": True,
            "operation_id": operation_id,
            "field": getattr(error, "field", None),
            "measurement": {
                "status": "unmeasured",
                "value": None,
                "candidate_wire_path": (
                    "data.<cohort-row>.values_another_event[offset]"
                ),
            },
            "privacy": {
                "projection": "aggregate_only",
                "user_level_rows": False,
            },
            "completeness": "unknown",
        }
    )
    return gap


def redact_analysis_values(
    value: Any, *, key: str | None = None
) -> tuple[Any, bool]:
    """Preserve executable structure while removing caller-supplied values."""

    if key in {"user_filtering", "user_re_attribute_filtering"} and value:
        return {"redacted": True}, True
    if key in {"value", "values"} and value not in (None, [], (), {}):
        if isinstance(value, (list, tuple)):
            return ["<redacted>" for _ in value], True
        return "<redacted>", True
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        changed = False
        for child_key, child in value.items():
            result[child_key], child_changed = redact_analysis_values(
                child, key=str(child_key)
            )
            changed = changed or child_changed
        return result, changed
    if isinstance(value, (list, tuple)):
        result_list: list[Any] = []
        changed = False
        for child in value:
            projected, child_changed = redact_analysis_values(child)
            result_list.append(projected)
            changed = changed or child_changed
        return result_list, changed
    return value, False


__all__ = ["prepare_query_spec_preview", "redact_analysis_values"]
