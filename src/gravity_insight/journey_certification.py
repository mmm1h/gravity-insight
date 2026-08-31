"""Offline Journey certification derived from current machine contracts."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Mapping

from .capability_contract import capability_contract
from .capability_trust import CapabilityTrustService, assess_capability_requirement
from .evidence_common import git_state, load_object, relative
from .journey_contract import load_journey_contract, validate_journey_bindings
from .operator_registry import OperatorRegistry
from .paths import PROJECT_ROOT
from .skill_contract import skill_artifact


def _journey_paths(root: Path) -> list[Path]:
    return sorted(
        (root / "src/gravity_insight/contracts/journeys").glob("*.json")
    )


def _load_contracts(root: Path) -> tuple[list[tuple[Path, dict[str, Any]]], list[str]]:
    contracts: list[tuple[Path, dict[str, Any]]] = []
    errors: list[str] = []
    for path in _journey_paths(root):
        try:
            raw = load_object(path)
            if raw.get("artifact_kind") != "journey":
                continue
            contracts.append((path, load_journey_contract(path)))
        except (OSError, UnicodeError, ValueError, TypeError) as exc:
            errors.append(f"{relative(root, path)}: {type(exc).__name__}: {exc}")
    return contracts, errors


def _registry_errors(
    root: Path, contracts: list[tuple[Path, dict[str, Any]]]
) -> list[str]:
    ledger_path = root / "src/gravity_insight/contracts/journeys/ledger-snapshot.v1.json"
    try:
        validate_journey_bindings(
            [contract for _path, contract in contracts], load_object(ledger_path)
        )
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        return [f"{relative(root, ledger_path)}: {type(exc).__name__}: {exc}"]
    return []


def _dependency_reasons(
    contract: Mapping[str, Any],
    *,
    trust: CapabilityTrustService,
    operators: OperatorRegistry,
) -> tuple[list[str], list[dict[str, Any]]]:
    reasons: list[str] = []
    evidence: list[dict[str, Any]] = []
    for requirement in contract["required_capabilities"]:
        artifact = capability_contract(
            str(requirement["identity_kind"]), str(requirement["selector"])
        )
        result = trust.trust(
            str(requirement["identity_kind"]), str(requirement["selector"])
        )
        status, selected = assess_capability_requirement(result, requirement)
        if artifact is None:
            reasons.append("JOURNEY_CAPABILITY_CONTRACT_MISSING")
        if status != "stable":
            reasons.extend(selected or ["JOURNEY_CAPABILITY_UNCERTIFIED"])
        evidence.append(
            {
                "identity_kind": requirement["identity_kind"],
                "selector": requirement["selector"],
                "status": status,
                "trust_status": result.get("trust_status"),
                "completeness": result.get("completeness"),
                "data_quality": result.get("data_quality", {}).get("status"),
                "reason_codes": copy.deepcopy(result.get("reason_codes", [])),
            }
        )
    operator_result = operators.dependencies(contract["required_operators"])
    if not operator_result["ok"]:
        reasons.extend(operator_result["reason_codes"])
    if contract["required_models"]:
        reasons.append("MODEL_VALIDATION_EVIDENCE_MISSING")
    if contract["required_semantics"]:
        reasons.append("PROJECT_SEMANTIC_BINDING_EVIDENCE_MISSING")
    if contract["required_context"]:
        reasons.append("PROJECT_CONTEXT_PACK_EVIDENCE_MISSING")
    required_skill = contract["required_skill"]
    if required_skill and skill_artifact(required_skill) is None:
        reasons.append("SKILL_DEPENDENCY_MISSING")
    return list(dict.fromkeys(reasons)), evidence


def _classification(
    contract: Mapping[str, Any], certification_gaps: list[str]
) -> tuple[str, list[str]]:
    blockers: list[str] = []
    if contract["lifecycle"] != "active":
        blockers.append("JOURNEY_LIFECYCLE_NOT_ACTIVE")
    if contract["execution"]["mode"] == "unavailable":
        blockers.append("JOURNEY_EXECUTION_UNAVAILABLE")
    if any(value == "missing" for value in contract["surfaces"].values()):
        blockers.append("JOURNEY_SURFACE_MISSING")
    if blockers:
        return "blocked", blockers
    if any(value == "declared" for value in contract["surfaces"].values()):
        certification_gaps.append("JOURNEY_SURFACE_ONLY_DECLARED")
    if certification_gaps:
        return "uncertified", list(dict.fromkeys(certification_gaps))
    return "certified", []


def journey_certifications(root: Path = PROJECT_ROOT) -> dict[str, Any]:
    root = root.resolve()
    contracts, load_errors = _load_contracts(root)
    registry_errors = _registry_errors(root, contracts) if contracts else []
    trust = CapabilityTrustService()
    operators = OperatorRegistry()
    rows: list[dict[str, Any]] = []
    for path, contract in contracts:
        reasons, capability_evidence = _dependency_reasons(
            contract, trust=trust, operators=operators
        )
        if registry_errors:
            reasons.append("JOURNEY_REGISTRY_BINDING_INVALID")
        status, reasons = _classification(contract, reasons)
        rows.append(
            {
                "journey_id": contract["journey_id"],
                "display_name": contract["display_name"],
                "status": status,
                "reason_codes": reasons,
                "evidence": {
                    "contract": relative(root, path),
                    "ledger": "src/gravity_insight/contracts/journeys/ledger-snapshot.v1.json",
                    "capabilities": capability_evidence,
                    "surfaces": copy.deepcopy(contract["surfaces"]),
                "execution_mode": contract["execution"]["mode"],
                    "request_budget": copy.deepcopy(contract["request_budget"]),
                },
            }
        )
    counts = {
        status: sum(row["status"] == status for row in rows)
        for status in ("certified", "uncertified", "blocked")
    }
    return {
        "schema_version": "gravity.journey-certifications.v1",
        "status": "valid" if rows and not load_errors and not registry_errors else "invalid",
        "ok": bool(rows) and not load_errors and not registry_errors,
        "counts": {
            **counts,
            "total": len(rows),
            "source_total": len(rows) + len(load_errors),
        },
        "journeys": rows,
        "registry_errors": [*load_errors, *registry_errors],
        "certification_scope": (
            "Offline contract, surface, dependency, Trust, Completeness, and Data Quality evidence."
        ),
        "limitation": (
            "Certification does not claim production execution success; account-scoped "
            "Provider and production evidence remain separate."
        ),
        "repository": git_state(root),
        "network_called": False,
    }


__all__ = ["journey_certifications"]
