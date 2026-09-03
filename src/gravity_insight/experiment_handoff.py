"""Offline Experiment Proposal and independent Outcome Evaluation handoff."""

from __future__ import annotations

import copy
import math
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .agent_runtime_contracts import (
    AgentRuntimeContractError,
    canonical_digest,
    validate_schema,
)
from .analysis_result_contract import (
    AnalysisResultContractError,
    compile_analysis_result,
)
from .execution_snapshot import ExecutionSnapshotError, compile_execution_snapshot
from .operator_registry import OperatorRegistry


POWER_SCHEMA_VERSION = "gravity.experiment-power-analysis.v1"
PROPOSAL_REQUEST_SCHEMA_VERSION = "gravity.experiment-proposal-request.v1"
PROPOSAL_SCHEMA_VERSION = "gravity.experiment-proposal.v1"
OUTCOME_REQUEST_SCHEMA_VERSION = "gravity.outcome-evaluation-handoff-request.v1"
OUTCOME_SCHEMA_VERSION = "gravity.outcome-evaluation-handoff.v1"
OUTCOME_JOURNEY_ID = "analysis.experiment-outcome-evaluation"

_POWER_SCHEMA = "experiment-power-analysis-v1.schema.json"
_PROPOSAL_REQUEST_SCHEMA = "experiment-proposal-request-v1.schema.json"
_PROPOSAL_SCHEMA = "experiment-proposal-v1.schema.json"
_SATISFIED = "satisfied"


class ExperimentContractError(AgentRuntimeContractError):
    """An Experiment or Outcome handoff contradicts its evidence."""


class ExperimentHandoffService:
    """Compile inert proposal/handoff artifacts without target I/O."""

    def __init__(self, *, operators: OperatorRegistry | None = None) -> None:
        self._operators = operators or OperatorRegistry()

    def propose(self, request: Mapping[str, Any]) -> dict[str, Any]:
        return compile_experiment_proposal(request)

    def outcome_handoff(self, request: Mapping[str, Any]) -> dict[str, Any]:
        return compile_outcome_evaluation_handoff(
            request, operators=self._operators
        )

    def evaluate(self, request: Mapping[str, Any]) -> dict[str, Any]:
        """Evaluate aggregate binary outcomes from one independent Handoff."""

        from .operators.experiment_outcome import evaluate_experiment_outcome

        return evaluate_experiment_outcome(
            request,
            operators=self._operators,
            validate_handoff=validate_outcome_evaluation_handoff,
            error_type=ExperimentContractError,
        )


