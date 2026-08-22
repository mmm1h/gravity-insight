"""Compile and resume the one supported investigation through Plan v1."""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from .analysis_playbook_catalog import (
    PLAYBOOK_ID,
    PLAYBOOK_VERSION,
    bind_metric_anomaly_playbook_definition,
    metric_anomaly_playbook_definition,
    playbook_definition_fingerprint,
)
from .analysis_playbook_input import (
    INPUT_SCHEMA_VERSION,
    PLAYBOOK_INPUT_ACTION,
    metric_anomaly_input_schema,
    normalize_metric_anomaly_inputs,
    playbook_input_error,
)
from .semantic_compose import SEMANTIC_COMPOSE_INPUT_SCHEMA_VERSION, actual_value


RESULT_SCHEMA_VERSION = "gravity.metric-anomaly-localization-result.v1"
CHECKPOINT_SCHEMA_VERSION = "gravity.analysis-playbook-checkpoint.v1"
COMPILED_SCHEMA_VERSION = "gravity.analysis-playbook-compiled.v1"


def metric_anomaly_playbook_schema() -> dict[str, Any]:
    """Describe the fixed investigation and its closed caller input."""

    definition = metric_anomaly_playbook_definition()
    return {
        "schema_version": "gravity.analysis-playbook-schema.v1",
        "ok": True,
        "status": "success",
        "playbook": _identity(definition),
        "goal": definition["goal"],
        "input_schema": metric_anomaly_input_schema(),
        "steps": copy.deepcopy(definition["steps"]),
        "stop_conditions": copy.deepcopy(definition["stop_conditions"]),
        "allowed_claims": copy.deepcopy(definition["allowed_claims"]),
        "execution": {
            "query_product": "semantic_compose",
            "plan_schema_version": "gravity.plan.v1",
            "resume_invalidation": "transitive DAG descendants only",
            "unchanged_successful_steps": "reused without execution",
        },
    }


