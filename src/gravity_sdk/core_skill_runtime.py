"""Offline composition of exact Skill dependencies for existing executors."""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Any

from .agent_runtime_contracts import AgentRuntimeContractError
from .actionable_error_values import actual_value
from .capability_trust import (
    CapabilityTrustService,
    assess_capability_requirement,
)
from .context_contract import ContextContractError
from .core_skill_context import resolve_project_context
from .core_skill_references import (
    capability_reference as _capability_reference,
    context_reference as _context_reference,
    journey_reference as _journey_reference,
    model_reference as _model_reference,
    operator_reference as _operator_reference,
    overlay_reference as _overlay_reference,
    semantic_reference as _semantic_reference,
    skill_reference as _skill_reference,
    unresolved_semantics as _unresolved_semantics,
)
from .errors import ContractChangedError, InputValidationError
from .execution_snapshot import build_execution_snapshot
from .external_context_binding import (
    ExternalContextBindingError,
    ExternalContextBindingResolver,
)
from .journey_contract import journey_artifact
from .model_registry import ModelRegistry
from .operator_registry import OperatorRegistry
from .project_skill_overlay import (
    ProjectSkillOverlayError,
    load_project_skill_overlay,
)
from .semantic_contract import SemanticContractError
from .semantic_registry import SemanticRegistry
from .runtime_skill_resolver import RuntimeSkillResolver


SCHEMA_VERSION = "gravity.core-skill-readiness.v1"


class CoreSkillRuntimeError(AgentRuntimeContractError):
    """Core Skill dependency composition cannot be represented safely."""


