"""Typed same-layer Capability Contracts and current provider fingerprints."""

from __future__ import annotations

import copy
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

from .agent_runtime_contracts import (
    AgentRuntimeContractError,
    canonical_digest,
    load_json_object,
    validate_schema,
)
from .fingerprints import contract_fingerprint
from .models import OperationSpec, load_operation_manifest


SCHEMA_VERSION = "gravity.capability.v1"
_SCHEMA_NAME = "capability-v1.schema.json"
_PACKAGE_ROOT = Path(__file__).resolve().parent
_CAPABILITY_ROOT = _PACKAGE_ROOT / "contracts" / "capabilities"
_MANIFEST_ROOT = _PACKAGE_ROOT / "manifests"


class CapabilityContractError(AgentRuntimeContractError):
    """A same-layer Capability Contract is invalid or ambiguous."""


def capability_contracts() -> tuple[dict[str, Any], ...]:
    return tuple(
        copy.deepcopy(artifact)
        for _, artifact in sorted(
            _capability_artifacts().items(), key=lambda item: item[0]
        )
    )


def capability_contract(
    identity_kind: str, selector: str
) -> dict[str, Any] | None:
    artifact = _capability_artifacts().get((identity_kind, selector))
    return copy.deepcopy(artifact) if artifact is not None else None


def current_provider_fingerprint(contract: Mapping[str, Any]) -> str | None:
    provider_kind = contract["provider"]["kind"]
    if provider_kind == "operation_manifest":
        operation = _operations().get(str(contract["selector"]))
        return contract_fingerprint(operation) if operation is not None else None
    if provider_kind == "agent_product_card":
        return _product_card_fingerprints().get(str(contract["selector"]))
    if provider_kind == "analysis_playbook":
        from .analysis_playbook_catalog import (
            PLAYBOOK_ID,
            PLAYBOOK_VERSION,
            playbook_definition_fingerprint,
        )

        expected = f"{PLAYBOOK_ID}@{PLAYBOOK_VERSION}"
        if contract["selector"] != expected:
            return None
        return playbook_definition_fingerprint()
    raise CapabilityContractError("Capability provider kind is unsupported")


def load_declared_capability_contract(path: Path) -> dict[str, Any]:
    value = load_json_object(path, f"Capability Contract {path.name}")
    try:
        validate_schema(value, _SCHEMA_NAME, f"Capability Contract {path.name}")
    except AgentRuntimeContractError as exc:
        raise CapabilityContractError(str(exc)) from exc
    if value["identity_kind"] == "operation":
        raise CapabilityContractError(
            "checked-in Capability Contracts cannot shadow Operation manifests"
        )
    return value


@lru_cache(maxsize=1)
def _capability_artifacts() -> dict[tuple[str, str], dict[str, Any]]:
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for operation in _operations().values():
        if operation.stability != "stable":
            continue
        contract = _operation_contract(operation)
        result[("operation", operation.operation_id)] = _artifact(contract)
    for path in sorted(_CAPABILITY_ROOT.glob("*.json")):
        contract = load_declared_capability_contract(path)
        key = str(contract["identity_kind"]), str(contract["selector"])
        if key in result:
            raise CapabilityContractError("Capability identity is duplicated")
        result[key] = _artifact(contract)
    _validate_dependencies(result)
    return result


def _operation_contract(operation: OperationSpec) -> dict[str, Any]:
    return {
        "artifact_kind": "capability",
        "schema_version": SCHEMA_VERSION,
        "identity_kind": "operation",
        "selector": operation.operation_id,
        "contract_version": operation.contract_version,
        "display_name": operation.operation_id,
        "lifecycle": "active",
        "owner": f"gravity-runtime/{operation.domain}",
        "effect": operation.effect,
        "privacy_classification": operation.privacy_policy.classification,
        "provider": {
            "kind": "operation_manifest",
            "fingerprint": contract_fingerprint(operation),
        },
        "dependencies": [],
        "declared_completeness": operation.pagination.completeness,
        "required_data_quality": "pass",
        "allowed_claims": [],
        "validation_ttl_seconds": 86400,
    }


def _artifact(contract: Mapping[str, Any]) -> dict[str, Any]:
    value = copy.deepcopy(dict(contract))
    try:
        validate_schema(value, _SCHEMA_NAME, "Capability Contract")
    except AgentRuntimeContractError as exc:
        raise CapabilityContractError(str(exc)) from exc
    return {"contract": value, "digest": canonical_digest(value)}


@lru_cache(maxsize=1)
def _operations() -> dict[str, OperationSpec]:
    result: dict[str, OperationSpec] = {}
    for path in sorted(_MANIFEST_ROOT.glob("*.json")):
        for operation in load_operation_manifest(path):
            if operation.operation_id in result:
                raise CapabilityContractError("compiled Operation identity is duplicated")
            result[operation.operation_id] = operation
    if not result:
        raise CapabilityContractError("compiled Operation catalog is empty")
    return result


@lru_cache(maxsize=1)
def _product_card_fingerprints() -> dict[str, str]:
    from .agents.product_inventory import canonical_capability_cards

    cards = canonical_capability_cards(None)
    return {
        str(card["selector"]): canonical_digest(card)
        for card in cards
    }


def _validate_dependencies(
    artifacts: Mapping[tuple[str, str], Mapping[str, Any]],
) -> None:
    graph: dict[tuple[str, str], tuple[tuple[str, str], ...]] = {}
    for key, artifact in artifacts.items():
        dependencies: list[tuple[str, str]] = []
        for dependency in artifact["contract"]["dependencies"]:
            target = (
                str(dependency["identity_kind"]),
                str(dependency["selector"]),
            )
            selected = artifacts.get(target)
            if selected is None:
                raise CapabilityContractError("Capability dependency is missing")
            if (
                selected["contract"]["contract_version"]
                != dependency["contract_version"]
            ):
                raise CapabilityContractError("Capability dependency version drifted")
            dependencies.append(target)
        graph[key] = tuple(dependencies)
    _reject_cycles(graph)


def _reject_cycles(
    graph: Mapping[tuple[str, str], tuple[tuple[str, str], ...]],
) -> None:
    visiting: set[tuple[str, str]] = set()
    complete: set[tuple[str, str]] = set()

    def visit(node: tuple[str, str]) -> None:
        if node in complete:
            return
        if node in visiting:
            raise CapabilityContractError("Capability dependency graph contains a cycle")
        visiting.add(node)
        for child in graph[node]:
            visit(child)
        visiting.remove(node)
        complete.add(node)

    for identity in graph:
        visit(identity)


__all__ = [
    "CapabilityContractError",
    "SCHEMA_VERSION",
    "capability_contract",
    "capability_contracts",
    "current_provider_fingerprint",
    "load_declared_capability_contract",
]
