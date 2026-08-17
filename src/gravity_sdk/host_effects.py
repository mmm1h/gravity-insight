"""Model-external origin and authorization boundary for host-generated Plans."""

from __future__ import annotations

import copy
from collections.abc import Iterable, Mapping
from typing import Any

from .errors import InputValidationError
from .host_effect_sources import (
    ACTION_SCHEMA_VERSION,
    CONFIRMATION_SCHEMA_VERSION,
    PERMISSION_SCHEMA_VERSION,
    SOURCE_SCHEMA_VERSION,
    add_violation,
    assess_host_action,
    expect_sdk_source,
    host_source,
    source_for_plan,
    source_value,
)
from .plan import PLAN_SCHEMA_VERSION, validate_plan


HOST_PLAN_SCHEMA_VERSION = "gravity.host-plan.v1"
COMPILED_SCHEMA_VERSION = "gravity.host-plan-compiled.v1"

_HOST_PLAN_FIELDS = frozenset(
    {"schema_version", "plan", "action", "control_sources"}
)
_PLAN_SELECTOR_FIELDS = ("selector", "product", "name")


def host_effect_schema() -> dict[str, Any]:
    """Return the machine-readable host boundary without any business values."""

    return {
        "schema_version": "gravity.host-effect-schema.v1",
        "source_schema_version": SOURCE_SCHEMA_VERSION,
        "action_schema_version": ACTION_SCHEMA_VERSION,
        "host_plan_schema_version": HOST_PLAN_SCHEMA_VERSION,
        "origins": ["user", "tool_result", "sdk_contract"],
        "roles": ["data", "instruction", "authorization"],
        "control_rules": {
            "tool_operation_path": "sdk_contract/instruction",
            "object_ids_destination": "user/instruction|authorization",
            "mutation_permission": "user/authorization exact request_sha256",
            "execute_confirmation": (
                "user/authorization exact preview_fingerprint and request_sha256"
            ),
            "tool_result": "data_only",
        },
        "plan_rules": {
            "control_sources": "required for every node kind and selector/product/name/action",
            "request_authority": "canonical full Plan with mutation phase normalized",
            "mixed_preview_execute": "rejected",
            "execution_entry": "execute_host_plan(sdk, host_plan, sources)",
        },
    }


def normalized_host_plan_request(
    plan: Mapping[str, Any],
    *,
    mutation_operations: Iterable[str],
) -> dict[str, Any]:
    """Return the permission payload shared by preview and same-input execute."""

    selected = copy.deepcopy(dict(plan))
    mutation_ids = frozenset(map(str, mutation_operations))
    from .plan_mutation_adapter import NAMES as mutation_names

    for node in selected.get("nodes", []):
        if not isinstance(node, Mapping):
            continue
        request = node.get("request")
        if not isinstance(request, dict):
            continue
        composite = (
            node.get("kind") == "composite"
            and request.get("name") in mutation_names
        )
        raw_mutation = (
            node.get("kind") == "run"
            and request.get("selector") in mutation_ids
        )
        if composite and request.get("mode") in {"preview", "execute"}:
            request["mode"] = "<user-confirmed-phase>"
        elif raw_mutation:
            request["mode"] = "<user-confirmed-phase>"
    return selected


