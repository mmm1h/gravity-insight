"""Schema-validated Built-in Skill manifests and dependency bindings."""

from __future__ import annotations

import copy
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

from .actionable_error_values import actual_value
from .agent_runtime_contracts import (
    AgentRuntimeContractError,
    canonical_digest,
    load_json_object,
    validate_schema,
)
from .capability_contract import capability_contract
from .errors import InputValidationError
from .journey_contract import journey_artifact


SCHEMA_VERSION = "gravity.skill.v1"
_SCHEMA_NAME = "skill-v1.schema.json"
_MANIFEST_ROOT = Path(__file__).resolve().parent / "contracts" / "skills"
_COMPACT_IDENTITY = re.compile(
    r"^(?P<namespace>[a-z][a-z0-9.-]*)/(?P<skill_id>[a-z0-9-]+)@(?P<version>[0-9A-Za-z.-]+)$"
)


class SkillContractError(AgentRuntimeContractError):
    """A Built-in Skill manifest or its dependency binding is invalid."""


def skill_uri(contract: Mapping[str, Any]) -> str:
    return (
        f"skill://{contract['namespace']}/{contract['skill_id']}"
        f"@{contract['version']}"
    )


def skill_artifacts() -> tuple[dict[str, Any], ...]:
    return tuple(copy.deepcopy(item) for _, item in sorted(_artifacts().items()))


def skill_artifact(identifier: str) -> dict[str, Any] | None:
    try:
        identity = normalize_skill_identity(identifier)
    except InputValidationError:
        return None
    value = _artifacts().get(identity)
    return copy.deepcopy(value) if value is not None else None


def normalize_skill_identity(identifier: Any) -> str:
    if not isinstance(identifier, str) or not identifier.strip():
        raise InputValidationError(
            f"actual value: {actual_value(identifier)}; Skill identity must be a "
            "non-empty versioned URI",
            field="skill",
            next_action="Run `gravity skills list` and use an exact skill_uri.",
        )
    selected = identifier.strip()
    compact = selected.removeprefix("skill://")
    if _COMPACT_IDENTITY.fullmatch(compact) is None:
        raise InputValidationError(
            f"actual value: {actual_value(identifier)}; Skill identity must use "
            "skill://<namespace>/<skill-id>@<version>",
            field="skill",
            next_action="Run `gravity skills list` and use an exact skill_uri.",
        )
    return "skill://" + compact


def load_skill_manifest(path: Path) -> dict[str, Any]:
    value = load_json_object(path, f"Skill manifest {path.name}")
    return compile_skill_manifest(value, label=f"Skill manifest {path.name}")


def compile_skill_manifest(
    value: Mapping[str, Any], *, label: str = "Skill manifest"
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise SkillContractError(f"{label} must be an object")
    contract = copy.deepcopy(dict(value))
    try:
        validate_schema(contract, _SCHEMA_NAME, label)
    except AgentRuntimeContractError as exc:
        raise SkillContractError(str(exc)) from exc
    if contract["request_budget"]["known_requests_min"] > contract["request_budget"]["known_requests_max"]:
        raise SkillContractError("Skill request budget range is invalid")
    if set(contract["context_dependencies"]["required"]).intersection(
        contract["context_dependencies"]["optional"]
    ):
        raise SkillContractError("Skill Context dependency cannot be required and optional")
    return contract


@lru_cache(maxsize=1)
def _artifacts() -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for path in sorted(_MANIFEST_ROOT.glob("*.json")):
        contract = load_skill_manifest(path)
        identity = skill_uri(contract)
        if identity in result:
            raise SkillContractError("Skill identity is duplicated")
        artifact = {
            "contract": contract,
            "digest": canonical_digest(contract),
            "skill_uri": identity,
        }
        _validate_dependencies(artifact)
        result[identity] = artifact
    if not result:
        raise SkillContractError("Built-in Skill registry is empty")
    return result


def _validate_dependencies(artifact: Mapping[str, Any]) -> None:
    contract = artifact["contract"]
    identity = artifact["skill_uri"]
    for journey_id in contract["covers_journeys"]:
        journey = journey_artifact(str(journey_id))
        if journey is None or journey["contract"]["required_skill"] != identity:
            raise SkillContractError("Skill Journey dependency is missing or drifted")
        if len(contract["covers_journeys"]) == 1:
            validate_skill_journey_parity(contract, journey["contract"])
    for requirement in contract["capability_dependencies"]:
        capability = capability_contract(
            str(requirement["identity_kind"]), str(requirement["selector"])
        )
        if capability is None:
            raise SkillContractError("Skill Capability dependency is missing")
        if capability["contract"]["contract_version"] != requirement["contract_version"]:
            raise SkillContractError("Skill Capability dependency version drifted")
    hints = set(contract["routing"]["product_hints"])
    selectors = {item["selector"] for item in contract["capability_dependencies"]}
    if not hints.issubset(selectors):
        raise SkillContractError("Skill routing hints are not declared dependencies")


def validate_skill_journey_parity(
    contract: Mapping[str, Any], journey: Mapping[str, Any]
) -> None:
    try:
        checks = (
            journey["journey_id"] in contract["covers_journeys"],
            contract["capability_dependencies"] == journey["required_capabilities"],
            contract["semantic_dependencies"] == journey["required_semantics"],
            contract["operator_dependencies"] == journey["required_operators"],
            contract["model_dependencies"] == journey["required_models"],
            contract["context_dependencies"]["required"]
            == journey["required_context"],
            contract["requirements"]["completeness"]
            == journey["required_capabilities"][0]["completeness"],
            contract["requirements"]["data_quality"]
            == journey["required_capabilities"][0]["data_quality"],
            contract["claim_policy"]["allowed"]
            == journey["claim_policy"]["allowed"],
            contract["claim_policy"]["forbidden"]
            == journey["claim_policy"]["forbidden"],
            contract["request_budget"]["known_requests_min"]
            == journey["request_budget"]["known_requests_min"],
            contract["request_budget"]["known_requests_max"]
            == journey["request_budget"]["known_requests_max"],
            contract["request_budget"]["unknown_discovery_max"]
            == journey["request_budget"]["unknown_discovery_max"],
            contract["request_budget"]["runtime_additional_requests"]
            == journey["request_budget"]["runtime_additional_requests"],
            contract["output_schema"] == "gravity.analysis-result.v1",
        )
    except (KeyError, IndexError, TypeError) as exc:
        raise SkillContractError(
            "Skill and Journey dependency contracts drifted"
        ) from exc
    if not all(checks):
        raise SkillContractError("Skill and Journey dependency contracts drifted")


__all__ = [
    "SCHEMA_VERSION",
    "SkillContractError",
    "compile_skill_manifest",
    "load_skill_manifest",
    "normalize_skill_identity",
    "skill_artifact",
    "skill_artifacts",
    "skill_uri",
    "validate_skill_journey_parity",
]
