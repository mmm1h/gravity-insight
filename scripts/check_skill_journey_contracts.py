"""Fail closed when linked Skill, Journey, Capability, and Model contracts drift."""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re
import sys
from typing import Any

from gravity_insight.agent_runtime_contracts import (
    AgentRuntimeContractError,
    load_json_object,
)
from gravity_insight.capability_contract import capability_contracts
from gravity_insight.capability_trust import assess_declared_capability_requirement
from gravity_insight.journey_contract import load_journey_contract
from gravity_insight.model_contract import load_model_artifact
from gravity_insight.skill_contract import load_skill_manifest, skill_uri


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = "gravity.skill-journey-contract-gate.v3"
_SKILL_ROOT = Path("skills/library")
_JOURNEY_ROOT = Path("src/gravity_insight/contracts/journeys")
_MODEL_ROOT = Path("src/gravity_insight/contracts/models")
_JOURNEY_AUXILIARY_FILES = frozenset({"ledger-snapshot.v1.json"})
_CLAIM_ID = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
_MODEL_CLAIM_FIELDS = ("validated", "scenario", "forbidden")
# These concepts have no exact Skill/Journey counterpart. Keeping literal IDs
# avoids widening them into invented-confidence or a domain-specific guarantee.
_MODEL_ONLY_CLAIM_IDS = frozenset(
    {
        "deterministic-scenario-over-caller-bound-parameters",
        "guaranteed-future-outcome",
        "project-accuracy-guarantee",
        "unvalidated-project-calibration-scenario",
    }
)
_DEPENDENCY_FIELDS = (
    ("capability_dependencies", "required_capabilities"),
    ("semantic_dependencies", "required_semantics"),
    ("operator_dependencies", "required_operators"),
    ("model_dependencies", "required_models"),
)
_REQUEST_BUDGET_FIELDS = (
    "known_requests_min",
    "known_requests_max",
    "unknown_discovery_max",
    "runtime_additional_requests",
)


@dataclass(frozen=True, order=True)
class Finding:
    skill_id: str
    journey_id: str
    model_uri: str
    detector: str
    detail: str
    capability_id: str = "<none>"
    dependency_kind: str = "<none>"
    dependency_selector: str = "<none>"
    dimension: str = "<none>"


def _canonical_items(values: Sequence[Any]) -> list[str]:
    return sorted(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        for value in values
    )


def _finding(
    skill_id: str,
    journey_id: str,
    detector: str,
    detail: str,
    *,
    model_uri: str = "<none>",
    capability_id: str = "<none>",
    dependency_kind: str = "<none>",
    dependency_selector: str = "<none>",
    dimension: str = "<none>",
) -> Finding:
    return Finding(
        skill_id=skill_id,
        journey_id=journey_id,
        model_uri=model_uri,
        detector=detector,
        detail=detail,
        capability_id=capability_id,
        dependency_kind=dependency_kind,
        dependency_selector=dependency_selector,
        dimension=dimension,
    )


def _claim_vocabulary(
    skills: Sequence[Mapping[str, Any]], journeys: Sequence[Mapping[str, Any]]
) -> set[str]:
    claims = set(_MODEL_ONLY_CLAIM_IDS)
    for skill in skills:
        policy = skill["claim_policy"]
        for field in ("allowed", "forbidden", "forbidden_without_context"):
            claims.update(str(value) for value in policy[field])
    for journey in journeys:
        policy = journey["claim_policy"]
        for field in ("allowed", "forbidden"):
            claims.update(str(value) for value in policy[field])
    return claims