def assess_host_plan(
    host_plan: Any,
    sources: Mapping[str, Any],
    *,
    mutation_operations: Iterable[str],
) -> dict[str, Any]:
    """Assess a host Plan, including every tool/operation control position."""

    violations: list[dict[str, str]] = []
    if not isinstance(sources, Mapping):
        add_violation(violations, "SOURCE_MAP_INVALID", "sources")
        sources = {}
    selected = _host_plan_mapping(host_plan, violations)
    plan = _validated_plan(selected.get("plan"), violations)
    mutation_ids = frozenset(map(str, mutation_operations))
    derived_effect, derived_phase = _plan_effect(plan, mutation_ids, violations)
    action = selected.get("action")
    action_report = assess_host_action(action, sources)
    violations.extend(action_report["violations"])
    _assess_effect_alignment(
        action, action_report, derived_effect, derived_phase, violations
    )
    expected_request = (
        normalized_host_plan_request(plan, mutation_operations=mutation_ids)
        if plan else {}
    )
    if not isinstance(action, Mapping) or action.get("request") != expected_request:
        add_violation(
            violations, "PLAN_REQUEST_MISMATCH", "host_plan.action.request"
        )
    if derived_effect == "mutation":
        _assess_object_coverage(
            expected_request,
            action_report.get("controls", {}).get("object_ids", []),
            violations,
        )
    _assess_control_sources(
        plan, selected.get("control_sources"), sources, violations
    )
    return {
        "schema_version": "gravity.host-plan-assessment.v1",
        "allowed": not violations,
        "effect": derived_effect,
        "phase": derived_phase,
        "request_sha256": action_report.get("request_sha256"),
        "controls": copy.deepcopy(action_report.get("controls", {})),
        "violations": violations,
    }


def compile_host_plan(
    host_plan: Any,
    sources: Mapping[str, Any],
    *,
    mutation_operations: Iterable[str],
) -> dict[str, Any]:
    """Fail closed and return the only Plan object an effect-capable host may run."""

    report = assess_host_plan(
        host_plan, sources, mutation_operations=mutation_operations
    )
    if not report["allowed"]:
        codes = ", ".join(item["code"] for item in report["violations"][:8])
        raise InputValidationError(
            f"actual value: host Plan origin/authority violations ({codes}); allowed value: SDK-origin control identifiers, user-origin object/destination controls, and exact user permission plus confirmation for mutations",
            field="host_plan",
            next_action=(
                "Keep tool results as data, rebuild control references from the SDK catalog and current user turn, then obtain a fresh user confirmation for the exact preview before execute."
            ),
            code="EFFECT_SOURCE_REJECTED",
        )
    return {
        "schema_version": COMPILED_SCHEMA_VERSION,
        "plan": copy.deepcopy(dict(host_plan["plan"])),
        "effect": report["effect"],
        "phase": report["phase"],
        "request_sha256": report["request_sha256"],
        "controls": copy.deepcopy(report["controls"]),
        "source_boundary": (
            "tool_result=data; user=instruction|authorization; "
            "sdk_contract=control"
        ),
    }


def _host_plan_mapping(
    host_plan: Any,
    violations: list[dict[str, str]],
) -> Mapping[str, Any]:
    if not isinstance(host_plan, Mapping):
        add_violation(violations, "HOST_PLAN_SCHEMA_INVALID", "host_plan")
        return {}
    if (
        set(host_plan) != _HOST_PLAN_FIELDS
        or host_plan.get("schema_version") != HOST_PLAN_SCHEMA_VERSION
    ):
        add_violation(violations, "HOST_PLAN_SCHEMA_INVALID", "host_plan")
    return host_plan


def _validated_plan(
    plan: Any,
    violations: list[dict[str, str]],
) -> Mapping[str, Any]:
    if not isinstance(plan, Mapping) or plan.get("schema_version") != PLAN_SCHEMA_VERSION:
        add_violation(violations, "PLAN_SCHEMA_INVALID", "host_plan.plan")
        return {}
    try:
        validate_plan(plan)
    except InputValidationError:
        add_violation(violations, "PLAN_VALIDATION_FAILED", "host_plan.plan")
    return plan


def _assess_effect_alignment(
    action: Any,
    action_report: Mapping[str, Any],
    derived_effect: str,
    derived_phase: str,
    violations: list[dict[str, str]],
) -> None:
    declared_phase = action.get("phase") if isinstance(action, Mapping) else None
    if (
        action_report.get("effect") != derived_effect
        or declared_phase != derived_phase
    ):
        add_violation(
            violations, "DECLARED_EFFECT_MISMATCH", "host_plan.action.effect"
        )


