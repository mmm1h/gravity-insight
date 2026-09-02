"""R01 Journey binding around Core Skill readiness and the existing executor."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from .analysis_playbook_input import normalize_metric_anomaly_inputs
from .analysis_result_contract import compile_analysis_result
from .core_skill_runtime import CoreSkillRuntime
from .data_quality import data_quality_result
from .errors import ErrorCategory, InputValidationError, exit_code_for_category
from .execution_snapshot import build_execution_snapshot
from .reference_journey_contract import JOURNEY_ID, reference_artifacts
from .reference_journey_quality import evaluate_playbook_data_quality
from .result_audit import result_receipt_references


CAN_RUN_SCHEMA_VERSION = "gravity.journey-can-run.v1"
ANALYSIS_RESULT_SCHEMA_VERSION = "gravity.analysis-result.v1"
INPUT_SCHEMA_VERSION = "gravity.reference-journey-input.v1"
_INVALID_EXIT = exit_code_for_category(ErrorCategory.CALLER)
_BLOCKED_EXIT = exit_code_for_category(ErrorCategory.LOCAL)


class ReferenceJourneyRunner:
    """Keep one R01 execution owner while Core composes local dependencies."""

    def __init__(
        self,
        sdk: Any,
        *,
        workspace: Any | None = None,
        capability_trust: Any | None = None,
        core_runtime: CoreSkillRuntime | None = None,
    ) -> None:
        self._sdk = sdk
        self._workspace = workspace if workspace is not None else sdk.workspace
        self._core_runtime = core_runtime or CoreSkillRuntime(
            workspace=self._workspace,
            capability_trust=capability_trust,
        )

    def can_run(self, inputs: Mapping[str, Any]) -> dict[str, Any]:
        """Return public readiness without echoing caller question or hypothesis."""

        return _public_can_run(self._assess(inputs))

    def _assess(self, inputs: Mapping[str, Any]) -> dict[str, Any]:
        normalized, reasons = _inputs(inputs)
        if normalized is None:
            return _invalid_can_run(reference_artifacts(), reasons)
        core = self._core_runtime.resolve(
            JOURNEY_ID,
            {
                "app_alias": normalized["app"],
                "windows": {
                    "current": copy.deepcopy(normalized["current_window"]),
                    "reference": copy.deepcopy(normalized["reference_window"]),
                },
            },
            input_schema_version=INPUT_SCHEMA_VERSION,
        )
        return _can_run_result(core, normalized)

    def run(self, inputs: Mapping[str, Any]) -> dict[str, Any]:
        before = self._assess(inputs)
        if before["can_run_status"] != "verified":
            return _blocked_analysis_result(
                before,
                network_called=bool(before["provider_rpc_called"]),
            )
        normalized = before["normalized_input"]
        bindings = before["semantic_bindings"]
        if len(bindings) != 1:
            failed = copy.deepcopy(before)
            failed["can_run_status"] = "blocked"
            failed["reason_codes"] = ["SEMANTIC_BINDING_AMBIGUOUS"]
            return _blocked_analysis_result(failed, network_called=False)
        playbook = self._sdk.metric_anomaly_playbook(
            normalized,
            semantic_binding=bindings[0],
        )
        after = self._assess(inputs)
        if after["execution_snapshot"] != before["execution_snapshot"]:
            changed = copy.deepcopy(before)
            changed["can_run_status"] = "blocked"
            changed["reason_codes"] = ["DEPENDENCY_SNAPSHOT_CHANGED"]
            return _blocked_analysis_result(changed, network_called=True)
        executed = playbook.get("execution", {}).get("query_steps_executed")
        maximum = before["request_budget"]["known_requests_max"]
        if type(executed) is not int or executed > maximum:
            failed = copy.deepcopy(before)
            failed["can_run_status"] = "blocked"
            failed["reason_codes"] = ["REQUEST_BUDGET_EXCEEDED"]
            return _blocked_analysis_result(failed, network_called=True)
        completeness = before["dependencies"]["capabilities"][0]["completeness"]
        quality = evaluate_playbook_data_quality(playbook, completeness=completeness)
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
    core: Mapping[str, Any], normalized: Mapping[str, Any]
) -> dict[str, Any]:
    status = str(core["status"])
    return {
        "schema_version": CAN_RUN_SCHEMA_VERSION,
        "ok": status == "verified",
        "status": status,
        "exit_code": (
            0
            if status == "verified"
            else _INVALID_EXIT if status == "invalid" else _BLOCKED_EXIT
        ),
        "journey": copy.deepcopy(core["journey"]),
        "skill": copy.deepcopy(core["skill"]),
        "project_overlay": copy.deepcopy(core["project_overlay"]),
        "lifecycle": copy.deepcopy(core["lifecycle"]),
        "readiness": copy.deepcopy(core["readiness"]),
        "validation": core["validation"],
        "can_run_status": status,
        "reason_codes": copy.deepcopy(core["reason_codes"]),
        "dependencies": copy.deepcopy(core["dependencies"]),
        "request_budget": copy.deepcopy(core["request_budget"]),
        "claim_policy": copy.deepcopy(core["claim_policy"]),
        "execution_snapshot": copy.deepcopy(core["execution_snapshot"]),
        "semantic_bindings": copy.deepcopy(core["semantic_bindings"]),
        "normalized_input": copy.deepcopy(normalized),
        "provider_rpc_called": bool(core["provider_rpc_called"]),
        "provider_internal_io_controlled": False,
        "provider_internal_network": core["provider_internal_network"],
        "network_called": False,
    }


def _invalid_can_run(
    artifacts: Mapping[str, Mapping[str, Any]], reasons: list[str]
) -> dict[str, Any]:
    journey = artifacts["journey"]
    contract = journey["contract"]
    journey_ref = {
        "journey_id": contract["journey_id"],
        "version": contract["version"],
        "digest": journey["digest"],
    }
    snapshot = _invalid_snapshot(artifacts, journey_ref)
    return {
        "schema_version": CAN_RUN_SCHEMA_VERSION,
        "ok": False,
        "status": "invalid",
        "exit_code": _INVALID_EXIT,
        "journey": journey_ref,
        "skill": None,
        "project_overlay": None,
        "lifecycle": {
            "journey": contract["lifecycle"],
            "skill": None,
        },
        "readiness": {
            "declared": None,
            "resolved": "invalid",
        },
        "validation": None,
        "can_run_status": "invalid",
        "reason_codes": list(dict.fromkeys(reasons)),
        "dependencies": {
            "capabilities": [],
            "semantics": [],
            "operators": [],
            "models": [],
            "context_packs": [],
        },
        "request_budget": copy.deepcopy(contract["request_budget"]),
        "claim_policy": {
            **copy.deepcopy(contract["claim_policy"]),
            "optional_context_complete": True,
        },
        "execution_snapshot": snapshot,
        "semantic_bindings": [],
        "normalized_input": None,
        "provider_rpc_called": False,
        "provider_internal_io_controlled": False,
        "provider_internal_network": "not_applicable",
        "network_called": False,
    }


def _invalid_snapshot(
    artifacts: Mapping[str, Mapping[str, Any]],
    journey_ref: Mapping[str, Any],
) -> dict[str, Any]:
    contract = artifacts["journey"]["contract"]
    capability = artifacts["capability"]
    operator = artifacts["operator"]
    capability_ref = {
        "identity_kind": capability["contract"]["identity_kind"],
        "selector": capability["contract"]["selector"],
        "contract_version": capability["contract"]["contract_version"],
        "contract_digest": capability["digest"],
        "trust_digest": None,
        "status": "unresolved",
    }
    semantic_refs = [
        {
            "uri": uri,
            "version": None,
            "definition_digest": None,
            "binding_digest": None,
            "source_digest": None,
            "registry_digest": None,
            "status": "unresolved",
        }
        for uri in contract["required_semantics"]
    ]
    operator_ref = {
        "uri": operator["contract"]["uri"],
        "version": operator["contract"]["version"],
        "digest": operator["digest"],
        "assumptions_digest": operator["assumptions_digest"],
        "status": "available",
    }
    return build_execution_snapshot(
        status="blocked",
        journey=journey_ref,
        skill=None,
        project_overlay=None,
        capabilities=[capability_ref],
        semantics=semantic_refs,
        operators=[operator_ref],
        models=[],
        context_packs=[],
        contracts={
            "input_schema_version": INPUT_SCHEMA_VERSION,
            "analysis_result_schema_version": ANALYSIS_RESULT_SCHEMA_VERSION,
            "execution_mode": contract["execution"]["mode"],
            "execution_owner": contract["execution"]["owner"],
        },
    )


def _success_analysis_result(
    readiness: Mapping[str, Any],
    playbook: Mapping[str, Any],
    quality: Mapping[str, Any],
) -> dict[str, Any]:
    snapshot = readiness["execution_snapshot"]
    conclusion = copy.deepcopy(playbook["conclusion"])
    scope = _input_scope(readiness["normalized_input"])
    value = {
        "schema_version": ANALYSIS_RESULT_SCHEMA_VERSION,
        "ok": True,
        "status": "success",
        "exit_code": 0,
        "question": readiness["normalized_input"]["question"],
        "journey": copy.deepcopy(snapshot["journey"]),
        "skill": copy.deepcopy(snapshot["skill"]),
        "scope": scope,
        "semantics": copy.deepcopy(snapshot["semantics"]),
        "capabilities": copy.deepcopy(snapshot["capabilities"]),
        "operators": copy.deepcopy(snapshot["operators"]),
        "models": copy.deepcopy(snapshot["models"]),
        "context_packs": _context_packs(readiness),
        "completeness": "complete",
        "data_quality": copy.deepcopy(quality),
        "evidence_level": "L2",
        "findings": [
            {
                "finding_type": "supported_association",
                "statement": conclusion["statement"],
                "evidence_level": "L2",
                "fact_references": copy.deepcopy(conclusion["fact_references"]),
                "supporting_references": _supporting_references(snapshot),
                "scope": copy.deepcopy(scope),
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
        "allowed_claims": [
            copy.deepcopy(claim)
            for claim in playbook["allowed_claims"]
            if claim["claim_id"] in set(readiness["claim_policy"]["allowed"])
        ],
        "forbidden_claims": copy.deepcopy(readiness["claim_policy"]["forbidden"]),
        "recommended_next_actions": [],
        "receipt_references": _receipt_references(playbook),
        "execution_snapshot": copy.deepcopy(snapshot),
        "can_run_status": "verified",
        "reason_codes": [],
        "network_called": bool(
            playbook.get("network_called") or readiness["provider_rpc_called"]
        ),
    }
    return compile_analysis_result(value)


def _blocked_analysis_result(
    readiness: Mapping[str, Any],
    *,
    network_called: bool,
    data_quality: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    invalid = readiness["can_run_status"] == "invalid"
    snapshot = readiness["execution_snapshot"]
    value = {
        "schema_version": ANALYSIS_RESULT_SCHEMA_VERSION,
        "ok": False,
        "status": "invalid" if invalid else "blocked",
        "exit_code": _INVALID_EXIT if invalid else _BLOCKED_EXIT,
        "question": None,
        "journey": copy.deepcopy(snapshot["journey"]),
        "skill": copy.deepcopy(snapshot["skill"]),
        "scope": _input_scope(readiness.get("normalized_input")),
        "semantics": copy.deepcopy(snapshot["semantics"]),
        "capabilities": copy.deepcopy(snapshot["capabilities"]),
        "operators": copy.deepcopy(snapshot["operators"]),
        "models": copy.deepcopy(snapshot["models"]),
        "context_packs": _context_packs(readiness),
        "completeness": "unknown",
        "data_quality": (
            copy.deepcopy(data_quality)
            if data_quality is not None
            else data_quality_result(())
        ),
        "evidence_level": None,
        "findings": [],
        "excluded_factors": [],
        "hypotheses": [],
        "limitations": ["Required Skill dependencies are not verified."],
        "allowed_claims": [],
        "forbidden_claims": copy.deepcopy(
            (readiness.get("claim_policy") or {}).get("forbidden", [])
        ),
        "recommended_next_actions": [],
        "receipt_references": [],
        "execution_snapshot": copy.deepcopy(snapshot),
        "can_run_status": readiness["can_run_status"],
        "reason_codes": copy.deepcopy(readiness["reason_codes"]),
        "network_called": network_called,
    }
    return compile_analysis_result(value)


def _public_can_run(value: Mapping[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(dict(value))
    result.pop("normalized_input", None)
    result.pop("semantic_bindings", None)
    return result


def _context_packs(readiness: Mapping[str, Any]) -> list[dict[str, Any]]:
    packs = readiness.get("dependencies", {}).get("context_packs", [])
    return copy.deepcopy(list(packs))


def _supporting_references(snapshot: Mapping[str, Any]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for item in snapshot["capabilities"]:
        if item["trust_digest"] is not None:
            result.append(
                {
                    "kind": "capability",
                    "uri": f"{item['identity_kind']}:{item['selector']}",
                    "digest": item["trust_digest"],
                }
            )
    for item in snapshot["semantics"]:
        if item["definition_digest"] is not None:
            result.append(
                {
                    "kind": "semantic",
                    "uri": item["uri"],
                    "digest": item["definition_digest"],
                }
            )
    for field, kind, digest_key in (
        ("operators", "operator", "digest"),
        ("models", "model", "digest"),
    ):
        for item in snapshot[field]:
            if item[digest_key] is not None:
                result.append(
                    {"kind": kind, "uri": item["uri"], "digest": item[digest_key]}
                )
    for item in snapshot["context_packs"]:
        if item["pack_digest"] is not None and item["status"] != "blocked":
            result.append(
                {
                    "kind": "context",
                    "uri": item["requirement_uri"],
                    "digest": item["pack_digest"],
                }
            )
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


__all__ = [
    "ANALYSIS_RESULT_SCHEMA_VERSION",
    "CAN_RUN_SCHEMA_VERSION",
    "INPUT_SCHEMA_VERSION",
    "ReferenceJourneyRunner",
]