def _check_model_claims(
    model: Mapping[str, Any], vocabulary: set[str]
) -> list[Finding]:
    model_uri = str(model["uri"])
    findings: list[Finding] = []
    for field in _MODEL_CLAIM_FIELDS:
        for claim in model["claim_policy"][field]:
            value = str(claim)
            if _CLAIM_ID.fullmatch(value) is None:
                findings.append(
                    _finding(
                        "<none>",
                        "<none>",
                        "model-claim-id-invalid",
                        f"Model claim_policy.{field} contains a non-canonical claim ID: {value!r}",
                        model_uri=model_uri,
                    )
                )
            elif value not in vocabulary:
                findings.append(
                    _finding(
                        "<none>",
                        "<none>",
                        "model-claim-id-unknown",
                        f"Model claim_policy.{field} references an unknown canonical claim ID: {value!r}",
                        model_uri=model_uri,
                    )
                )
    return findings


def _check_link(skill: Mapping[str, Any], journey: Mapping[str, Any]) -> list[Finding]:
    skill_id = str(skill["skill_id"])
    journey_id = str(journey["journey_id"])
    findings: list[Finding] = []
    expected_skill = skill_uri(skill)
    if journey["required_skill"] != expected_skill:
        findings.append(
            _finding(
                skill_id,
                journey_id,
                "journey-required-skill-mismatch",
                f"Journey required_skill={journey['required_skill']!r}; expected {expected_skill!r}",
            )
        )

    for skill_field, journey_field in _DEPENDENCY_FIELDS:
        skill_values = _canonical_items(skill[skill_field])
        journey_values = _canonical_items(journey[journey_field])
        if skill_values != journey_values:
            findings.append(
                _finding(
                    skill_id,
                    journey_id,
                    "skill-journey-dependency-mismatch",
                    f"{skill_field}={skill_values!r}; {journey_field}={journey_values!r}",
                )
            )

    skill_context = _canonical_items(skill["context_dependencies"]["required"])
    journey_context = _canonical_items(journey["required_context"])
    if skill_context != journey_context:
        findings.append(
            _finding(
                skill_id,
                journey_id,
                "skill-journey-dependency-mismatch",
                "context_dependencies.required="
                f"{skill_context!r}; required_context={journey_context!r}",
            )
        )

    for dimension in ("completeness", "data_quality"):
        skill_value = skill["requirements"][dimension]
        journey_value = journey["required_capabilities"][0][dimension]
        if skill_value != journey_value:
            findings.append(
                _finding(
                    skill_id,
                    journey_id,
                    "skill-journey-requirement-mismatch",
                    f"requirements.{dimension}={skill_value!r}; first Journey "
                    f"Capability requirement {dimension}={journey_value!r}",
                    dimension=dimension,
                )
            )

    budget_drift = [
        f"{field}: skill={skill['request_budget'][field]!r}, "
        f"journey={journey['request_budget'][field]!r}"
        for field in _REQUEST_BUDGET_FIELDS
        if skill["request_budget"][field] != journey["request_budget"][field]
    ]
    if budget_drift:
        findings.append(
            _finding(
                skill_id,
                journey_id,
                "skill-journey-request-budget-mismatch",
                "; ".join(budget_drift),
            )
        )

    skill_allowed = set(skill["claim_policy"]["allowed"])
    skill_forbidden = set(skill["claim_policy"]["forbidden"])
    journey_allowed = set(journey["claim_policy"]["allowed"])
    journey_forbidden = set(journey["claim_policy"]["forbidden"])
    outside = sorted(skill_allowed - journey_allowed)
    if outside:
        findings.append(
            _finding(
                skill_id,
                journey_id,
                "skill-allowed-claims-outside-journey",
                f"Skill allows claims absent from Journey allowed: {outside!r}",
            )
        )
    forbidden = sorted(skill_allowed & journey_forbidden)
    if forbidden:
        findings.append(
            _finding(
                skill_id,
                journey_id,
                "skill-allowed-claims-forbidden-by-journey",
                f"Skill allows claims forbidden by Journey: {forbidden!r}",
            )
        )
    missing_forbidden = sorted(journey_forbidden - skill_forbidden)
    if missing_forbidden:
        findings.append(
            _finding(
                skill_id,
                journey_id,
                "journey-forbidden-claims-missing-from-skill",
                f"Skill omits Journey forbidden claims: {missing_forbidden!r}",
            )
        )
    return findings


