"""R01 vertical Journey composed around the existing playbook executor."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .agent_runtime_contracts import canonical_digest
from .analysis_playbook_input import normalize_metric_anomaly_inputs
from .capability_trust import (
    CapabilityTrustService,
    assess_capability_requirement,
)
from .errors import ErrorCategory, InputValidationError, exit_code_for_category
from .reference_journey_contract import JOURNEY_ID, reference_artifacts
from .reference_journey_quality import evaluate_playbook_data_quality
from .reference_project_contract import (
    ReferenceProjectContractError,
    load_reference_project_contract,
    public_context_reference,
)
from .result_audit import result_receipt_references


CAN_RUN_SCHEMA_VERSION = "gravity.journey-can-run.v1"
ANALYSIS_RESULT_SCHEMA_VERSION = "gravity.analysis-result.v1"
INPUT_SCHEMA_VERSION = "gravity.reference-journey-input.v1"
_INVALID_EXIT = exit_code_for_category(ErrorCategory.CALLER)
_BLOCKED_EXIT = exit_code_for_category(ErrorCategory.LOCAL)


class ReferenceJourneyRunner:
    """R01-specific input/project binding around the existing playbook owner."""

    def __init__(
        self,
        sdk: Any,
        *,
        workspace: Any | None = None,
        capability_trust: CapabilityTrustService | None = None,
    ) -> None:
        self._sdk = sdk
        self._workspace = workspace if workspace is not None else sdk.workspace
        self._capability_trust = capability_trust or CapabilityTrustService()

    def can_run(self, inputs: Mapping[str, Any]) -> dict[str, Any]:
        """Return public readiness without echoing caller values."""

        return _public_can_run(self._assess(inputs))

    def _assess(self, inputs: Mapping[str, Any]) -> dict[str, Any]:
        artifacts = reference_artifacts()
        normalized, input_reasons = _inputs(inputs)
        if normalized is None:
            return _can_run_result(
                artifacts,
                status="invalid",
                reasons=input_reasons,
                normalized=None,
                trust=None,
                project=None,
            )
        project, project_reasons, project_invalid = self._project(normalized, artifacts)
        requirement = artifacts["journey"]["contract"]["required_capabilities"][0]
        trust = self._capability_trust.trust(
            str(requirement["identity_kind"]), str(requirement["selector"])
        )
        capability_status, capability_reasons = assess_capability_requirement(
            trust, requirement
        )
        reasons = [*project_reasons, *capability_reasons]
        if project_invalid:
            status = "invalid"
        elif project_reasons or capability_status == "blocked":
            status = "blocked"
        elif capability_status == "unknown":
            status = "unknown"
        elif capability_status != "stable" or project is None:
            status = "blocked"
        else:
            status = "verified"
        return _can_run_result(
            artifacts,
            status=status,
            reasons=reasons,
            normalized=normalized,
            trust=trust,
            project=project,
        )

    def run(self, inputs: Mapping[str, Any]) -> dict[str, Any]:
        before = self._assess(inputs)
        if before["can_run_status"] != "verified":
            return _blocked_analysis_result(before, network_called=False)
        normalized = before["normalized_input"]
        playbook = self._sdk.metric_anomaly_playbook(normalized)
        after = self._assess(inputs)
        if after.get("execution_snapshot") != before.get("execution_snapshot"):
            changed = copy.deepcopy(before)
            changed["can_run_status"] = "blocked"
            changed["reason_codes"] = ["DEPENDENCY_SNAPSHOT_CHANGED"]
            return _blocked_analysis_result(changed, network_called=True)
        completeness = before["dependencies"]["capability"]["completeness"]
        quality = evaluate_playbook_data_quality(
            playbook, completeness=completeness
        )
        if quality["status"] != "pass":
            failed = copy.deepcopy(before)
            failed["can_run_status"] = "blocked"
            failed["reason_codes"] = quality["reason_codes"]
            return _blocked_analysis_result(
                failed,
                network_called=True,
                data_quality=quality,
            )
        return _success_analysis_result(before, playbook, quality)

    def _project(
        self,
        normalized: Mapping[str, Any],
        artifacts: Mapping[str, Mapping[str, Any]],
    ) -> tuple[dict[str, Any] | None, list[str], bool]:
        root = getattr(self._workspace, "root", None)
        if not isinstance(root, Path):
            try:
                root = Path(root)
            except TypeError:
                return None, ["SEMANTIC_DEFINITION_MISSING", "CONTEXT_REQUIRED_MISSING"], False
        path = artifacts["journey"]["contract"]["project_contract_path"]
        try:
            project = load_reference_project_contract(
                root,
                contract_path=path,
                current_window=normalized["current_window"],
                reference_window=normalized["reference_window"],
            )
        except ReferenceProjectContractError as exc:
            reason = str(exc)
            if reason in {
                "SEMANTIC_EFFECTIVE_RANGE_MISMATCH",
                "CONTEXT_ENTITY_TIME_MISMATCH",
            }:
                return None, [reason], False
            if "missing" in reason.casefold():
                return None, ["SEMANTIC_DEFINITION_MISSING", "CONTEXT_REQUIRED_MISSING"], False
            return None, ["REFERENCE_PROJECT_CONTRACT_INVALID"], True
        if normalized["app"] != "merge2-legacy":
            return None, ["SEMANTIC_BINDING_MISSING"], False
        return project, [], False


def _inputs(value: Mapping[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
    if not isinstance(value, Mapping):
        return None, ["JOURNEY_INPUT_INVALID"]
    expected = {
        "schema_version",
        "question",
        "app",
        "current_window",
        "reference_window",
        "hypothesis",
    }
    if set(value) != expected or value.get("schema_version") != INPUT_SCHEMA_VERSION:
        return None, ["JOURNEY_INPUT_INVALID"]
    playbook_input = dict(value)
    playbook_input["schema_version"] = "gravity.metric-anomaly-localization-input.v1"
    try:
        normalized = normalize_metric_anomaly_inputs(playbook_input)
    except InputValidationError:
        return None, ["JOURNEY_INPUT_INVALID"]
    normalized["schema_version"] = "gravity.metric-anomaly-localization-input.v1"
    return normalized, []


def _can_run_result(
    artifacts: Mapping[str, Mapping[str, Any]],
    *,
    status: str,
    reasons: list[str],
    normalized: Mapping[str, Any] | None,
    trust: Mapping[str, Any] | None,
    project: Mapping[str, Any] | None,
) -> dict[str, Any]:
    dependencies = {
        "capability": copy.deepcopy(trust),
        "semantic": (
            {
                "uri": project["semantic"]["uri"],
                "digest": project["semantic"]["digest"],
                "source_revision": project["source_revision"],
            }
            if project is not None
            else None
        ),
        "operator": _operator_reference(artifacts["operator"]),
        "models": [],
        "skill": _skill_reference(artifacts),
        "context_pack": (
            public_context_reference(project["context_pack"])
            if project is not None
            else None
        ),
    }
    snapshot = _digest(
        {
            "journey": artifacts["journey"]["digest"],
            "dependencies": dependencies,
            "input_scope": _input_scope(normalized),
        }
    )
    return {
        "schema_version": CAN_RUN_SCHEMA_VERSION,
        "ok": status == "verified",
        "status": status,
        "exit_code": (
            0
            if status == "verified"
            else _INVALID_EXIT if status == "invalid" else _BLOCKED_EXIT
        ),
        "journey": {
            "journey_id": JOURNEY_ID,
            "version": 1,
            "digest": artifacts["journey"]["digest"],
        },
        "lifecycle": artifacts["journey"]["contract"]["lifecycle"],
        "can_run_status": status,
        "reason_codes": list(dict.fromkeys(reasons)),
        "dependencies": dependencies,
        "execution_snapshot": snapshot,
        "normalized_input": copy.deepcopy(normalized),
        "network_called": False,
    }


def _success_analysis_result(
    readiness: Mapping[str, Any],
    playbook: Mapping[str, Any],
    quality: Mapping[str, Any],
) -> dict[str, Any]:
    dependencies = readiness["dependencies"]
    conclusion = copy.deepcopy(playbook["conclusion"])
    return {
        "schema_version": ANALYSIS_RESULT_SCHEMA_VERSION,
        "ok": True,
        "status": "success",
        "exit_code": 0,
        "question": readiness["normalized_input"]["question"],
        "journey": copy.deepcopy(readiness["journey"]),
        "skill": copy.deepcopy(dependencies["skill"]),
        "scope": _input_scope(readiness["normalized_input"]),
        "semantics": [copy.deepcopy(dependencies["semantic"])],
        "capabilities": [copy.deepcopy(dependencies["capability"])],
        "operators": [copy.deepcopy(dependencies["operator"])],
        "models": copy.deepcopy(dependencies["models"]),
        "context_pack": copy.deepcopy(dependencies["context_pack"]),
        "completeness": "complete",
        "data_quality": copy.deepcopy(quality),
        "evidence_level": "L2",
        "findings": [
            {
                "finding_type": "supported_association",
                "statement": conclusion["statement"],
                "evidence_level": "L2",
                "fact_references": copy.deepcopy(conclusion["fact_references"]),
                "limitations": [
                    "Only returned rows and the selected slice are compared.",
                    "The result does not establish causality or unreturned values.",
                ],
            }
        ],
        "excluded_factors": [],
        "hypotheses": [copy.deepcopy(readiness["normalized_input"]["hypothesis"])],
        "limitations": [
            "No complete App total, causality, incrementality, ROI, or natural-volume claim is allowed."
        ],
        "allowed_claims": copy.deepcopy(playbook["allowed_claims"]),
        "forbidden_claims": copy.deepcopy(
            reference_artifacts()["journey"]["contract"]["claim_policy"]["forbidden"]
        ),
        "recommended_next_actions": [],
        "receipt_references": _receipt_references(playbook),
        "execution_snapshot": readiness["execution_snapshot"],
        "network_called": bool(playbook.get("network_called")),
    }


def _blocked_analysis_result(
    readiness: Mapping[str, Any],
    *,
    network_called: bool,
    data_quality: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": ANALYSIS_RESULT_SCHEMA_VERSION,
        "ok": False,
        "status": "blocked" if readiness["can_run_status"] != "invalid" else "invalid",
        "exit_code": (
            _INVALID_EXIT
            if readiness["can_run_status"] == "invalid"
            else _BLOCKED_EXIT
        ),
        "journey": copy.deepcopy(readiness["journey"]),
        "can_run_status": readiness["can_run_status"],
        "reason_codes": copy.deepcopy(readiness["reason_codes"]),
        "scope": _input_scope(readiness.get("normalized_input")),
        "dependencies": copy.deepcopy(readiness["dependencies"]),
        "completeness": "unknown",
        "data_quality": copy.deepcopy(data_quality)
        if data_quality is not None
        else {
            "schema_version": "gravity.data-quality-result.v1",
            "status": "unknown",
            "checks": [],
            "reason_codes": ["DATA_QUALITY_UNPROVEN"],
        },
        "findings": [],
        "allowed_claims": [],
        "receipt_references": [],
        "execution_snapshot": readiness["execution_snapshot"],
        "network_called": network_called,
    }


def _skill_reference(
    artifacts: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    skill = artifacts["skill"]
    contract = skill["contract"]
    return {
        "namespace": contract["namespace"],
        "skill_id": contract["skill_id"],
        "version": contract["version"],
        "digest": skill["package_digest"],
    }


def _operator_reference(artifact: Mapping[str, Any]) -> dict[str, Any]:
    contract = artifact["contract"]
    return {
        "uri": contract["uri"],
        "version": contract["version"],
        "digest": artifact["digest"],
        "method": copy.deepcopy(contract["method"]),
        "assumptions_digest": artifact["assumptions_digest"],
        "input_schema": copy.deepcopy(contract["schemas"]["input"]),
        "output_schema": copy.deepcopy(contract["schemas"]["output"]),
        "limitations": copy.deepcopy(contract["claim_policy"]["limitations"]),
    }


def _public_can_run(value: Mapping[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(dict(value))
    result.pop("normalized_input", None)
    return result


def _receipt_references(playbook: Mapping[str, Any]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for step in playbook.get("steps", ()):
        for reference in result_receipt_references(step):
            receipt_id = reference["receipt_id"]
            if receipt_id in seen:
                continue
            seen.add(receipt_id)
            result.append(reference)
    return result


def _input_scope(value: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    return {
        "app": value["app"],
        "current_window": copy.deepcopy(value["current_window"]),
        "reference_window": copy.deepcopy(value["reference_window"]),
        "selected_dimension_count": len(value["hypothesis"]["values"]),
    }


def _digest(value: Any) -> str:
    return canonical_digest(value)


__all__ = [
    "ANALYSIS_RESULT_SCHEMA_VERSION",
    "CAN_RUN_SCHEMA_VERSION",
    "INPUT_SCHEMA_VERSION",
    "ReferenceJourneyRunner",
]
