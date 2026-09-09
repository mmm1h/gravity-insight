"""Journey inspection and readiness over explicitly bound existing owners."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from .actionable_error_values import actual_value
from .agent_runtime_contracts import canonical_digest
from .analysis_result_contract import compile_analysis_result
from .capability_impact import capability_impact
from .capability_trust import CapabilityTrustService
from .contracts.envelope_obligations import (
    CompletenessState, DataCompleteness, DiagnosticEvidence, DiagnosticState,
    EnvelopeObligations, ExecutionState, ExecutionStatus, MutationCertainty,
    MutationState, SemanticState, SemanticValidity, serialize_envelope,
)
from .errors import ErrorCategory, InputValidationError, exit_code_for_category
from .execution_snapshot import build_execution_snapshot, snapshot_change_reasons
from .journey_contract import journey_artifact, journey_artifacts, verify_journey_registry
from .model_registry import ModelRegistry
from .operator_registry import OperatorRegistry
from .reference_journey_contract import JOURNEY_ID
from .workspace_app import resolve_workspace_app


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
        skill_runtime: Any | None = None,
    ) -> None:
        self._sdk = sdk
        self._workspace = workspace if workspace is not None else sdk.workspace
        self._capability_trust = capability_trust or CapabilityTrustService()
        self._operators = operators or OperatorRegistry()
        self._models = models or ModelRegistry(operators=self._operators)
        if skill_runtime is None:
            from .core_skill_runtime import CoreSkillRuntime

            skill_runtime = CoreSkillRuntime(
                workspace=self._workspace,
                capability_trust=self._capability_trust,
                operators=self._operators,
                models=self._models,
            )
        self._skill_runtime = skill_runtime

    def list(self) -> dict[str, Any]:
        rows = []
        for artifact in journey_artifacts():
            contract = artifact["contract"]
            rows.append({
                "journey_id": contract["journey_id"],
                "display_name": contract["display_name"],
                "version": contract["version"],
                "lifecycle": contract["lifecycle"],
                "execution_mode": contract["execution"]["mode"],
                "execution_binding": self._binding(contract),
                "surfaces": copy.deepcopy(contract["surfaces"]),
                "digest": artifact["digest"],
            })
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
                **{key: contract[key] for key in (
                    "journey_id", "display_name", "version", "lifecycle", "owner", "calling_project"
                )},
                "digest": artifact["digest"],
            },
            "skill": {"uri": contract["required_skill"]} if contract["required_skill"] else None,
            **{key: copy.deepcopy(contract[key]) for key in (
                "required_semantics", "required_operators", "required_models",
                "required_context", "required_capabilities", "surfaces",
                "request_budget", "claim_policy", "execution"
            )},
            "execution_binding": self._binding(contract),
            "network_called": False,
        }

    def _binding(self, contract: Mapping[str, Any]) -> dict[str, Any]:
        identity = contract["journey_id"]
        method, owner, mode, schema = None, None, None, None
        if identity == JOURNEY_ID:
            method, owner, mode = "metric_anomaly_playbook", "metric-anomaly-localization@1", "plan"
            schema = "gravity.analysis-result.v1"
        elif identity == "analysis.default-value-dictionary":
            method, owner, mode = "analysis_default_dictionary", "composite:analysis_default_dictionary", "composite"
            from .analysis_default_dictionary import SCHEMA_VERSION

            schema = SCHEMA_VERSION
        elif identity == "analysis.realtime-event-catalog":
            method, owner, mode = "realtime_event_catalog", "composite:realtime_event_catalog", "composite"
            from .realtime_event_catalog import SCHEMA_VERSION

            schema = SCHEMA_VERSION
        bound = (
            method is not None
            and contract["execution"]["owner"] == owner
            and contract["execution"]["mode"] == mode
            and callable(getattr(self._sdk, method, None))
        )
        return {
            "status": "bound" if bound else (
                "method_guidance" if contract["execution"]["mode"] == "unavailable" else "unbound"
            ),
            "owner": contract["execution"]["owner"],
            "sdk_method": method,
            "result_schema_version": schema,
        }

    def _reference_runner(self) -> Any:
        from .reference_journey import ReferenceJourneyRunner

        return ReferenceJourneyRunner(
            self._sdk, workspace=self._workspace,
            capability_trust=self._capability_trust, core_runtime=self._skill_runtime,
        )

    def can_run(
        self, journey_id: str, inputs: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        result = self._assess(journey_id, inputs)
        for key in ("normalized_input", "semantic_bindings", "default_scope"):
            result.pop(key, None)
        return result

    def _assess(
        self, journey_id: str, inputs: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        artifact = _journey(journey_id)
        contract = artifact["contract"]
        binding = self._binding(contract)
        selected = {} if inputs is None else inputs
        normalized = None
        if contract["journey_id"] == JOURNEY_ID:
            core = self._reference_runner().can_run(selected)
        else:
            try:
                if not isinstance(selected, Mapping):
                    raise InputValidationError("Journey input must be an object", field="inputs")
                if binding["sdk_method"] is not None:
                    normalized = self._product_inputs(binding["sdk_method"], selected)
                    scope = None
                else:
                    if set(selected) - {"scope"}:
                        raise InputValidationError(
                            "actual value: unsupported fields; unbound Journey accepts only dependency scope",
                            field="inputs",
                            next_action="Pass only scope with app_alias and named start/end windows; use the Product directly for business inputs.",
                        )
                    scope = selected.get("scope")
                core = self._skill_runtime.resolve(contract["journey_id"], scope)
            except InputValidationError as exc:
                reason = "PROJECT_APP_BINDING_MISSING" if exc.field == "app" else "JOURNEY_INPUT_INVALID"
                core = _unresolved(artifact, reason)
        payload, obligations = _readiness_parts(core, contract, binding, normalized)
        return serialize_envelope(payload, obligations)

    def _product_inputs(self, method: str, inputs: Mapping[str, Any]) -> dict[str, Any]:
        fields = {"app"} if method == "analysis_default_dictionary" else {"app", "start", "end", "event_type"}
        if set(inputs) - fields:
            raise InputValidationError(
                "actual value: unsupported fields; Journey Product input fields changed",
                field="inputs", next_action="Use app for the dictionary; add start/end and optional event_type for the realtime catalog.",
            )
        result = {"app": resolve_workspace_app(self._workspace, inputs.get("app"))}
        if method == "realtime_event_catalog":
            start, end = inputs.get("start"), inputs.get("end")
            try:
                dates = [datetime.strptime(value, "%Y-%m-%d %H:%M:%S") for value in (start, end)]
                valid = all(date.strftime("%Y-%m-%d %H:%M:%S") == value for date, value in zip(dates, (start, end)))
            except (ValueError, TypeError):
                valid = False
            event_type = inputs.get("event_type", "profile")
            if not valid or dates[0] > dates[1] or not isinstance(event_type, str):
                raise InputValidationError("Catalog requires an explicit ordered datetime window and string event_type", field="inputs")
            result.update(start=start, end=end, event_type=event_type)
        return result

    def run(
        self, journey_id: str, inputs: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        before = self._assess(journey_id, inputs)
        if not before["ok"]:
            return _blocked_result(before)
        if before["journey"]["journey_id"] == JOURNEY_ID:
            return self._reference_runner().run({} if inputs is None else inputs)
        method = before["execution_binding"]["sdk_method"]
        result = getattr(self._sdk, method)(**before["normalized_input"], workspace=self._workspace)
        after = self._assess(journey_id, inputs)
        reasons = snapshot_change_reasons(before["execution_snapshot"], after["execution_snapshot"])
        if before["normalized_input"] != after["normalized_input"]:
            reasons.append("PROJECT_APP_BINDING_CHANGED")
        if before["execution_binding"] != after["execution_binding"]:
            reasons.append("JOURNEY_EXECUTION_BINDING_CHANGED")
        if not isinstance(result, Mapping) or result.get("schema_version") != before["execution_binding"]["result_schema_version"]:
            reasons.append("JOURNEY_RESULT_CONTRACT_CHANGED")
        if reasons or not after["ok"]:
            # Discard observations made under a changed dependency set.
            failed = copy.deepcopy(before)
            failed["can_run_status"] = "blocked"
            failed["reason_codes"] = list(dict.fromkeys([*after["reason_codes"], *reasons]))
            return _blocked_result(failed, network_called=True)
        # Product owners retain their own projection, completeness and errors.
        return result

    def impact(self, request: Mapping[str, Any]) -> dict[str, Any]:
        return capability_impact(request)


def _readiness_parts(
    core: Mapping[str, Any], contract: Mapping[str, Any],
    binding: Mapping[str, Any], normalized: Mapping[str, Any] | None,
) -> tuple[dict[str, Any], EnvelopeObligations]:
    result = copy.deepcopy(dict(core))
    status = str(core["status"])
    reasons = list(core["reason_codes"])
    if status == "unknown" and not reasons:
        reasons.append("DEPENDENCY_VALIDATION_UNKNOWN")
    if binding["status"] != "bound":
        reasons.append("JOURNEY_EXECUTION_NOT_BOUND")
    state = (
        "dependency_blocked" if status != "verified"
        else "unbound" if binding["status"] != "bound" else "executable"
    )
    public_status = "blocked" if state == "unbound" else status
    reasons = list(dict.fromkeys(reasons))
    result.update({
        "schema_version": CAN_RUN_SCHEMA_VERSION,
        "ok": state == "executable",
        "status": public_status,
        "exit_code": 0 if state == "executable" else (
            _INVALID_EXIT if status == "invalid" else _BLOCKED_EXIT
        ),
        "can_run_status": public_status,
        "execution_readiness": state,
        "execution_binding": copy.deepcopy(binding),
        "dependency_status": status,
        "reason_codes": reasons,
        "claim_policy": copy.deepcopy(core.get("claim_policy") or contract["claim_policy"]),
        "normalized_input": normalized,
    })
    if state != "executable":
        snapshot = result["execution_snapshot"]
        snapshot["status"] = "blocked"
        snapshot["snapshot_digest"] = canonical_digest({
            key: value for key, value in snapshot.items() if key != "snapshot_digest"
        })
    # A successful preflight is not execution or data-completeness evidence.
    obligations = EnvelopeObligations(
        execution_status=ExecutionStatus(ExecutionState.NOT_STARTED, "JOURNEY_READINESS_ONLY"),
        data_completeness=DataCompleteness(CompletenessState.UNKNOWN, "NO_EXECUTION_DATA"),
        semantic_validity=SemanticValidity(SemanticState.UNKNOWN, ("JOURNEY_READINESS_ONLY",)),
        diagnostic_evidence=DiagnosticEvidence(
            DiagnosticState.INCOMPLETE if reasons else DiagnosticState.NONE, tuple(reasons),
        ),
        mutation_certainty=MutationCertainty(MutationState.NOT_APPLICABLE, "READ_ONLY_JOURNEY"),
    )
    return result, obligations


def _unresolved(artifact: Mapping[str, Any], reason: str) -> dict[str, Any]:
    contract = artifact["contract"]
    journey = {"journey_id": contract["journey_id"], "version": contract["version"], "digest": artifact["digest"]}
    return {
        "status": "blocked" if reason == "PROJECT_APP_BINDING_MISSING" else "invalid",
        "journey": journey,
        "reason_codes": [reason],
        "dependencies": {},
        "execution_snapshot": build_execution_snapshot(
            status="blocked", journey=journey, skill=None, project_overlay=None,
            capabilities=[], semantics=[], operators=[], models=[], context_packs=[],
            contracts={
                "input_schema_version": None,
                "analysis_result_schema_version": "gravity.analysis-result.v1",
                "execution_mode": contract["execution"]["mode"],
                "execution_owner": contract["execution"]["owner"],
            },
        ),
        "network_called": False,
    }


def _blocked_result(readiness: Mapping[str, Any], *, network_called: bool = False) -> dict[str, Any]:
    snapshot = readiness["execution_snapshot"]
    invalid = readiness["can_run_status"] == "invalid"
    return compile_analysis_result({
        "schema_version": "gravity.analysis-result.v1",
        "ok": False, "status": "invalid" if invalid else "blocked",
        "exit_code": _INVALID_EXIT if invalid else _BLOCKED_EXIT,
        "question": None, "scope": None,
        **{key: copy.deepcopy(snapshot[key]) for key in (
            "journey", "skill", "semantics", "capabilities", "operators", "models"
        )},
        "context_packs": copy.deepcopy(readiness["dependencies"].get("context_packs", [])),
        "can_run_status": readiness["can_run_status"],
        "reason_codes": copy.deepcopy(readiness["reason_codes"]),
        "completeness": "unknown",
        "data_quality": {
            "schema_version": "gravity.data-quality-result.v1", "status": "unknown",
            "checks": [], "reason_codes": ["DATA_QUALITY_UNPROVEN"],
        },
        "evidence_level": None, "findings": [], "excluded_factors": [], "hypotheses": [],
        "limitations": ["Journey execution or required dependencies are not verified; no business analysis was completed."],
        "allowed_claims": [],
        "forbidden_claims": copy.deepcopy(readiness["claim_policy"]["forbidden"]),
        "recommended_next_actions": [], "receipt_references": [],
        "execution_snapshot": copy.deepcopy(snapshot),
        "network_called": network_called or bool(readiness.get("provider_rpc_called")),
    })


def _journey(journey_id: Any) -> dict[str, Any]:
    if not isinstance(journey_id, str) or not journey_id.strip():
        raise InputValidationError(
            f"actual value: {actual_value(journey_id)}; journey_id must name one registered Journey",
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


__all__ = ["CAN_RUN_SCHEMA_VERSION", "DESCRIPTION_SCHEMA_VERSION", "JourneyService", "LIST_SCHEMA_VERSION"]