def _claim_dependency_findings(
    owner_kind: str,
    owner_id: str,
    allowed_claims: Sequence[Any],
    dependencies: Sequence[Mapping[str, Any]],
    capabilities: Mapping[tuple[str, str], Mapping[str, Any]],
) -> tuple[list[Finding], int]:
    if not allowed_claims:
        return [], 0
    findings: list[Finding] = []
    for requirement in dependencies:
        dependency_kind = str(requirement["identity_kind"])
        dependency_selector = str(requirement["selector"])
        dependency = capabilities.get((dependency_kind, dependency_selector))
        common = {
            "capability_id": owner_id if owner_kind == "capability" else "<none>",
            "dependency_kind": dependency_kind,
            "dependency_selector": dependency_selector,
        }
        owner_fields = {
            "skill_id": owner_id if owner_kind == "skill" else "<none>",
            "journey_id": owner_id if owner_kind == "journey" else "<none>",
        }
        if dependency is None:
            findings.append(
                _finding(
                    owner_fields["skill_id"],
                    owner_fields["journey_id"],
                    "claim-dependency-contract-missing",
                    f"{owner_kind} {owner_id!r} publishes claims but dependency "
                    f"{dependency_kind}:{dependency_selector} has no Capability contract",
                    dimension="contract",
                    **common,
                )
            )
            continue
        if dependency["contract_version"] != requirement["contract_version"]:
            findings.append(
                _finding(
                    owner_fields["skill_id"],
                    owner_fields["journey_id"],
                    "claim-dependency-version-unreachable",
                    f"{owner_kind} {owner_id!r} publishes claims but requires "
                    f"{dependency_kind}:{dependency_selector} contract_version="
                    f"{requirement['contract_version']!r}; current declared value is "
                    f"{dependency['contract_version']!r}",
                    dimension="contract_version",
                    **common,
                )
            )
            continue
        status, reasons = assess_declared_capability_requirement(
            dependency, requirement
        )
        if status == "stable":
            continue
        for reason in reasons:
            dimension = _requirement_dimension(reason)
            findings.append(
                _finding(
                    owner_fields["skill_id"],
                    owner_fields["journey_id"],
                    "claim-dependency-requirement-unreachable",
                    f"{owner_kind} {owner_id!r} publishes claims but dependency "
                    f"{dependency_kind}:{dependency_selector} cannot satisfy "
                    f"{dimension}: required={requirement[dimension]!r}, "
                    f"current_declared={_declared_value(dependency, dimension)!r}; "
                    f"runtime_reason={reason}",
                    dimension=dimension,
                    **common,
                )
            )
    return findings, len(dependencies)


def _requirement_dimension(reason: str) -> str:
    if reason == "COMPLETENESS_INSUFFICIENT":
        return "completeness"
    if reason in {
        "DEPENDENCY_BLOCKED",
        "DEPENDENCY_QUARANTINED",
        "DEPENDENCY_TRUST_INSUFFICIENT",
        "DEPENDENCY_VALIDATION_UNKNOWN",
    }:
        return "minimum_trust"
    return "data_quality"


def _declared_value(dependency: Mapping[str, Any], dimension: str) -> Any:
    if dimension == "completeness":
        return dependency["declared_completeness"]
    if dimension == "minimum_trust":
        return dependency["lifecycle"]
    return "pass (best case)"


