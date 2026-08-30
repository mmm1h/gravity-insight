"""Offline transitive impact projection for Capability contract changes."""

from __future__ import annotations

import copy
from collections import deque
from collections.abc import Mapping
from typing import Any

from .actionable_error_values import actual_value
from .capability_contract import capability_contracts
from .errors import InputValidationError
from .journey_contract import journey_artifacts


SCHEMA_VERSION = "gravity.capability-impact.v1"
REQUEST_SCHEMA_VERSION = "gravity.capability-impact-request.v1"
_IDENTITY_KINDS = frozenset({"operation", "product", "composite"})
_CHANGE_REASONS = {
    "provider_fingerprint_changed": "CAPABILITY_PROVIDER_CHANGED",
    "contract_changed": "CAPABILITY_CONTRACT_CHANGED",
    "lifecycle_changed": "CAPABILITY_LIFECYCLE_CHANGED",
    "validation_changed": "CAPABILITY_VALIDATION_CHANGED",
    "data_quality_changed": "CAPABILITY_DATA_QUALITY_CHANGED",
}


def capability_impact(request: Mapping[str, Any]) -> dict[str, Any]:
    """Name transitive Capability, Skill, and Journey impact without execution."""

    changes = _changes(request)
    artifacts = {
        (
            str(item["contract"]["identity_kind"]),
            str(item["contract"]["selector"]),
        ): item
        for item in capability_contracts()
    }
    reverse = _reverse_dependencies(artifacts)
    causes: dict[tuple[str, str], set[tuple[str, str, str]]] = {}
    for change in changes:
        source = (change["identity_kind"], change["selector"])
        cause = (*source, change["change_kind"])
        queue = deque([source])
        visited: set[tuple[str, str]] = set()
        while queue:
            current = queue.popleft()
            if current in visited:
                continue
            visited.add(current)
            causes.setdefault(current, set()).add(cause)
            queue.extend(reverse.get(current, ()))

    affected_capabilities = [
        _capability_impact_row(identity, causes[identity], artifacts.get(identity))
        for identity in sorted(causes)
    ]
    affected_skills: dict[str, set[str]] = {}
    affected_journeys: list[dict[str, Any]] = []
    for artifact in journey_artifacts():
        contract = artifact["contract"]
        required = {
            (str(item["identity_kind"]), str(item["selector"]))
            for item in contract["required_capabilities"]
        }
        selected = required.intersection(causes)
        if not selected:
            continue
        reasons = sorted(
            {
                _CHANGE_REASONS[cause[2]]
                for identity in selected
                for cause in causes[identity]
            }
        )
        journey_id = str(contract["journey_id"])
        affected_journeys.append(
            {
                "journey_id": journey_id,
                "version": contract["version"],
                "reason_codes": reasons,
            }
        )
        skill_uri = contract.get("required_skill")
        if isinstance(skill_uri, str) and skill_uri:
            affected_skills.setdefault(skill_uri, set()).update(reasons)

    result = {
        "schema_version": SCHEMA_VERSION,
        "status": "affected" if causes else "unaffected",
        "changes": copy.deepcopy(changes),
        "affected_capabilities": affected_capabilities,
        "affected_skills": [
            {"skill_uri": uri, "reason_codes": sorted(reasons)}
            for uri, reasons in sorted(affected_skills.items())
        ],
        "affected_journeys": sorted(
            affected_journeys, key=lambda item: item["journey_id"]
        ),
        "network_called": False,
    }
    return result


def _changes(request: Mapping[str, Any]) -> list[dict[str, str]]:
    if not isinstance(request, Mapping) or set(request) != {
        "schema_version",
        "changes",
    }:
        raise InputValidationError(
            "actual value: invalid shape; Capability impact input must contain "
            "schema_version and changes",
            field="input",
        )
    if request.get("schema_version") != REQUEST_SCHEMA_VERSION:
        raise InputValidationError(
            f"actual value: {actual_value(request.get('schema_version'))}; "
            f"schema_version must be {REQUEST_SCHEMA_VERSION}",
            field="schema_version",
        )
    raw = request.get("changes")
    if not isinstance(raw, list) or not 1 <= len(raw) <= 64:
        raise InputValidationError(
            "actual value: invalid changes; changes must contain 1..64 entries",
            field="changes",
        )
    result: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for index, item in enumerate(raw):
        if not isinstance(item, Mapping) or set(item) != {
            "identity_kind",
            "selector",
            "change_kind",
        }:
            raise InputValidationError(
                "actual value: invalid change; every change must contain "
                "identity_kind, selector, and change_kind",
                field=f"changes[{index}]",
            )
        identity_kind = item.get("identity_kind")
        selector = item.get("selector")
        change_kind = item.get("change_kind")
        if identity_kind not in _IDENTITY_KINDS:
            raise InputValidationError(
                f"actual value: {actual_value(identity_kind)}; identity_kind must "
                "be operation, product, or composite",
                field=f"changes[{index}].identity_kind",
            )
        if not isinstance(selector, str) or not selector.strip() or len(selector) > 256:
            raise InputValidationError(
                f"actual value: {actual_value(selector)}; selector must name one "
                "bounded Capability identity",
                field=f"changes[{index}].selector",
            )
        if change_kind not in _CHANGE_REASONS:
            raise InputValidationError(
                f"actual value: {actual_value(change_kind)}; change_kind must be one of: "
                + ", ".join(sorted(_CHANGE_REASONS)),
                field=f"changes[{index}].change_kind",
            )
        selected = (str(identity_kind), selector.strip(), str(change_kind))
        if selected in seen:
            raise InputValidationError(
                "actual value: duplicate change; Capability impact changes must be unique",
                field=f"changes[{index}]",
            )
        seen.add(selected)
        result.append(
            {
                "identity_kind": selected[0],
                "selector": selected[1],
                "change_kind": selected[2],
            }
        )
    return sorted(
        result,
        key=lambda item: (
            item["identity_kind"], item["selector"], item["change_kind"]
        ),
    )


def _reverse_dependencies(
    artifacts: Mapping[tuple[str, str], Mapping[str, Any]],
) -> dict[tuple[str, str], tuple[tuple[str, str], ...]]:
    reverse: dict[tuple[str, str], set[tuple[str, str]]] = {}
    for parent, artifact in artifacts.items():
        for dependency in artifact["contract"]["dependencies"]:
            child = (
                str(dependency["identity_kind"]),
                str(dependency["selector"]),
            )
            reverse.setdefault(child, set()).add(parent)
    return {
        child: tuple(sorted(parents)) for child, parents in reverse.items()
    }


def _capability_impact_row(
    identity: tuple[str, str],
    causes: set[tuple[str, str, str]],
    artifact: Mapping[str, Any] | None,
) -> dict[str, Any]:
    return {
        "identity_kind": identity[0],
        "selector": identity[1],
        "contract_version": (
            artifact["contract"]["contract_version"] if artifact is not None else None
        ),
        "reason_codes": sorted({_CHANGE_REASONS[cause[2]] for cause in causes}),
        "caused_by": [
            {
                "identity_kind": cause[0],
                "selector": cause[1],
                "change_kind": cause[2],
            }
            for cause in sorted(causes)
        ],
    }


__all__ = [
    "REQUEST_SCHEMA_VERSION",
    "SCHEMA_VERSION",
    "capability_impact",
]