def compile_experiment_power_analysis(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    selected = _validated(value, _POWER_SCHEMA, "Experiment power analysis")
    status = selected["status"]
    evidence_fields = (
        "operator",
        "primary_metric_uri",
        "target_segment_digest",
        "alpha",
        "power",
        "minimum_detectable_effect",
        "minimum_sample_size_per_arm",
    )
    if status == "complete":
        if any(selected[field] is None for field in evidence_fields):
            raise ExperimentContractError(
                "Complete power analysis is missing required evidence"
            )
        if selected["reason_codes"]:
            raise ExperimentContractError(
                "Complete power analysis cannot carry blockers"
            )
        _probability(selected["alpha"], "alpha")
        _probability(selected["power"], "power")
        _positive_number(
            selected["minimum_detectable_effect"], "minimum_detectable_effect"
        )
        expected = canonical_digest(_without(selected, "result_digest"))
        if selected["result_digest"] != expected:
            raise ExperimentContractError("Power analysis digest changed")
    else:
        if any(selected[field] is not None for field in evidence_fields):
            raise ExperimentContractError(
                "Unavailable power analysis cannot carry computed evidence"
            )
        if not selected["reason_codes"] or selected["result_digest"] is not None:
            raise ExperimentContractError(
                "Unavailable power analysis requires blockers and no digest"
            )
    return selected


def compile_experiment_proposal(
    request: Mapping[str, Any],
) -> dict[str, Any]:
    selected = _validated(request, _PROPOSAL_REQUEST_SCHEMA, "Experiment request")
    try:
        analysis = compile_analysis_result(selected["source_analysis_result"])
        snapshot = compile_execution_snapshot(selected["planning_snapshot"])
    except (AnalysisResultContractError, ExecutionSnapshotError) as exc:
        raise ExperimentContractError(str(exc)) from exc
    if analysis["status"] != "success" or analysis["can_run_status"] != "verified":
        raise ExperimentContractError(
            "Experiment Proposal requires a verified successful Analysis Result"
        )
    if snapshot["status"] != "resolved":
        raise ExperimentContractError(
            "Experiment planning snapshot must be resolved"
        )
    if (
        snapshot["journey"] != analysis["journey"]
        or snapshot["runtime"] != analysis["execution_snapshot"]["runtime"]
    ):
        raise ExperimentContractError(
            "Experiment planning snapshot changed the source Journey or Runtime"
        )

    source_window = _window(selected["source_window"], "source_window")
    window_verified = _scope_window(analysis.get("scope")) == source_window
    target = copy.deepcopy(selected["target_segment"])
    semantic_by_uri = {item["uri"]: item for item in snapshot["semantics"]}
    primary, primary_status = _metric_reference(
        selected["primary_metric"], semantic_by_uri, role="primary"
    )
    guardrails, guardrail_status = _guardrail_references(
        selected["guardrails"], semantic_by_uri, primary
    )
    assumptions, assumption_status = _context_assumptions(
        selected["context_assumptions"], snapshot["context_packs"]
    )
    power, power_status, power_reasons = _power_reference(
        selected["power_analysis"], snapshot, primary, target
    )
    readiness = {
        "source_window": _SATISFIED if window_verified else "unresolved",
        "target_segment": _SATISFIED if target is not None else "missing",
        "primary_metric": primary_status,
        "guardrails": guardrail_status,
        "power_analysis": power_status,
        "context_assumptions": assumption_status,
    }
    reasons = _proposal_reasons(readiness, power_reasons)
    body = {
        "schema_version": PROPOSAL_SCHEMA_VERSION,
        "status": "ready_for_review" if not reasons else "proposal_only",
        "source_analysis": _source_analysis_reference(
            analysis, source_window, window_verified
        ),
        "planning_snapshot_digest": snapshot["snapshot_digest"],
        "hypothesis": {**copy.deepcopy(selected["hypothesis"]), "role": "data"},
        "target_segment": target,
        "primary_metric": primary,
        "guardrails": guardrails,
        "power_analysis": power,
        "context_assumptions": assumptions,
        "readiness": readiness,
        "reason_codes": reasons,
        "experiment_creation_authorized": False,
        "automatic_execution": False,
        "created_at": _timestamp(selected["created_at"], "created_at"),
        "network_called": False,
    }
    proposal_id = "exp1_" + canonical_digest(body)[:32]
    proposal = {"proposal_id": proposal_id, **body}
    proposal["proposal_digest"] = canonical_digest(proposal)
    return validate_experiment_proposal(proposal)


def validate_experiment_proposal(value: Mapping[str, Any]) -> dict[str, Any]:
    proposal = _validated(value, _PROPOSAL_SCHEMA, "Experiment Proposal")
    _window(proposal["source_analysis"]["source_window"], "source_window")
    _timestamp(proposal["created_at"], "created_at")
    power = proposal.get("power_analysis")
    if power is not None:
        proposal["power_analysis"] = compile_experiment_power_analysis(power)
    identity_body = _without(proposal, "proposal_id", "proposal_digest")
    if proposal["proposal_id"] != "exp1_" + canonical_digest(identity_body)[:32]:
        raise ExperimentContractError("Experiment Proposal identity changed")
    if proposal["proposal_digest"] != canonical_digest(
        _without(proposal, "proposal_digest")
    ):
        raise ExperimentContractError("Experiment Proposal digest changed")
    ready = all(value == _SATISFIED for value in proposal["readiness"].values())
    if (proposal["status"] == "ready_for_review") != ready:
        raise ExperimentContractError(
            "Experiment Proposal status contradicts dependency readiness"
        )
    _validate_proposal_reasons(proposal, ready)
    return proposal


def compile_outcome_evaluation_handoff(
    request: Mapping[str, Any],
    *,
    operators: OperatorRegistry | None = None,
) -> dict[str, Any]:
    from .outcome_evaluation_handoff import compile_outcome_evaluation_handoff as impl

    return impl(request, operators=operators)


def validate_outcome_evaluation_handoff(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    from .outcome_evaluation_handoff import validate_outcome_evaluation_handoff as impl

    return impl(value)


def _metric_reference(
    request: Mapping[str, Any] | None,
    semantic_by_uri: Mapping[str, Mapping[str, Any]],
    *,
    role: str,
) -> tuple[dict[str, Any] | None, str]:
    if request is None:
        return None, "missing"
    uri = str(request["uri"])
    semantic = semantic_by_uri.get(uri)
    if semantic is None:
        return {
            "uri": uri,
            "version": None,
            "definition_digest": None,
            "binding_digest": None,
            "registry_digest": None,
            "status": "unresolved",
            "direction": request[
                "success_direction" if role == "primary" else "breach_direction"
            ],
        }, "unresolved"
    direction = request[
        "success_direction" if role == "primary" else "breach_direction"
    ]
    reference = {
        "uri": semantic["uri"],
        "version": semantic["version"],
        "definition_digest": semantic["definition_digest"],
        "binding_digest": semantic["binding_digest"],
        "registry_digest": semantic["registry_digest"],
        "status": semantic["status"],
        "direction": direction,
    }
    resolved = (
        semantic["status"] == "resolved"
        and semantic["version"] is not None
        and all(
            semantic[field] is not None
            for field in ("definition_digest", "binding_digest", "registry_digest")
        )
    )
    return reference, _SATISFIED if resolved else "unresolved"


def _guardrail_references(
    requests: Sequence[Mapping[str, Any]],
    semantic_by_uri: Mapping[str, Mapping[str, Any]],
    primary: Mapping[str, Any] | None,
) -> tuple[list[dict[str, Any]], str]:
    if not requests:
        return [], "missing"
    uris = [str(item["uri"]) for item in requests]
    if len(uris) != len(set(uris)) or (
        primary is not None and primary["uri"] in uris
    ):
        raise ExperimentContractError(
            "Experiment Metric roles contain duplicate or conflicting URIs"
        )
    values = [
        _metric_reference(item, semantic_by_uri, role="guardrail")
        for item in requests
    ]
    return [item[0] for item in values if item[0] is not None], (
        _SATISFIED if all(item[1] == _SATISFIED for item in values) else "unresolved"
    )


def _context_assumptions(
    values: Sequence[Mapping[str, Any]],
    references: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], str]:
    if not values:
        return [], "missing"
    ids = [str(item["assumption_id"]) for item in values]
    if len(ids) != len(set(ids)):
        raise ExperimentContractError("Context assumption IDs are duplicated")
    available = {
        (item["requirement_uri"], item["pack_digest"])
        for item in references
        if item.get("status") == "available" and item.get("pack_digest") is not None
    }
    selected = [copy.deepcopy(dict(item)) for item in values]
    resolved = all(
        (item["requirement_uri"], item["pack_digest"]) in available
        for item in selected
    )
    selected.sort(key=lambda item: item["assumption_id"])
    return selected, _SATISFIED if resolved else "unresolved"


def _power_reference(
    value: Mapping[str, Any] | None,
    snapshot: Mapping[str, Any],
    primary: Mapping[str, Any] | None,
    target: Mapping[str, Any] | None,
) -> tuple[dict[str, Any] | None, str, list[str]]:
    if value is None:
        return None, "missing", []
    power = compile_experiment_power_analysis(value)
    if power["status"] != "complete":
        return power, "unresolved", list(power["reason_codes"])
    if (
        primary is None
        or target is None
        or power["primary_metric_uri"] != primary["uri"]
        or power["target_segment_digest"] != target["digest"]
    ):
        return power, "unresolved", ["EXPERIMENT_POWER_BINDING_MISMATCH"]
    operator = power["operator"]
    matched = any(
        all(item.get(field) == operator.get(field) for field in (
            "uri", "version", "digest", "assumptions_digest"
        ))
        and item.get("status") == "available"
        for item in snapshot["operators"]
    )
    return (
        (power, _SATISFIED, [])
        if matched
        else (power, "unresolved", ["EXPERIMENT_POWER_OPERATOR_UNRESOLVED"])
    )


def _proposal_reasons(
    readiness: Mapping[str, str], power_reasons: Sequence[str]
) -> list[str]:
    reasons = {
        ("source_window", "unresolved"): "EXPERIMENT_SOURCE_WINDOW_UNPROVEN",
        ("target_segment", "missing"): "EXPERIMENT_TARGET_SEGMENT_MISSING",
        ("primary_metric", "missing"): "EXPERIMENT_PRIMARY_METRIC_MISSING",
        ("primary_metric", "unresolved"): "EXPERIMENT_PRIMARY_METRIC_UNRESOLVED",
        ("guardrails", "missing"): "EXPERIMENT_GUARDRAILS_MISSING",
        ("guardrails", "unresolved"): "EXPERIMENT_GUARDRAILS_UNRESOLVED",
        ("power_analysis", "missing"): "EXPERIMENT_POWER_ANALYSIS_MISSING",
        ("power_analysis", "unresolved"): "EXPERIMENT_POWER_ANALYSIS_UNRESOLVED",
        ("context_assumptions", "missing"): "EXPERIMENT_CONTEXT_ASSUMPTIONS_MISSING",
        ("context_assumptions", "unresolved"): "EXPERIMENT_CONTEXT_ASSUMPTIONS_UNRESOLVED",
    }
    selected = [
        reason
        for key, reason in reasons.items()
        if readiness.get(key[0]) == key[1]
    ]
    return sorted(set([*selected, *power_reasons]))


def _validate_proposal_reasons(
    proposal: Mapping[str, Any], ready: bool
) -> None:
    power = proposal.get("power_analysis")
    power_reasons = (
        list(power["reason_codes"])
        if isinstance(power, Mapping) and power.get("status") == "unavailable"
        else []
    )
    expected = set(_proposal_reasons(proposal["readiness"], power_reasons))
    details = {
        "EXPERIMENT_POWER_BINDING_MISMATCH",
        "EXPERIMENT_POWER_OPERATOR_UNRESOLVED",
    }
    observed_details = details.intersection(proposal["reason_codes"])
    if (
        proposal["readiness"]["power_analysis"] == "unresolved"
        and isinstance(power, Mapping)
        and power.get("status") == "complete"
    ):
        if len(observed_details) != 1:
            raise ExperimentContractError(
                "Experiment Proposal power blocker is not exact"
            )
        expected.update(observed_details)
    if list(proposal["reason_codes"]) != sorted(expected) or ready == bool(expected):
        raise ExperimentContractError(
            "Experiment Proposal blockers contradict dependency readiness"
        )


def _source_analysis_reference(
    analysis: Mapping[str, Any],
    source_window: Mapping[str, Any],
    window_verified: bool,
) -> dict[str, Any]:
    skill = analysis["skill"]
    return {
        "result_digest": canonical_digest(analysis),
        "journey": copy.deepcopy(analysis["journey"]),
        "skill": (
            {
                "uri": skill["uri"],
                "version": skill["version"],
                "package_digest": skill["package_digest"],
            }
            if skill is not None
            else None
        ),
        "snapshot_digest": analysis["execution_snapshot"]["snapshot_digest"],
        "scope_digest": canonical_digest(analysis["scope"]),
        "evidence_level": analysis["evidence_level"],
        "source_window": copy.deepcopy(source_window),
        "window_verified": window_verified,
    }


def _scope_window(scope: Any) -> dict[str, Any] | None:
    if not isinstance(scope, Mapping):
        return None
    candidates = [scope]
    candidates.extend(
        scope[key]
        for key in ("window", "current_window")
        if isinstance(scope.get(key), Mapping)
    )
    for candidate in candidates:
        if all(key in candidate for key in ("start", "end", "timezone")):
            try:
                return _window(candidate, "Analysis Result scope window")
            except ExperimentContractError:
                return None
    return None


def _window(value: Mapping[str, Any], label: str) -> dict[str, Any]:
    selected = {
        key: copy.deepcopy(value[key])
        for key in ("start", "end", "timezone")
        if key in value
    }
    try:
        start = date.fromisoformat(str(selected["start"]))
        end = date.fromisoformat(str(selected["end"]))
        ZoneInfo(str(selected["timezone"]))
    except (KeyError, TypeError, ValueError, ZoneInfoNotFoundError) as exc:
        raise ExperimentContractError(f"{label} is invalid") from exc
    if start > end:
        raise ExperimentContractError(f"{label} is reversed")
    return selected


def _timestamp(value: Any, label: str) -> str:
    selected = str(value)
    try:
        parsed = _datetime(selected)
    except ValueError as exc:
        raise ExperimentContractError(f"{label} is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ExperimentContractError(f"{label} must be UTC")
    return selected


def _datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _probability(value: Any, label: str) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or not 0 < value < 1
    ):
        raise ExperimentContractError(f"{label} must be finite and between 0 and 1")


def _positive_number(value: Any, label: str) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value <= 0
    ):
        raise ExperimentContractError(f"{label} must be a positive finite number")


def _validated(
    value: Mapping[str, Any], schema: str, label: str
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ExperimentContractError(f"{label} must be an object")
    selected = copy.deepcopy(dict(value))
    try:
        validate_schema(selected, schema, label)
    except AgentRuntimeContractError as exc:
        raise ExperimentContractError(str(exc)) from exc
    return selected


def _without(value: Mapping[str, Any], *keys: str) -> dict[str, Any]:
    return {
        key: copy.deepcopy(item)
        for key, item in value.items()
        if key not in keys
    }


__all__ = [
    "ExperimentContractError",
    "ExperimentHandoffService",
    "OUTCOME_JOURNEY_ID",
    "compile_experiment_power_analysis",
    "compile_experiment_proposal",
    "compile_outcome_evaluation_handoff",
    "validate_experiment_proposal",
    "validate_outcome_evaluation_handoff",
]