class CoreSkillRuntime:
    """Resolve local Skill dependencies without becoming an execution owner."""

    def __init__(
        self,
        *,
        workspace: Any,
        capability_trust: CapabilityTrustService | None = None,
        operators: OperatorRegistry | None = None,
        models: ModelRegistry | None = None,
        skill_resolver: RuntimeSkillResolver | None = None,
        external_context: ExternalContextBindingResolver | None = None,
        external_context_providers: Sequence[Any] = (),
    ) -> None:
        self._workspace = workspace
        self._capability_trust = capability_trust or CapabilityTrustService()
        self._operators = operators or OperatorRegistry()
        self._models = models or ModelRegistry(operators=self._operators)
        self._skill_resolver = skill_resolver or RuntimeSkillResolver(
            workspace=workspace
        )
        self._external_context = external_context or ExternalContextBindingResolver(
            workspace=workspace,
            providers=external_context_providers,
        )

    def resolve(
        self,
        journey_id: str,
        scope: Mapping[str, Any],
        *,
        input_schema_version: str | None = None,
        source_revision: str | None = None,
        observed_at: str | None = None,
    ) -> dict[str, Any]:
        journey = _journey(journey_id)
        normalized_scope = _scope(scope)
        local = self._local_dependencies(journey)
        project = self._project_dependencies(
            journey,
            normalized_scope,
            local["skill"],
            source_revision=source_revision,
            observed_at=observed_at,
        )
        reasons = list(dict.fromkeys([*local["reasons"], *project["reasons"]]))
        invalid = project["invalid"] or any(
            reason in {"SEMANTIC_EXECUTION_BINDING_INVALID", "SEMANTIC_OWNER_CONFLICT"}
            for reason in reasons
        )
        status = _status(
            reasons=reasons,
            capability_states=local["capability_states"],
            project_error_invalid=invalid,
        )
        snapshot = self._snapshot(
            journey,
            status,
            local,
            project,
            input_schema_version=input_schema_version,
        )
        return self._readiness(journey, status, reasons, local, project, snapshot)

    def _local_dependencies(self, journey: Mapping[str, Any]) -> dict[str, Any]:
        contract = journey["contract"]
        skill_resolution = self._skill_resolver.resolve(
            contract.get("required_skill"), journey=journey
        )
        skill = skill_resolution["skill"]
        capabilities, references, states, capability_reasons = self._capabilities(
            contract
        )
        operators = self._operators.dependencies(contract["required_operators"])
        models = self._models.dependencies(contract["required_models"])
        return {
            "skill": skill,
            "capabilities": capabilities,
            "capability_refs": references,
            "capability_states": states,
            "operators": operators,
            "models": models,
            "reasons": [
                *capability_reasons,
                *skill_resolution["reason_codes"],
                *operators["reason_codes"],
                *models["reason_codes"],
            ],
        }

    def _project_dependencies(
        self,
        journey: Mapping[str, Any],
        scope: Mapping[str, Any],
        skill: Mapping[str, Any] | None,
        *,
        source_revision: str | None,
        observed_at: str | None,
    ) -> dict[str, Any]:
        result = {
            "overlay": None,
            "semantics": _unresolved_semantics(journey["contract"]["required_semantics"]),
            "context_packs": [],
            "semantic_bindings": [],
            "overlay_status": "blocked",
            "reasons": [],
            "invalid": False,
            "optional_context_complete": True,
            "provider_rpc_called": False,
            "provider_internal_io_controlled": False,
            "provider_internal_network": "not_applicable",
        }
        try:
            result["overlay"] = self._overlay(
                journey,
                skill,
                source_revision=source_revision,
                observed_at=observed_at,
            )
            result["semantics"], result["semantic_bindings"], semantic_reasons = (
                self._semantics(journey, result["overlay"], scope)
            )
            context = resolve_project_context(
                workspace=self._workspace,
                journey=journey,
                skill=skill,
                overlay=result["overlay"],
                semantics=result["semantics"],
                scope=scope,
                source_revision=source_revision,
                observed_at=observed_at,
                external_context=self._external_context,
            )
            result["context_packs"] = context["context_packs"]
            result["optional_context_complete"] = context[
                "optional_context_complete"
            ]
            result["provider_rpc_called"] = context["provider_rpc_called"]
            result["provider_internal_io_controlled"] = context[
                "provider_internal_io_controlled"
            ]
            result["provider_internal_network"] = context[
                "provider_internal_network"
            ]
            context_reasons = context["reason_codes"]
            result["reasons"] = [*semantic_reasons, *context_reasons]
            result["overlay_status"] = "resolved"
        except (
            ProjectSkillOverlayError,
            SemanticContractError,
            ContextContractError,
            ExternalContextBindingError,
        ) as exc:
            result["reasons"] = [exc.reason_code]
            result["invalid"] = isinstance(exc, SemanticContractError) or exc.reason_code.endswith("_INVALID")
        return result

    def _snapshot(
        self,
        journey: Mapping[str, Any],
        status: str,
        local: Mapping[str, Any],
        project: Mapping[str, Any],
        *,
        input_schema_version: str | None,
    ) -> dict[str, Any]:
        return build_execution_snapshot(
            status="resolved" if status == "verified" else "blocked",
            journey=_journey_reference(journey),
            skill=_skill_reference(local["skill"]),
            project_overlay=_overlay_reference(project["overlay"]),
            capabilities=local["capability_refs"],
            semantics=[_semantic_reference(item) for item in project["semantics"]],
            operators=[
                _operator_reference(item)
                for item in local["operators"]["dependencies"]
            ],
            models=[
                _model_reference(item) for item in local["models"]["dependencies"]
            ],
            context_packs=[
                _context_reference(item) for item in project["context_packs"]
            ],
            contracts={
                "input_schema_version": input_schema_version,
                "analysis_result_schema_version": "gravity.analysis-result.v1",
                "execution_mode": journey["contract"]["execution"]["mode"],
                "execution_owner": journey["contract"]["execution"]["owner"],
            },
        )

    def _readiness(
        self,
        journey: Mapping[str, Any],
        status: str,
        reasons: list[str],
        local: Mapping[str, Any],
        project: Mapping[str, Any],
        snapshot: Mapping[str, Any],
    ) -> dict[str, Any]:
        skill = local["skill"]
        overlay = project["overlay"]
        claim_policy = _resolved_claim_policy(
            skill, optional_context_complete=project["optional_context_complete"]
        )
        return {
            "schema_version": SCHEMA_VERSION,
            "ok": status == "verified",
            "status": status,
            "journey": _journey_reference(journey),
            "skill": _skill_reference(skill),
            "project_overlay": _overlay_reference(overlay),
            "lifecycle": {
                "journey": journey["contract"]["lifecycle"],
                "skill": skill["contract"]["lifecycle"] if skill is not None else None,
            },
            "readiness": {
                "declared": skill["contract"]["readiness"] if skill is not None else None,
                "resolved": status,
            },
            "validation": (
                skill["contract"]["validation"] if skill is not None else None
            ),
            "claim_policy": claim_policy,
            "dependencies": {
                "capabilities": copy.deepcopy(local["capabilities"]),
                "semantics": copy.deepcopy(project["semantics"]),
                "operators": copy.deepcopy(local["operators"]["dependencies"]),
                "models": copy.deepcopy(local["models"]["dependencies"]),
                "context_packs": copy.deepcopy(project["context_packs"]),
            },
            "semantic_bindings": copy.deepcopy(project["semantic_bindings"]),
            "default_scope": (
                copy.deepcopy(overlay["contract"]["default_scope"])
                if overlay is not None
                else None
            ),
            "overlay_status": project["overlay_status"],
            "request_budget": copy.deepcopy(journey["contract"]["request_budget"]),
            "reason_codes": reasons,
            "execution_snapshot": copy.deepcopy(snapshot),
            "provider_rpc_called": project["provider_rpc_called"],
            "provider_internal_io_controlled": project[
                "provider_internal_io_controlled"
            ],
            "provider_internal_network": project["provider_internal_network"],
            "network_called": False,
        }

    def _capabilities(
        self, contract: Mapping[str, Any]
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str], list[str]]:
        results: list[dict[str, Any]] = []
        references: list[dict[str, Any]] = []
        states: list[str] = []
        reasons: list[str] = []
        for requirement in contract["required_capabilities"]:
            result = self._capability_trust.trust(
                str(requirement["identity_kind"]), str(requirement["selector"])
            )
            state, selected = assess_capability_requirement(result, requirement)
            results.append(result)
            references.append(_capability_reference(result, requirement, state))
            states.append(state)
            reasons.extend(selected)
        return results, references, states, reasons

    def _overlay(
        self,
        journey: Mapping[str, Any],
        skill: Mapping[str, Any] | None,
        *,
        source_revision: str | None,
        observed_at: str | None,
    ) -> dict[str, Any]:
        contract = journey["contract"]
        path = contract.get("project_contract_path")
        root = getattr(self._workspace, "root", None)
        if not isinstance(path, str) or not path or root is None:
            raise ProjectSkillOverlayError(
                "PROJECT_SKILL_OVERLAY_MISSING",
                "Journey does not bind one Project Skill Overlay",
            )
        overlay = load_project_skill_overlay(
            Path(root),
            contract_path=path,
            source_revision=source_revision,
            observed_at=observed_at,
        )
        selected = overlay["contract"]
        expected_skill = skill["skill_uri"] if skill is not None else contract["required_skill"]
        if (
            selected["extends"]["skill_uri"] != expected_skill
            or selected["journey_id"] != contract["journey_id"]
            or selected["owner"] != contract["owner"]
            or not str(contract.get("calling_project") or "").endswith(
                "/" + selected["project_id"]
            )
        ):
            raise ProjectSkillOverlayError(
                "PROJECT_SKILL_OVERLAY_CONFLICT",
                "Project Skill Overlay disagrees with the exact Journey and Skill",
            )
        return overlay

    def _semantics(
        self,
        journey: Mapping[str, Any],
        overlay: Mapping[str, Any],
        scope: Mapping[str, Any],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
        registry = SemanticRegistry(overlay["semantic_sources"])
        app_alias = scope["app_alias"] or overlay["contract"]["default_scope"]["app_alias"]
        start, end = _combined_window(scope["windows"])
        dependencies = registry.dependencies(
            journey["contract"]["required_semantics"],
            project_id=overlay["contract"]["project_id"],
            app_alias=app_alias,
            start=start,
            end=end,
        )
        bindings: list[dict[str, Any]] = []
        reasons = list(dependencies["reason_codes"])
        for resolution in dependencies["dependencies"]:
            if not resolution.get("ok"):
                continue
            definition = resolution["definition"]["contract"]
            binding = resolution.get("binding")
            if definition["authority"] == "project" and definition["owner"] != overlay["contract"]["owner"]:
                reasons.append("SEMANTIC_OWNER_CONFLICT")
            if binding is not None:
                bound = binding["contract"]
                if (
                    bound["project_id"] != overlay["contract"]["project_id"]
                    or bound["owner"] != overlay["contract"]["owner"]
                    or bound["app_alias"] != app_alias
                ):
                    reasons.append("SEMANTIC_BINDING_CONFLICT")
                bindings.append(copy.deepcopy(bound))
        reasons.extend(_execution_binding_reasons(journey, bindings))
        return copy.deepcopy(dependencies["dependencies"]), bindings, reasons

def _journey(journey_id: Any) -> dict[str, Any]:
    if not isinstance(journey_id, str) or not journey_id.strip():
        raise InputValidationError(
            "actual value: empty; journey_id must be an exact registered identity",
            field="journey_id",
            next_action="Run `gravity journey list` and use an exact journey_id.",
        )
    artifact = journey_artifact(journey_id.strip())
    if artifact is None:
        raise InputValidationError(
            f"actual value: {actual_value(journey_id)}; journey_id is not registered",
            field="journey_id",
            next_action="Run `gravity journey list` and use an exact journey_id.",
        )
    return artifact


def _scope(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {"app_alias", "windows"}:
        raise InputValidationError(
            "actual value: invalid object; Core Skill scope fields changed",
            field="scope",
            next_action="Pass app_alias plus one to eight explicit start/end windows.",
        )
    app_alias = value["app_alias"]
    if app_alias is not None and (not isinstance(app_alias, str) or not app_alias):
        raise InputValidationError(
            "actual value: invalid; app_alias is invalid",
            field="scope.app_alias",
            next_action="Use the exact project App alias or null to use Overlay default_scope.",
        )
    windows = value["windows"]
    if not isinstance(windows, Mapping) or not 1 <= len(windows) <= 8:
        raise InputValidationError(
            "actual value: invalid; windows are invalid",
            field="scope.windows",
            next_action="Pass one to eight named windows with canonical start and end dates.",
        )
    normalized: dict[str, dict[str, str]] = {}
    for name, window in windows.items():
        if (
            not isinstance(name, str)
            or not name
            or not isinstance(window, Mapping)
            or set(window) != {"start", "end"}
        ):
            raise InputValidationError(
                "actual value: invalid; window fields changed",
                field="scope.windows",
                next_action="Use each window name once with exactly start and end fields.",
            )
        start, end = _day(window["start"]), _day(window["end"])
        if start > end:
            raise InputValidationError(
                "actual value: reversed; window is invalid",
                field="scope.windows",
                next_action="Choose a window whose start date does not follow its end date.",
            )
        normalized[name] = {"start": start.isoformat(), "end": end.isoformat()}
    return {"app_alias": app_alias, "windows": dict(sorted(normalized.items()))}


def _day(value: Any) -> date:
    try:
        selected = date.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        selected = None
    if selected is None or selected.isoformat() != value:
        raise InputValidationError(
            "actual value: invalid; date must be YYYY-MM-DD",
            field="scope.windows",
            next_action="Use canonical YYYY-MM-DD dates and retry.",
        )
    return selected


def _combined_window(windows: Mapping[str, Mapping[str, str]]) -> tuple[str, str]:
    return (
        min(window["start"] for window in windows.values()),
        max(window["end"] for window in windows.values()),
    )


def _status(
    *, reasons: Sequence[str], capability_states: Sequence[str], project_error_invalid: bool
) -> str:
    if project_error_invalid:
        return "invalid"
    if reasons:
        return "blocked"
    if "unknown" in capability_states or not capability_states:
        return "unknown"
    return "verified" if all(state == "stable" for state in capability_states) else "blocked"


def _execution_binding_reasons(
    journey: Mapping[str, Any], bindings: Sequence[Mapping[str, Any]]
) -> list[str]:
    owner = journey["contract"]["execution"]["owner"]
    if owner != "metric-anomaly-localization@1" or not bindings:
        return []
    if len(bindings) != 1:
        return ["SEMANTIC_BINDING_AMBIGUOUS"]
    from .analysis_playbook_catalog import bind_metric_anomaly_playbook_definition

    try:
        bind_metric_anomaly_playbook_definition(bindings[0])
    except ContractChangedError:
        return ["SEMANTIC_EXECUTION_BINDING_INVALID"]
    return []


def _resolved_claim_policy(
    skill: Mapping[str, Any] | None, *, optional_context_complete: bool
) -> dict[str, Any] | None:
    if skill is None:
        return None
    policy = skill["contract"]["claim_policy"]
    restricted = (
        []
        if optional_context_complete
        else list(policy["forbidden_without_context"])
    )
    return {
        "allowed": [
            claim for claim in policy["allowed"] if claim not in set(restricted)
        ],
        "forbidden": list(dict.fromkeys([*policy["forbidden"], *restricted])),
        "forbidden_without_context": list(policy["forbidden_without_context"]),
        "optional_context_complete": optional_context_complete,
    }


__all__ = ["CoreSkillRuntime", "CoreSkillRuntimeError", "SCHEMA_VERSION"]
