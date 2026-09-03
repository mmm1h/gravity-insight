"""Local Outcome Handoff binding for the significance-test Operator."""

from __future__ import annotations

import copy
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from ..operator_ids import SIGNIFICANCE_TEST_URI


def evaluate_experiment_outcome(
    request: Mapping[str, Any],
    *,
    operators: Any,
    validate_handoff: Callable[[Mapping[str, Any]], dict[str, Any]],
    error_type: type[Exception],
) -> dict[str, Any]:
    selected = _request(request, error_type)
    handoff = validate_handoff(selected["handoff"])
    if handoff["status"] != "handoff_ready":
        raise error_type(
            "Outcome evaluation requires a handoff_ready external observation"
        )
    if handoff["outcome_journey"]["can_run_status"] != "verified":
        raise error_type("Outcome evaluation Journey dependencies are not verified")
    return operators.execute(
        SIGNIFICANCE_TEST_URI,
        _operator_input(selected, handoff, error_type),
    )


def _request(
    value: Mapping[str, Any], error_type: type[Exception]
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise error_type("Outcome evaluation request must be an object")
    required = {
        "handoff",
        "recommendation_run_id",
        "observation_run_id",
        "evaluation_run_id",
        "test",
        "metrics",
    }
    if set(value) != required:
        raise error_type("Outcome evaluation request fields are not exact")
    selected = copy.deepcopy(dict(value))
    if not isinstance(selected["handoff"], Mapping):
        raise error_type("Outcome evaluation handoff must be an object")
    if not isinstance(selected["test"], Mapping):
        raise error_type("Outcome evaluation test must be an object")
    metrics = selected["metrics"]
    if isinstance(metrics, (str, bytes)) or not isinstance(metrics, Sequence):
        raise error_type("Outcome evaluation metrics must be an array")
    return selected


def _operator_input(
    request: Mapping[str, Any],
    handoff: Mapping[str, Any],
    error_type: type[Exception],
) -> dict[str, Any]:
    evidence_window = copy.deepcopy(handoff["evidence_window"])
    return {
        "schema_version": "gravity.operator-input.significance-test.v1",
        "claim": "experiment-outcome-observation",
        "recommendation": {
            "digest": handoff["proposal"]["proposal_digest"],
            "producer_run_id": request["recommendation_run_id"],
            "window": copy.deepcopy(handoff["source_analysis"]["source_window"]),
        },
        "observation": {
            "source": "external",
            "digest": handoff["experiment"]["evidence_digest"],
            "assignment_digest": handoff["experiment"]["assignment_digest"],
            "producer_run_id": request["observation_run_id"],
            "window": copy.deepcopy(evidence_window),
        },
        "evidence_window": evidence_window,
        "evaluation_run_id": request["evaluation_run_id"],
        "test": copy.deepcopy(request["test"]),
        "metrics": _metrics(request["metrics"], handoff, error_type),
        "unit": "proportion",
        "additivity": "non_additive",
    }


def _metrics(
    values: Sequence[Any],
    handoff: Mapping[str, Any],
    error_type: type[Exception],
) -> list[dict[str, Any]]:
    provided = _provided_metrics(values, error_type)
    expected: list[tuple[Mapping[str, Any], str]] = []
    if handoff["primary_metric"] is not None:
        expected.append((handoff["primary_metric"], "primary"))
    expected.extend((item, "guardrail") for item in handoff["guardrails"])
    if set(provided) != {str(item["uri"]) for item, _role in expected}:
        raise error_type(
            "Outcome evaluation metrics do not match the Handoff metric family"
        )
    alternatives = {
        "increase": "greater",
        "decrease": "less",
        "two_sided": "two_sided",
    }
    return [
        {
            "metric_uri": item["uri"],
            "role": role,
            "alternative": alternatives[item["direction"]],
            "control": copy.deepcopy(provided[str(item["uri"])]["control"]),
            "treatment": copy.deepcopy(provided[str(item["uri"])]["treatment"]),
        }
        for item, role in expected
    ]


def _provided_metrics(
    values: Sequence[Any], error_type: type[Exception]
) -> dict[str, Mapping[str, Any]]:
    provided: dict[str, Mapping[str, Any]] = {}
    for value in values:
        if not isinstance(value, Mapping) or set(value) != {
            "metric_uri",
            "control",
            "treatment",
        }:
            raise error_type("Outcome evaluation metric fields are not exact")
        uri = str(value["metric_uri"])
        if uri in provided:
            raise error_type("Outcome evaluation metric URIs are duplicated")
        provided[uri] = value
    return provided


__all__ = ["evaluate_experiment_outcome"]
