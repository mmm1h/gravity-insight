"""Reusable offline Journey registry, readiness, impact, and execution facade."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from .actionable_error_values import actual_value
from .agent_runtime_contracts import canonical_digest
from .capability_impact import capability_impact
from .capability_trust import (
    CapabilityTrustService,
    assess_capability_requirement,
)
from .errors import ErrorCategory, InputValidationError, exit_code_for_category
from .journey_contract import (
    journey_artifact,
    journey_artifacts,
    verify_journey_registry,
)
from .model_registry import ModelRegistry
from .operator_registry import OperatorRegistry
from .reference_journey_contract import JOURNEY_ID, reference_artifacts


CAN_RUN_SCHEMA_VERSION = "gravity.journey-can-run.v1"
DESCRIPTION_SCHEMA_VERSION = "gravity.journey-description.v1"
LIST_SCHEMA_VERSION = "gravity.journey-list.v1"
_INVALID_EXIT = exit_code_for_category(ErrorCategory.CALLER)
_BLOCKED_EXIT = exit_code_for_category(ErrorCategory.LOCAL)


class JourneyService:
    """Inspect every machine Journey and run only an explicitly bound owner."""

    def __init__(
        self,
        sdk: Any,
        *,
        workspace: Any | None = None,
        capability_trust: CapabilityTrustService | None = None,
        operators: OperatorRegistry | None = None,
        models: ModelRegistry | None = None,
    ) -> None:
        self._sdk = sdk
        self._workspace = workspace if workspace is not None else sdk.workspace
        self._capability_trust = capability_trust or CapabilityTrustService()
        self._operators = operators or OperatorRegistry()
        self._models = models or ModelRegistry(operators=self._operators)

    def list(self) -> dict[str, Any]:
        rows = []
        for artifact in journey_artifacts():
            contract = artifact["contract"]
            rows.append(
                {
                    "journey_id": contract["journey_id"],
                    "display_name": contract["display_name"],
                    "version": contract["version"],
                    "lifecycle": contract["lifecycle"],
                    "execution_mode": contract["execution"]["mode"],
                    "surfaces": copy.deepcopy(contract["surfaces"]),
                    "digest": artifact["digest"],
                }
            )
        return {
            "schema_version": LIST_SCHEMA_VERSION,
            "status": "success",
            "count": len(rows),
            "journeys": rows,
            "network_called": False,
        }

    def verify(self) -> dict[str, Any]:
        return verify_journey_registry()

    def describe(self, journey_id: str) -> dict[str, Any]:
        artifact = _journey(journey_id)
        contract = artifact["contract"]
        return {
            "schema_version": DESCRIPTION_SCHEMA_VERSION,
            "journey": {
                "journey_id": contract["journey_id"],
                "display_name": contract["display_name"],
                "version": contract["version"],
                "lifecycle": contract["lifecycle"],
                "owner": contract["owner"],
                "calling_project": contract["calling_project"],
                "digest": artifact["digest"],
            },
            "skill": _skill_reference(contract),
            "required_semantics": copy.deepcopy(contract["required_semantics"]),
            "required_operators": copy.deepcopy(contract["required_operators"]),
            "required_models": copy.deepcopy(contract["required_models"]),
            "required_context": copy.deepcopy(contract["required_context"]),
            "required_capabilities": copy.deepcopy(
                contract["required_capabilities"]
            ),
            "surfaces": copy.deepcopy(contract["surfaces"]),
            "request_budget": copy.deepcopy(contract["request_budget"]),
            "claim_policy": copy.deepcopy(contract["claim_policy"]),
            "execution": copy.deepcopy(contract["execution"]),
            "network_called": False,
        }

    def can_run(
        self,
        journey_id: str,
        inputs: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        artifact = _journey(journey_id)
        if journey_id == JOURNEY_ID:
            from .reference_journey import ReferenceJourneyRunner

            return ReferenceJourneyRunner(
                self._sdk,
                workspace=self._workspace,
                capability_trust=self._capability_trust,
            ).can_run(inputs if inputs is not None else {})
        if inputs is not None and not isinstance(inputs, Mapping):
            return _generic_can_run(
                artifact,
                capability_results=[],
                status="invalid",
                reasons=["JOURNEY_INPUT_INVALID"],
            )
        return self._generic_can_run(artifact)

    def run(
        self,
        journey_id: str,
        inputs: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        artifact = _journey(journey_id)
        if journey_id == JOURNEY_ID:
            from .reference_journey import ReferenceJourneyRunner

            return ReferenceJourneyRunner(
                self._sdk,
                workspace=self._workspace,
                capability_trust=self._capability_trust,
            ).run(inputs if inputs is not None else {})
        readiness = self.can_run(journey_id, inputs)
        reasons = list(readiness["reason_codes"])
        if readiness["can_run_status"] == "verified":
            reasons = ["JOURNEY_EXECUTION_NOT_BOUND"]
        return {
            "schema_version": "gravity.analysis-result.v1",
            "ok": False,
            "status": (
                "invalid"
                if readiness["can_run_status"] == "invalid"
                else "blocked"
            ),
            "exit_code": (
                _INVALID_EXIT
                if readiness["can_run_status"] == "invalid"
                else _BLOCKED_EXIT
            ),
            "journey": copy.deepcopy(readiness["journey"]),
            "can_run_status": readiness["can_run_status"],
            "reason_codes": reasons,
            "dependencies": copy.deepcopy(readiness["dependencies"]),
            "completeness": "unknown",
            "data_quality": {
                "schema_version": "gravity.data-quality-result.v1",
                "status": "unknown",
                "checks": [],
                "reason_codes": ["DATA_QUALITY_UNPROVEN"],
            },
            "findings": [],
            "allowed_claims": [],
            "receipt_references": [],
            "execution_snapshot": readiness["execution_snapshot"],
            "network_called": False,
        }

    def impact(self, request: Mapping[str, Any]) -> dict[str, Any]:
        return capability_impact(request)

    def _generic_can_run(self, artifact: Mapping[str, Any]) -> dict[str, Any]:
        contract = artifact["contract"]
        capability_results: list[dict[str, Any]] = []
        statuses: list[str] = []
        reasons: list[str] = []
        for requirement in contract["required_capabilities"]:
            result = self._capability_trust.trust(
                str(requirement["identity_kind"]), str(requirement["selector"])
            )
            capability_results.append(result)
            status, selected_reasons = assess_capability_requirement(
                result, requirement
            )
            statuses.append(status)
            reasons.extend(selected_reasons)
        if contract["required_semantics"]:
            statuses.append("blocked")
            reasons.append("SEMANTIC_DEFINITION_MISSING")
        operator_dependencies = self._operators.dependencies(
            contract["required_operators"]
        )
        if not operator_dependencies["ok"]:
            statuses.append("blocked")
            reasons.extend(operator_dependencies["reason_codes"])
        model_dependencies = self._models.dependencies(contract["required_models"])
        if not model_dependencies["ok"]:
            statuses.append("blocked")
            reasons.extend(model_dependencies["reason_codes"])
        if contract["required_context"]:
            statuses.append("blocked")
            reasons.append("CONTEXT_REQUIRED_MISSING")
        if contract["required_skill"]:
            statuses.append("blocked")
            reasons.append("SKILL_DEPENDENCY_UNRESOLVED")
        if contract["lifecycle"] == "revoked":
            statuses.append("blocked")
            reasons.append("JOURNEY_REVOKED")
        status = (
            "blocked"
            if "blocked" in statuses
            else "unknown"
            if "unknown" in statuses or not statuses
            else "verified"
        )
        return _generic_can_run(
            artifact,
            capability_results=capability_results,
            operator_dependencies=operator_dependencies,
            model_dependencies=model_dependencies,
            status=status,
            reasons=reasons,
        )


def _generic_can_run(
    artifact: Mapping[str, Any],
    *,
    capability_results: list[dict[str, Any]],
    operator_dependencies: Mapping[str, Any],
    model_dependencies: Mapping[str, Any],
    status: str,
    reasons: list[str],
) -> dict[str, Any]:
    contract = artifact["contract"]
    dependencies = {
        "capabilities": copy.deepcopy(capability_results),
        "semantics": _static_dependencies(contract["required_semantics"]),
        "operators": copy.deepcopy(operator_dependencies["dependencies"]),
        "models": copy.deepcopy(model_dependencies["dependencies"]),
        "context": _static_dependencies(contract["required_context"]),
        "skill": (
            {"uri": contract["required_skill"], "status": "unresolved"}
            if contract["required_skill"]
            else None
        ),
    }
    snapshot = canonical_digest(
        {
            "journey_digest": artifact["digest"],
            "dependencies": dependencies,
        }
    )
    return {
        "schema_version": CAN_RUN_SCHEMA_VERSION,
        "ok": status == "verified",
        "status": status,
        "exit_code": (
            0 if status == "verified" else _INVALID_EXIT if status == "invalid" else _BLOCKED_EXIT
        ),
        "journey": {
            "journey_id": contract["journey_id"],
            "version": contract["version"],
            "digest": artifact["digest"],
        },
        "lifecycle": contract["lifecycle"],
        "can_run_status": status,
        "reason_codes": list(dict.fromkeys(reasons)),
        "dependencies": dependencies,
        "execution_snapshot": snapshot,
        "network_called": False,
    }


def _static_dependencies(values: list[str]) -> list[dict[str, str]]:
    return [{"uri": value, "status": "unresolved"} for value in values]


def _journey(journey_id: Any) -> dict[str, Any]:
    if not isinstance(journey_id, str) or not journey_id.strip():
        raise InputValidationError(
            f"actual value: {actual_value(journey_id)}; journey_id must name one "
            "registered Journey",
            field="journey_id",
        )
    artifact = journey_artifact(journey_id.strip())
    if artifact is None:
        raise InputValidationError(
            f"actual value: {actual_value(journey_id)}; journey_id is not registered",
            field="journey_id",
            next_action="Run `gravity journey list` and retry with an exact journey_id.",
        )
    return artifact


def _skill_reference(contract: Mapping[str, Any]) -> dict[str, Any] | None:
    if contract["journey_id"] != JOURNEY_ID:
        uri = contract.get("required_skill")
        return {"uri": uri} if isinstance(uri, str) and uri else None
    skill = reference_artifacts()["skill"]
    manifest = skill["contract"]
    return {
        "namespace": manifest["namespace"],
        "skill_id": manifest["skill_id"],
        "version": manifest["version"],
        "digest": skill["package_digest"],
    }


__all__ = [
    "CAN_RUN_SCHEMA_VERSION",
    "DESCRIPTION_SCHEMA_VERSION",
    "JourneyService",
    "LIST_SCHEMA_VERSION",
]