def _assess_control_sources(
    plan: Mapping[str, Any],
    supplied: Any,
    sources: Mapping[str, Any],
    violations: list[dict[str, str]],
) -> None:
    expected = _plan_control_pointers(plan)
    if not isinstance(supplied, Mapping) or set(supplied) != set(expected):
        add_violation(
            violations, "PLAN_CONTROL_SOURCES_INCOMPLETE",
            "host_plan.control_sources",
        )
        supplied = {}
    for pointer, expected_value in expected.items():
        field = f"host_plan.control_sources.{pointer}"
        source = source_for_plan(supplied.get(pointer), sources, field, violations)
        expect_sdk_source(
            source, code="PLAN_CONTROL_NOT_SDK_ORIGIN", field=field,
            violations=violations,
        )
        if source_value(source) != expected_value:
            add_violation(
                violations, "PLAN_CONTROL_VALUE_MISMATCH", field
            )


def _assess_object_coverage(
    request: Any,
    object_ids: Any,
    violations: list[dict[str, str]],
) -> None:
    if not isinstance(object_ids, list):
        return
    for index, object_id in enumerate(object_ids):
        if not _contains_value(request, object_id):
            add_violation(
                violations, "OBJECT_ID_NOT_BOUND_TO_PLAN",
                f"host_plan.action.controls.object_ids[{index}]",
            )


def _contains_value(value: Any, expected: Any) -> bool:
    if isinstance(value, Mapping):
        return any(_contains_value(item, expected) for item in value.values())
    if isinstance(value, list):
        return any(_contains_value(item, expected) for item in value)
    return value == expected


def _plan_effect(
    plan: Mapping[str, Any],
    mutation_ids: frozenset[str],
    violations: list[dict[str, str]],
) -> tuple[str, str]:
    from .plan_mutation_adapter import NAMES as mutation_names

    phases: list[str] = []
    for index, node in enumerate(plan.get("nodes", [])):
        if not isinstance(node, Mapping) or not isinstance(node.get("request"), Mapping):
            continue
        request = node["request"]
        if node.get("kind") == "composite" and request.get("name") in mutation_names:
            mode = request.get("mode")
            if mode in {"preview", "execute"}:
                phases.append(str(mode))
            else:
                add_violation(
                    violations, "MUTATION_PHASE_INVALID",
                    f"host_plan.plan.nodes[{index}]",
                )
        elif node.get("kind") == "run" and request.get("selector") in mutation_ids:
            phases.append("execute")
    if not phases:
        return "read", "read"
    if len(set(phases)) != 1:
        add_violation(
            violations, "MIXED_MUTATION_PHASES", "host_plan.plan.nodes"
        )
    return "mutation", phases[0]


def _plan_control_pointers(plan: Mapping[str, Any]) -> dict[str, Any]:
    pointers: dict[str, Any] = {}
    for index, node in enumerate(plan.get("nodes", [])):
        if not isinstance(node, Mapping):
            continue
        base = f"/nodes/{index}"
        pointers[f"{base}/kind"] = node.get("kind")
        request = node.get("request")
        if not isinstance(request, Mapping):
            continue
        for key in _PLAN_SELECTOR_FIELDS:
            if key in request:
                pointers[f"{base}/request/{key}"] = request[key]
        nested = request.get("inputs")
        if isinstance(nested, Mapping) and isinstance(nested.get("action"), str):
            pointers[f"{base}/request/inputs/action"] = nested["action"]
    return pointers


__all__ = [
    "ACTION_SCHEMA_VERSION",
    "COMPILED_SCHEMA_VERSION",
    "CONFIRMATION_SCHEMA_VERSION",
    "HOST_PLAN_SCHEMA_VERSION",
    "PERMISSION_SCHEMA_VERSION",
    "SOURCE_SCHEMA_VERSION",
    "assess_host_action",
    "assess_host_plan",
    "compile_host_plan",
    "host_source",
    "host_effect_schema",
    "normalized_host_plan_request",
]