def check_contracts(
    skills: Sequence[Mapping[str, Any]],
    journeys: Sequence[Mapping[str, Any]],
    models: Sequence[Mapping[str, Any]],
    *,
    capabilities: Sequence[Mapping[str, Any]] | None = None,
    initial_findings: Sequence[Finding] = (),
    scanned_skill_files: int | None = None,
    scanned_journey_files: int | None = None,
    scanned_model_files: int | None = None,
) -> tuple[int, dict[str, Any]]:
    findings = list(initial_findings)
    skills_by_uri: dict[str, Mapping[str, Any]] = {}
    journeys_by_id: dict[str, Mapping[str, Any]] = {}
    models_by_uri: dict[str, Mapping[str, Any]] = {}
    capabilities_by_id: dict[tuple[str, str], Mapping[str, Any]] = {}
    for skill in skills:
        uri = skill_uri(skill)
        if uri in skills_by_uri:
            findings.append(
                _finding(
                    str(skill["skill_id"]),
                    "<none>",
                    "duplicate-skill-uri",
                    f"Skill URI is duplicated: {uri!r}",
                )
            )
        else:
            skills_by_uri[uri] = skill
    for journey in journeys:
        journey_id = str(journey["journey_id"])
        if journey_id in journeys_by_id:
            findings.append(
                _finding(
                    "<none>",
                    journey_id,
                    "duplicate-journey-id",
                    "Journey ID is duplicated",
                )
            )
        else:
            journeys_by_id[journey_id] = journey
    for model in models:
        model_uri = str(model["uri"])
        if model_uri in models_by_uri:
            findings.append(
                _finding(
                    "<none>",
                    "<none>",
                    "duplicate-model-uri",
                    f"Model URI is duplicated: {model_uri!r}",
                    model_uri=model_uri,
                )
            )
        else:
            models_by_uri[model_uri] = model
    capability_values = tuple(capabilities or ())
    reachability_enabled = capabilities is not None
    for capability in capability_values:
        identity = (
            str(capability["identity_kind"]),
            str(capability["selector"]),
        )
        if identity in capabilities_by_id:
            findings.append(
                _finding(
                    "<none>",
                    "<none>",
                    "duplicate-capability-identity",
                    f"Capability identity is duplicated: {identity!r}",
                    capability_id=f"{identity[0]}:{identity[1]}",
                )
            )
        else:
            capabilities_by_id[identity] = capability

    vocabulary = _claim_vocabulary(skills, journeys)
    for model in models:
        findings.extend(_check_model_claims(model, vocabulary))

    checked_links = 0
    checked_skill_model_links = 0
    checked_journey_model_links = 0
    linked_skills: set[str] = set()
    referenced_models: set[str] = set()
    claim_publishers = 0
    claim_bearing_capabilities = 0
    checked_claim_dependencies = 0
    for capability in capability_values:
        allowed_claims = capability["allowed_claims"]
        if allowed_claims:
            claim_publishers += 1
            claim_bearing_capabilities += 1
        selected, checked = _claim_dependency_findings(
            "capability",
            f"{capability['identity_kind']}:{capability['selector']}",
            allowed_claims,
            capability["dependencies"],
            capabilities_by_id,
        )
        findings.extend(selected)
        checked_claim_dependencies += checked
    for skill in skills:
        skill_id = str(skill["skill_id"])
        covered = skill["covers_journeys"]
        if covered:
            linked_skills.add(skill_id)
        for journey_id in covered:
            checked_links += 1
            journey = journeys_by_id.get(str(journey_id))
            if journey is None:
                findings.append(
                    _finding(
                        skill_id,
                        str(journey_id),
                        "skill-journey-reference-missing",
                        "covers_journeys references an unknown Journey ID",
                    )
                )
                continue
            findings.extend(_check_link(skill, journey))

        skill_allowed = set(skill["claim_policy"]["allowed"])
        if skill_allowed:
            claim_publishers += 1
        if reachability_enabled:
            selected, checked = _claim_dependency_findings(
                "skill",
                skill_id,
                tuple(skill_allowed),
                skill["capability_dependencies"],
                capabilities_by_id,
            )
            findings.extend(selected)
            checked_claim_dependencies += checked
        for dependency in skill["model_dependencies"]:
            checked_skill_model_links += 1
            model_uri = str(dependency)
            referenced_models.add(model_uri)
            model = models_by_uri.get(model_uri)
            if model is None:
                findings.append(
                    _finding(
                        skill_id,
                        "<none>",
                        "skill-model-reference-missing",
                        "Skill model_dependencies references an unknown Model URI",
                        model_uri=model_uri,
                    )
                )
                continue
            forbidden = sorted(
                skill_allowed & set(model["claim_policy"]["forbidden"])
            )
            if forbidden:
                findings.append(
                    _finding(
                        skill_id,
                        "<none>",
                        "skill-allowed-claims-forbidden-by-model",
                        f"Skill allows claims forbidden by Model: {forbidden!r}",
                        model_uri=model_uri,
                    )
                )

    for journey in journeys:
        journey_id = str(journey["journey_id"])
        journey_allowed = set(journey["claim_policy"]["allowed"])
        if journey_allowed:
            claim_publishers += 1
        if reachability_enabled:
            selected, checked = _claim_dependency_findings(
                "journey",
                journey_id,
                tuple(journey_allowed),
                journey["required_capabilities"],
                capabilities_by_id,
            )
            findings.extend(selected)
            checked_claim_dependencies += checked
        for dependency in journey["required_models"]:
            checked_journey_model_links += 1
            model_uri = str(dependency)
            referenced_models.add(model_uri)
            model = models_by_uri.get(model_uri)
            if model is None:
                findings.append(
                    _finding(
                        "<none>",
                        journey_id,
                        "journey-model-reference-missing",
                        "Journey required_models references an unknown Model URI",
                        model_uri=model_uri,
                    )
                )
                continue
            forbidden = sorted(
                journey_allowed & set(model["claim_policy"]["forbidden"])
            )
            if forbidden:
                findings.append(
                    _finding(
                        "<none>",
                        journey_id,
                        "journey-allowed-claims-forbidden-by-model",
                        f"Journey allows claims forbidden by Model: {forbidden!r}",
                        model_uri=model_uri,
                    )
                )

        required_skill = journey["required_skill"]
        if required_skill is None:
            continue
        skill = skills_by_uri.get(str(required_skill))
        if skill is None:
            findings.append(
                _finding(
                    str(required_skill),
                    journey_id,
                    "journey-required-skill-missing",
                    "Journey required_skill references an unknown Skill URI",
                )
            )
        elif journey_id not in skill["covers_journeys"]:
            findings.append(
                _finding(
                    str(skill["skill_id"]),
                    journey_id,
                    "journey-skill-backlink-missing",
                    "Journey required_skill is not reciprocated by covers_journeys",
                )
            )

    findings.sort()
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "status": "pass" if not findings else "fail",
        "finding_count": len(findings),
        "findings": [asdict(finding) for finding in findings],
        "scanned_skill_files": (
            len(skills) if scanned_skill_files is None else scanned_skill_files
        ),
        "scanned_journey_files": (
            len(journeys) if scanned_journey_files is None else scanned_journey_files
        ),
        "scanned_model_files": (
            len(models) if scanned_model_files is None else scanned_model_files
        ),
        "skill_contract_count": len(skills),
        "journey_contract_count": len(journeys),
        "model_contract_count": len(models),
        "capability_contract_count": len(capability_values),
        "claim_bearing_capability_count": claim_bearing_capabilities,
        "claim_publisher_count": claim_publishers,
        "checked_claim_dependency_count": checked_claim_dependencies,
        "linked_skill_count": len(linked_skills),
        "checked_link_count": checked_links,
        "referenced_model_count": len(referenced_models),
        "checked_skill_model_link_count": checked_skill_model_links,
        "checked_journey_model_link_count": checked_journey_model_links,
    }
    return (1 if findings else 0), receipt