def compile_metric_anomaly_playbook(
    inputs: Mapping[str, Any], checkpoint: Mapping[str, Any] | None = None,
    *,
    semantic_binding: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Create the full or resumed Plan while retaining the definition DAG."""

    normalized = normalize_metric_anomaly_inputs(inputs)
    definition = _definition(semantic_binding)
    own = _own_input_fingerprints(definition, normalized)
    prior = _validated_checkpoint(checkpoint, definition) if checkpoint is not None else None
    invalidated = _invalidated_steps(definition, own, prior)
    query_steps = [
        step for step in definition["steps"]
        if step["kind"] == "query" and step["id"] in invalidated
    ]
    plan = _compile_plan(definition, normalized, query_steps, invalidated)
    reusable = [
        str(step["id"]) for step in definition["steps"]
        if step["id"] not in invalidated
    ]
    reusable_queries = [
        str(step["id"]) for step in definition["steps"]
        if step["kind"] == "query" and step["id"] not in invalidated
    ]
    previous_items = _checkpoint_items(prior, reusable_queries)
    return {
        "schema_version": COMPILED_SCHEMA_VERSION,
        "playbook": _identity(definition),
        "inputs": normalized,
        "own_input_fingerprints": own,
        "invalidated_steps": [
            str(step["id"]) for step in definition["steps"] if step["id"] in invalidated
        ],
        "reused_steps": reusable,
        "rerun_steps": [str(step["id"]) for step in query_steps],
        "plan": plan,
        "previous_items": previous_items,
    }


def run_metric_anomaly_playbook(
    sdk: Any,
    inputs: Mapping[str, Any],
    *,
    checkpoint: Mapping[str, Any] | None = None,
    max_workers: int = 6,
    dry_run: bool = False,
    execute_plan: Callable[[Mapping[str, Any]], Mapping[str, Any]] | None = None,
    semantic_binding: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute only invalidated query nodes and deterministically rebuild the result."""

    definition = _definition(semantic_binding)
    compiled = compile_metric_anomaly_playbook(
        inputs, checkpoint, semantic_binding=semantic_binding
    )
    plan = compiled["plan"]
    if dry_run:
        validation = (
            sdk.execute_plan(plan, max_workers=max_workers, dry_run=True)
            if plan is not None else _no_query_validation(max_workers)
        )
        return {
            **{key: copy.deepcopy(compiled[key]) for key in (
                "schema_version", "playbook", "inputs", "invalidated_steps",
                "reused_steps", "rerun_steps", "plan",
            )},
            "ok": True,
            "status": "validated",
            "network_called": False,
            "plan_validation": validation,
        }
    if execute_plan is not None and plan is not None:
        plan_result = execute_plan(plan)
    elif plan is not None:
        plan_result = sdk.execute_plan(plan, max_workers=max_workers)
    else:
        plan_result = _no_query_execution(max_workers)
    fresh = _plan_items(plan_result, tuple(compiled["rerun_steps"]))
    items = {**compiled["previous_items"], **fresh}
    from .analysis_playbook_result import build_metric_anomaly_result

    result = build_metric_anomaly_result(
        definition, compiled["inputs"], items,
        invalidated_steps=compiled["invalidated_steps"],
        reused_steps=compiled["reused_steps"],
        rerun_steps=compiled["rerun_steps"],
    )
    result["checkpoint"] = _build_checkpoint(
        result,
        compiled["inputs"],
        compiled["own_input_fingerprints"],
        items,
        definition,
    )
    return result


def _compile_plan(
    definition: Mapping[str, Any], inputs: Mapping[str, Any],
    steps: Sequence[Mapping[str, Any]], invalidated: set[str],
) -> dict[str, Any] | None:
    if not steps:
        return None
    nodes: list[dict[str, Any]] = []
    for step in steps:
        step_id = str(step["id"])
        dependencies = [
            item for item in _query_dependencies(definition, step_id)
            if item in invalidated
        ]
        node: dict[str, Any] = {
            "id": step_id,
            "kind": "composite",
            "request": _semantic_request(step_id, definition, inputs),
            "limits": {"max_pages": 1, "max_items": 200},
        }
        if dependencies:
            node["depends_on"] = dependencies
        nodes.append(node)
    return {
        "schema_version": "gravity.plan.v1",
        "budget": {"max_workers": 6, "max_total_items": 1200},
        "nodes": nodes,
    }


def _semantic_request(
    step_id: str, definition: Mapping[str, Any], inputs: Mapping[str, Any],
) -> dict[str, Any]:
    current = step_id.endswith("current")
    window = inputs["current_window"] if current else inputs["reference_window"]
    grouped = step_id.startswith("compare_") or step_id.startswith("validate_")
    filtered = step_id.startswith("validate_")
    members = definition["members"]
    semantic_inputs = {
        "definition": copy.deepcopy(definition["semantic_definition"]),
        "window": copy.deepcopy(window),
        "metric": copy.deepcopy(members["metric"]),
        "dimensions": [copy.deepcopy(members["dimension"])] if grouped else [],
        "filters": ([{
            "member": copy.deepcopy(members["filter"]),
            "operator": "IN",
            "values": list(inputs["hypothesis"]["values"]),
        }] if filtered else []),
        "grain": copy.deepcopy(members["grain"]),
        "joins": [copy.deepcopy(members["join"])] if grouped else [],
    }
    return {
        "name": "semantic_compose",
        "input_schema_version": SEMANTIC_COMPOSE_INPUT_SCHEMA_VERSION,
        "app": copy.deepcopy(inputs["app"]),
        "inputs": semantic_inputs,
    }


def _query_dependencies(definition: Mapping[str, Any], step_id: str) -> list[str]:
    by_id = {str(step["id"]): step for step in definition["steps"]}
    selected: list[str] = []

    def visit(candidate: str) -> None:
        step = by_id[candidate]
        if step["kind"] == "query":
            if candidate not in selected:
                selected.append(candidate)
            return
        for parent in step["depends_on"]:
            visit(str(parent))

    for dependency in by_id[step_id]["depends_on"]:
        visit(str(dependency))
    return selected


def _own_input_fingerprints(
    definition: Mapping[str, Any], inputs: Mapping[str, Any],
) -> dict[str, str]:
    return {
        str(step["id"]): _fingerprint({
            field: inputs[field] for field in step["input_dependencies"]
        })
        for step in definition["steps"]
    }


def _invalidated_steps(
    definition: Mapping[str, Any], own: Mapping[str, str],
    checkpoint: Mapping[str, Any] | None,
) -> set[str]:
    if checkpoint is None:
        return {str(step["id"]) for step in definition["steps"]}
    prior = {str(step["id"]): step for step in checkpoint["steps"]}
    invalid = {
        str(step["id"]) for step in definition["steps"]
        if prior[str(step["id"])]["own_input_fingerprint"] != own[str(step["id"])]
        or (step["kind"] == "query" and not _reusable_item(prior[str(step["id"])].get("plan_item")))
    }
    for step in definition["steps"]:
        if any(str(parent) in invalid for parent in step["depends_on"]):
            invalid.add(str(step["id"]))
    return invalid


def _validated_checkpoint(
    value: Mapping[str, Any], definition: Mapping[str, Any],
) -> Mapping[str, Any]:
    selected = value.get("checkpoint") if isinstance(value.get("checkpoint"), Mapping) else value
    if not isinstance(selected, Mapping):
        raise playbook_input_error("playbook checkpoint must be an object", "checkpoint", actual_value(type(selected).__name__), CHECKPOINT_SCHEMA_VERSION, next_action=PLAYBOOK_INPUT_ACTION)
    allowed = {"schema_version", "playbook", "inputs", "steps"}
    if set(selected) != allowed or selected.get("schema_version") != CHECKPOINT_SCHEMA_VERSION:
        raise playbook_input_error("playbook checkpoint fields or schema are invalid", "checkpoint.schema_version", actual_value(selected.get("schema_version")), CHECKPOINT_SCHEMA_VERSION, next_action=PLAYBOOK_INPUT_ACTION)
    identity = selected.get("playbook")
    expected = _identity(definition)
    if identity != expected:
        raise playbook_input_error("playbook checkpoint identity changed", "checkpoint.playbook", actual_value(identity), expected, next_action=PLAYBOOK_INPUT_ACTION)
    old_inputs = normalize_metric_anomaly_inputs(selected.get("inputs"))
    expected_own = _own_input_fingerprints(definition, old_inputs)
    steps = selected.get("steps")
    if not isinstance(steps, list) or len(steps) != len(definition["steps"]):
        raise playbook_input_error("playbook checkpoint steps are incomplete", "checkpoint.steps", actual_value(len(steps) if isinstance(steps, list) else type(steps).__name__), len(definition["steps"]), next_action=PLAYBOOK_INPUT_ACTION)
    for expected_step, actual in zip(definition["steps"], steps):
        step_id = str(expected_step["id"])
        if not isinstance(actual, Mapping) or actual.get("id") != step_id:
            raise playbook_input_error("playbook checkpoint step identity changed", "checkpoint.steps", actual_value(actual), step_id, next_action=PLAYBOOK_INPUT_ACTION)
        fingerprint = actual.get("own_input_fingerprint")
        if fingerprint != expected_own[step_id]:
            raise playbook_input_error("playbook checkpoint input fingerprint changed", f"checkpoint.steps.{step_id}.own_input_fingerprint", actual_value(fingerprint), expected_own[step_id], next_action=PLAYBOOK_INPUT_ACTION)
        item = actual.get("plan_item")
        result_fingerprint = actual.get("result_fingerprint")
        expected_result = _fingerprint(item) if item is not None else None
        if result_fingerprint != expected_result:
            raise playbook_input_error("playbook checkpoint result fingerprint changed", f"checkpoint.steps.{step_id}.result_fingerprint", actual_value(result_fingerprint), expected_result, next_action=PLAYBOOK_INPUT_ACTION)
    return selected


def _checkpoint_items(
    checkpoint: Mapping[str, Any] | None, reusable: Sequence[str],
) -> dict[str, Mapping[str, Any]]:
    if checkpoint is None:
        return {}
    by_id = {str(step["id"]): step for step in checkpoint["steps"]}
    return {step_id: copy.deepcopy(by_id[step_id]["plan_item"]) for step_id in reusable}


def _plan_items(
    result: Mapping[str, Any], expected: tuple[str, ...],
) -> dict[str, Mapping[str, Any]]:
    values = result.get("results") if isinstance(result, Mapping) else None
    if not isinstance(values, list):
        raise RuntimeError("playbook Plan result omitted its node results")
    by_id = {
        str(item.get("node_id")): copy.deepcopy(dict(item))
        for item in values if isinstance(item, Mapping)
    }
    if tuple(item for item in expected if item in by_id) != expected or len(by_id) != len(expected):
        raise RuntimeError("playbook Plan result node identities changed")
    return by_id


def _build_checkpoint(
    result: Mapping[str, Any], inputs: Mapping[str, Any], own: Mapping[str, str],
    items: Mapping[str, Mapping[str, Any]],
    definition: Mapping[str, Any],
) -> dict[str, Any]:
    statuses = {
        str(step["id"]): str(step["status"])
        for step in result["steps"] if isinstance(step, Mapping)
    }
    steps = []
    for step in definition["steps"]:
        step_id = str(step["id"])
        item = copy.deepcopy(items.get(step_id))
        steps.append({
            "id": step_id,
            "status": statuses[step_id],
            "own_input_fingerprint": own[step_id],
            "result_fingerprint": _fingerprint(item) if item is not None else None,
            "plan_item": item,
        })
    return {
        "schema_version": CHECKPOINT_SCHEMA_VERSION,
        "playbook": _identity(definition),
        "inputs": copy.deepcopy(dict(inputs)),
        "steps": steps,
    }


def _reusable_item(value: Any) -> bool:
    return (
        isinstance(value, Mapping)
        and value.get("ok") is True
        and value.get("status") == "success"
        and isinstance(value.get("result"), Mapping)
    )


def _definition(
    semantic_binding: Mapping[str, Any] | None,
) -> dict[str, Any]:
    return (
        metric_anomaly_playbook_definition()
        if semantic_binding is None
        else bind_metric_anomaly_playbook_definition(semantic_binding)
    )


def _identity(definition: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "playbook_id": PLAYBOOK_ID,
        "version": PLAYBOOK_VERSION,
        "fingerprint": playbook_definition_fingerprint(definition),
    }


def _fingerprint(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _no_query_validation(max_workers: int) -> dict[str, Any]:
    return {
        "schema_version": "gravity.plan-result.v1", "ok": True,
        "status": "validated", "dry_run": True, "declared_count": 0,
        "max_expanded_count": 0, "max_aggregate_items": 0,
        "max_workers": max_workers, "exit_code": 0, "results": [],
    }


def _no_query_execution(max_workers: int) -> dict[str, Any]:
    return {
        "schema_version": "gravity.plan-result.v1", "ok": True,
        "status": "success", "dry_run": False, "declared_count": 0,
        "expanded_count": 0, "success_count": 0, "empty_count": 0,
        "failure_count": 0, "skipped_count": 0, "exit_code": 0,
        "max_workers": max_workers, "results": [],
    }


__all__ = [
    "CHECKPOINT_SCHEMA_VERSION",
    "COMPILED_SCHEMA_VERSION",
    "INPUT_SCHEMA_VERSION",
    "RESULT_SCHEMA_VERSION",
    "compile_metric_anomaly_playbook",
    "metric_anomaly_playbook_schema",
    "normalize_metric_anomaly_inputs",
    "run_metric_anomaly_playbook",
]
