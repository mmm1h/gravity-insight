"""Independent Outcome Evaluation handoff; no outcome computation occurs here."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from datetime import date
from typing import Any
from zoneinfo import ZoneInfo

from .agent_runtime_contracts import canonical_digest
from .experiment_handoff import (
    ExperimentContractError,
    OUTCOME_JOURNEY_ID,
    OUTCOME_SCHEMA_VERSION,
    _datetime,
    _timestamp,
    _validated,
    _window,
    _without,
    validate_experiment_proposal,
)
from .journey_contract import journey_artifact
from .operator_registry import OperatorRegistry


_REQUEST_SCHEMA = "outcome-evaluation-handoff-request-v1.schema.json"
_SCHEMA = "outcome-evaluation-handoff-v1.schema.json"


def compile_outcome_evaluation_handoff(
    request: Mapping[str, Any],
    *,
    operators: OperatorRegistry | None = None,
) -> dict[str, Any]:
    selected = _validated(request, _REQUEST_SCHEMA, "Outcome request")
    proposal = validate_experiment_proposal(selected["proposal"])
    observation = _observation(selected["observation"])
    _validate_observation_binding(proposal, observation)
    evidence_window = _window(selected["evidence_window"], "evidence_window")
    alignment = _window_alignment(
        proposal["source_analysis"]["source_window"],
        evidence_window,
        observation,
    )
    outcome_journey = _outcome_journey(
        proposal["source_analysis"]["journey"]["journey_id"],
        operators or OperatorRegistry(),
    )
    reasons = _handoff_reasons(proposal, observation, alignment, outcome_journey)
    body = _handoff_body(
        selected,
        proposal,
        observation,
        evidence_window,
        alignment,
        outcome_journey,
        reasons,
    )
    handoff_id = "out1_" + canonical_digest(body)[:32]
    handoff = {"handoff_id": handoff_id, **body}
    handoff["handoff_digest"] = canonical_digest(handoff)
    return validate_outcome_evaluation_handoff(handoff)


def validate_outcome_evaluation_handoff(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    handoff = _validated(value, _SCHEMA, "Outcome Evaluation Handoff")
    source_window = _window(
        handoff["source_analysis"]["source_window"], "source_window"
    )
    evidence_window = _window(handoff["evidence_window"], "evidence_window")
    started = _timestamp(handoff["experiment"]["started_at"], "started_at")
    ended = _timestamp(handoff["experiment"]["ended_at"], "ended_at")
    if _datetime(started) >= _datetime(ended):
        raise ExperimentContractError("Experiment observation window is invalid")
    if handoff["experiment"]["status"] == "completed" and (
        handoff["experiment"]["assignment_digest"] is None
        or handoff["experiment"]["evidence_digest"] is None
    ):
        raise ExperimentContractError(
            "Completed observation requires assignment and evidence digests"
        )
    _timestamp(handoff["created_at"], "created_at")
    body = _without(handoff, "handoff_id", "handoff_digest")
    if handoff["handoff_id"] != "out1_" + canonical_digest(body)[:32]:
        raise ExperimentContractError("Outcome Handoff identity changed")
    if handoff["handoff_digest"] != canonical_digest(
        _without(handoff, "handoff_digest")
    ):
        raise ExperimentContractError("Outcome Handoff digest changed")
    alignment = _window_alignment(
        source_window,
        evidence_window,
        handoff["experiment"],
    )
    journey = {
        **handoff["outcome_journey"],
        "journey_distinct": handoff["outcome_journey"]["journey_id"]
        != handoff["source_analysis"]["journey"]["journey_id"],
    }
    expected_reasons = _handoff_reasons(
        handoff["proposal"], handoff["experiment"], alignment, journey
    )
    expected_independence = {
        "journey_distinct": journey["journey_distinct"],
        "evidence_window_separate": alignment["window_separate"],
        "same_run_evaluation_allowed": False,
        "recommendation_self_validation_allowed": False,
    }
    if (
        handoff["reason_codes"] != expected_reasons
        or handoff["independence"] != expected_independence
        or (handoff["status"] == "handoff_ready") != (not expected_reasons)
    ):
        raise ExperimentContractError("Outcome Handoff status contradicts blockers")
    return handoff


def _observation(value: Mapping[str, Any]) -> dict[str, Any]:
    observation = _validated(
        value, "experiment-observation-v1.schema.json", "Experiment observation"
    )
    started = _timestamp(observation["started_at"], "started_at")
    ended = _timestamp(observation["ended_at"], "ended_at")
    if _datetime(started) >= _datetime(ended):
        raise ExperimentContractError("Experiment observation window is invalid")
    if observation["status"] == "completed" and (
        observation["assignment_digest"] is None
        or observation["evidence_digest"] is None
    ):
        raise ExperimentContractError(
            "Completed observation requires assignment and evidence digests"
        )
    return observation


def _validate_observation_binding(
    proposal: Mapping[str, Any], observation: Mapping[str, Any]
) -> None:
    if (
        observation["proposal_id"] != proposal["proposal_id"]
        or observation["proposal_digest"] != proposal["proposal_digest"]
    ):
        raise ExperimentContractError(
            "Experiment observation is not bound to the Proposal"
        )


def _window_alignment(
    source_window: Mapping[str, Any],
    evidence_window: Mapping[str, Any],
    observation: Mapping[str, Any],
) -> dict[str, bool]:
    evidence_zone = ZoneInfo(evidence_window["timezone"])
    matches = (
        evidence_window["start"]
        == _datetime(observation["started_at"]).astimezone(evidence_zone).date().isoformat()
        and evidence_window["end"]
        == _datetime(observation["ended_at"]).astimezone(evidence_zone).date().isoformat()
    )
    return {
        "window_matches": matches,
        "timezone_matches": evidence_window["timezone"] == source_window["timezone"],
        "window_separate": date.fromisoformat(evidence_window["start"])
        > date.fromisoformat(source_window["end"]),
    }


def _outcome_journey(
    source_journey_id: str, operators: OperatorRegistry
) -> dict[str, Any]:
    artifact = journey_artifact(OUTCOME_JOURNEY_ID)
    if artifact is None:
        raise ExperimentContractError("Outcome Evaluation Journey is missing")
    contract = artifact["contract"]
    dependencies = operators.dependencies(contract["required_operators"])
    return {
        "journey_id": contract["journey_id"],
        "version": contract["version"],
        "digest": artifact["digest"],
        "can_run_status": "verified" if dependencies["ok"] else "blocked",
        "reason_codes": sorted(set(dependencies["reason_codes"])),
        "journey_distinct": contract["journey_id"] != source_journey_id,
    }


def _handoff_reasons(
    proposal: Mapping[str, Any],
    observation: Mapping[str, Any],
    alignment: Mapping[str, bool],
    outcome_journey: Mapping[str, Any],
) -> list[str]:
    checks = (
        (proposal["status"] != "ready_for_review", "EXPERIMENT_PROPOSAL_NOT_READY"),
        (observation["status"] != "completed", "EXPERIMENT_OBSERVATION_INCOMPLETE"),
        (not alignment["window_matches"], "OUTCOME_EVIDENCE_WINDOW_MISMATCH"),
        (not alignment["timezone_matches"], "OUTCOME_EVIDENCE_TIMEZONE_MISMATCH"),
        (not alignment["window_separate"], "OUTCOME_EVIDENCE_WINDOW_NOT_SEPARATE"),
        (not outcome_journey["journey_distinct"], "OUTCOME_JOURNEY_NOT_DISTINCT"),
    )
    return sorted(reason for failed, reason in checks if failed)


def _handoff_body(
    request: Mapping[str, Any],
    proposal: Mapping[str, Any],
    observation: Mapping[str, Any],
    evidence_window: Mapping[str, Any],
    alignment: Mapping[str, bool],
    outcome_journey: Mapping[str, Any],
    reasons: list[str],
) -> dict[str, Any]:
    return {
        "schema_version": OUTCOME_SCHEMA_VERSION,
        "status": "handoff_ready" if not reasons else "blocked",
        "proposal": {
            "proposal_id": proposal["proposal_id"],
            "proposal_digest": proposal["proposal_digest"],
            "status": proposal["status"],
        },
        "experiment": {
            key: copy.deepcopy(observation[key])
            for key in (
                "experiment_ref",
                "status",
                "started_at",
                "ended_at",
                "assignment_digest",
                "evidence_digest",
            )
        },
        "source_analysis": {
            key: copy.deepcopy(proposal["source_analysis"][key])
            for key in ("result_digest", "journey", "scope_digest", "source_window")
        },
        "outcome_journey": {
            key: copy.deepcopy(outcome_journey[key])
            for key in ("journey_id", "version", "digest", "can_run_status", "reason_codes")
        },
        "evidence_window": copy.deepcopy(evidence_window),
        "primary_metric": copy.deepcopy(proposal["primary_metric"]),
        "guardrails": copy.deepcopy(proposal["guardrails"]),
        "independence": {
            "journey_distinct": outcome_journey["journey_distinct"],
            "evidence_window_separate": alignment["window_separate"],
            "same_run_evaluation_allowed": False,
            "recommendation_self_validation_allowed": False,
        },
        "reason_codes": reasons,
        "evaluation_performed": False,
        "created_at": _timestamp(request["created_at"], "created_at"),
        "network_called": False,
    }


__all__ = [
    "compile_outcome_evaluation_handoff",
    "validate_outcome_evaluation_handoff",
]