def check_repository(root: Path = ROOT) -> tuple[int, dict[str, Any]]:
    skill_root = root / _SKILL_ROOT
    journey_root = root / _JOURNEY_ROOT
    model_root = root / _MODEL_ROOT
    findings: list[Finding] = []
    skill_files = sorted(skill_root.glob("*.json")) if skill_root.is_dir() else []
    journey_files = (
        sorted(journey_root.glob("*.json")) if journey_root.is_dir() else []
    )
    model_files = sorted(model_root.glob("*.json")) if model_root.is_dir() else []
    if not skill_root.is_dir():
        findings.append(
            _finding(
                "<registry>",
                "<none>",
                "skill-scan-root-missing",
                f"required scan root is absent: {_SKILL_ROOT.as_posix()}",
            )
        )
    elif not skill_files:
        findings.append(
            _finding(
                "<registry>",
                "<none>",
                "skill-registry-empty",
                "Skill registry contains no JSON contracts",
            )
        )
    if not journey_root.is_dir():
        findings.append(
            _finding(
                "<none>",
                "<registry>",
                "journey-scan-root-missing",
                f"required scan root is absent: {_JOURNEY_ROOT.as_posix()}",
            )
        )
    elif not journey_files:
        findings.append(
            _finding(
                "<none>",
                "<registry>",
                "journey-registry-empty",
                "Journey registry contains no JSON contracts",
            )
        )
    if not model_root.is_dir():
        findings.append(
            _finding(
                "<none>",
                "<none>",
                "model-scan-root-missing",
                f"required scan root is absent: {_MODEL_ROOT.as_posix()}",
                model_uri="<registry>",
            )
        )
    elif not model_files:
        findings.append(
            _finding(
                "<none>",
                "<none>",
                "model-registry-empty",
                "Model registry contains no JSON contracts",
                model_uri="<registry>",
            )
        )

    skills: list[dict[str, Any]] = []
    for path in skill_files:
        try:
            skills.append(load_skill_manifest(path))
        except (AgentRuntimeContractError, OSError, TypeError, ValueError) as exc:
            findings.append(
                _finding(
                    path.relative_to(root).as_posix(),
                    "<none>",
                    "skill-contract-invalid",
                    str(exc),
                )
            )

    journeys: list[dict[str, Any]] = []
    for path in journey_files:
        relative = path.relative_to(root).as_posix()
        try:
            document = load_json_object(path, f"Journey registry file {path.name}")
            if path.name in _JOURNEY_AUXILIARY_FILES:
                continue
            if document.get("artifact_kind") != "journey":
                findings.append(
                    _finding(
                        "<none>",
                        relative,
                        "journey-artifact-kind-invalid",
                        "Journey registry JSON is neither a Journey nor a registered auxiliary file",
                    )
                )
                continue
            journeys.append(load_journey_contract(path))
        except (AgentRuntimeContractError, OSError, TypeError, ValueError) as exc:
            findings.append(
                _finding(
                    "<none>",
                    relative,
                    "journey-contract-invalid",
                    str(exc),
                )
            )

    models: list[dict[str, Any]] = []
    for path in model_files:
        relative = path.relative_to(root).as_posix()
        try:
            document = load_json_object(path, f"Model registry file {path.name}")
            if document.get("artifact_kind") != "model":
                findings.append(
                    _finding(
                        "<none>",
                        "<none>",
                        "model-artifact-kind-invalid",
                        "Model registry JSON is not a Model Artifact",
                        model_uri=relative,
                    )
                )
                continue
            models.append(load_model_artifact(path)["contract"])
        except (AgentRuntimeContractError, OSError, TypeError, ValueError) as exc:
            findings.append(
                _finding(
                    "<none>",
                    "<none>",
                    "model-contract-invalid",
                    str(exc),
                    model_uri=relative,
                )
            )

    capabilities: list[dict[str, Any]] = []
    try:
        capabilities = [
            artifact["contract"] for artifact in capability_contracts()
        ]
    except (AgentRuntimeContractError, OSError, TypeError, ValueError) as exc:
        findings.append(
            _finding(
                "<none>",
                "<none>",
                "capability-contract-registry-invalid",
                str(exc),
                capability_id="<registry>",
                dimension="contract",
            )
        )

    return check_contracts(
        skills,
        journeys,
        models,
        capabilities=capabilities,
        initial_findings=findings,
        scanned_skill_files=len(skill_files),
        scanned_journey_files=len(journey_files),
        scanned_model_files=len(model_files),
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    code, receipt = check_repository(args.root.resolve())
    rendered = json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8", newline="\n")
    sys.stdout.write(rendered)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
