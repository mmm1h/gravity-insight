"""Fail closed when linked Skill and Journey contracts drift."""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import sys
from typing import Any

from gravity_insight.agent_runtime_contracts import (
    AgentRuntimeContractError,
    load_json_object,
)
from gravity_insight.journey_contract import load_journey_contract
from gravity_insight.skill_contract import load_skill_manifest, skill_uri


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = "gravity.skill-journey-contract-gate.v1"
_SKILL_ROOT = Path("skills/library")
_JOURNEY_ROOT = Path("src/gravity_insight/contracts/journeys")
_JOURNEY_AUXILIARY_FILES = frozenset({"ledger-snapshot.v1.json"})
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
    detector: str
    detail: str


def _canonical_items(values: Sequence[Any]) -> list[str]:
    return sorted(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        for value in values
    )


def _finding(
    skill_id: str, journey_id: str, detector: str, detail: str
) -> Finding:
    return Finding(
        skill_id=skill_id,
        journey_id=journey_id,
        detector=detector,
        detail=detail,
    )


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


def check_contracts(
    skills: Sequence[Mapping[str, Any]],
    journeys: Sequence[Mapping[str, Any]],
    *,
    initial_findings: Sequence[Finding] = (),
    scanned_skill_files: int | None = None,
    scanned_journey_files: int | None = None,
) -> tuple[int, dict[str, Any]]:
    findings = list(initial_findings)
    skills_by_uri: dict[str, Mapping[str, Any]] = {}
    journeys_by_id: dict[str, Mapping[str, Any]] = {}
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

    checked_links = 0
    linked_skills: set[str] = set()
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

    for journey in journeys:
        required_skill = journey["required_skill"]
        if required_skill is None:
            continue
        journey_id = str(journey["journey_id"])
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
        "skill_contract_count": len(skills),
        "journey_contract_count": len(journeys),
        "linked_skill_count": len(linked_skills),
        "checked_link_count": checked_links,
    }
    return (1 if findings else 0), receipt


def check_repository(root: Path = ROOT) -> tuple[int, dict[str, Any]]:
    skill_root = root / _SKILL_ROOT
    journey_root = root / _JOURNEY_ROOT
    findings: list[Finding] = []
    skill_files = sorted(skill_root.glob("*.json")) if skill_root.is_dir() else []
    journey_files = (
        sorted(journey_root.glob("*.json")) if journey_root.is_dir() else []
    )
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

    return check_contracts(
        skills,
        journeys,
        initial_findings=findings,
        scanned_skill_files=len(skill_files),
        scanned_journey_files=len(journey_files),
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
