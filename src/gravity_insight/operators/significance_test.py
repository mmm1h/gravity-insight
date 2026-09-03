"""Deterministic observational significance testing for binary outcomes."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import date
from statistics import NormalDist
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ..operator_ids import SIGNIFICANCE_TEST_RESULT_SCHEMA
from ..operator_returned_dimension_change import OperatorMethodError


_ALLOWED_CLAIM = "experiment-outcome-observation"
_MINIMUM_CELL_COUNT = 5


def significance_test(inputs: Mapping[str, Any]) -> dict[str, Any]:
    """Compare independent binary-outcome arms without making a causal claim."""

    _validate_claim(inputs["claim"])
    _validate_provenance(inputs)
    metrics = list(inputs["metrics"])
    _validate_metric_family(metrics)
    alpha = _probability(inputs["test"]["alpha"], "test.alpha")
    multiplicity = str(inputs["test"]["multiplicity"])
    if len(metrics) > 1 and multiplicity != "bonferroni":
        _fail(
            "OPERATOR_MULTIPLICITY_REQUIRED",
            "Multiple metrics require explicit Bonferroni family control.",
            "test.multiplicity",
            "Use multiplicity=bonferroni or evaluate exactly one metric.",
        )
    family_size = len(metrics)
    adjusted_alpha = alpha / family_size if multiplicity == "bonferroni" else alpha
    results = [
        _metric_result(item, index, alpha=alpha, adjusted_alpha=adjusted_alpha)
        for index, item in enumerate(metrics)
    ]
    significant = any(item["significant"] for item in results)
    assumptions = {
        "independent_arms": "caller_asserted",
        "binary_outcome": "verified_from_aggregate_counts",
        "normal_approximation": "verified",
        "minimum_observed_cell_count": _MINIMUM_CELL_COUNT,
        "pooled_null_variance": True,
        "observational_only": True,
    }
    return {
        "schema_version": SIGNIFICANCE_TEST_RESULT_SCHEMA,
        "verdict": (
            "significant_observed_difference"
            if significant
            else "no_significant_observed_difference"
        ),
        "test_specification": {
            "method": "two-proportion-z-test",
            "null_variance": "pooled-under-null",
            "tail": "per_metric",
            "alpha": _render(alpha),
            "multiplicity": multiplicity,
            "family_size": family_size,
            "per_comparison_alpha": _render(adjusted_alpha),
            "p_value_adjustment": multiplicity,
            "confidence_interval": "two-sided-unpooled-wald-risk-difference",
            "decision_rule": "adjusted_p_value <= alpha",
        },
        "assumptions": assumptions,
        "provenance": {
            "recommendation_digest": inputs["recommendation"]["digest"],
            "observation_digest": inputs["observation"]["digest"],
            "assignment_digest": inputs["observation"]["assignment_digest"],
            "observation_source": "external",
            "recommendation_window": dict(inputs["recommendation"]["window"]),
            "evidence_window": dict(inputs["evidence_window"]),
            "runs_distinct": True,
        },
        "metrics": results,
        "claims": {
            "allowed": [_ALLOWED_CLAIM],
            "forbidden": [
                "causality-without-controlled-evidence",
                "recommendation-self-validation",
            ],
        },
        "statement": (
            "The supplied post-recommendation evidence window was evaluated for "
            "statistical differences between returned aggregate proportions."
        ),
        "limitations": [
            "Statistical significance describes the supplied observation window only.",
            "The method does not establish causality, incrementality, or future impact.",
            "Independent assignment and absence of interference remain caller assertions.",
        ],
        "network_called": False,
    }


def _validate_claim(value: Any) -> None:
    if value != _ALLOWED_CLAIM:
        _fail(
            "OPERATOR_CAUSALITY_FORBIDDEN",
            "Significance-test v1 permits observational outcome claims only.",
            "claim",
            "Use claim=experiment-outcome-observation and keep causal interpretation out of the result.",
        )


def _validate_provenance(inputs: Mapping[str, Any]) -> None:
    recommendation = inputs["recommendation"]
    observation = inputs["observation"]
    run_ids = {
        str(recommendation["producer_run_id"]),
        str(observation["producer_run_id"]),
        str(inputs["evaluation_run_id"]),
    }
    if (
        len(run_ids) != 3
        or observation["digest"] == recommendation["digest"]
        or observation["assignment_digest"]
        in {observation["digest"], recommendation["digest"]}
    ):
        _fail(
            "OPERATOR_SELF_VALIDATION_FORBIDDEN",
            "Recommendation, external observation, and evaluation runs must be distinct.",
            "evaluation_run_id",
            "Provide three distinct immutable run identifiers from separate stages.",
        )
    if observation["source"] != "external":
        _fail(
            "OPERATOR_SELF_VALIDATION_FORBIDDEN",
            "The observation digest must be supplied by an external run.",
            "observation.source",
            "Supply an external completed observation digest; do not evaluate a same-run artifact.",
        )
    recommendation_window = _window(recommendation["window"], "recommendation.window")
    observation_window = _window(observation["window"], "observation.window")
    evidence_window = _window(inputs["evidence_window"], "evidence_window")
    if observation_window != evidence_window:
        _fail(
            "OPERATOR_EVIDENCE_WINDOW_INVALID",
            "The evidence window must exactly match the external observation window.",
            "evidence_window",
            "Pass the completed observation window unchanged as the evidence window.",
        )
    if recommendation_window["timezone"] != evidence_window["timezone"]:
        _fail(
            "OPERATOR_EVIDENCE_WINDOW_INVALID",
            "Recommendation and evidence windows must use the same timezone.",
            "evidence_window.timezone",
            "Align the evidence window to the recommendation-window timezone.",
        )
    if date.fromisoformat(evidence_window["start"]) <= date.fromisoformat(
        recommendation_window["end"]
    ):
        _fail(
            "OPERATOR_EVIDENCE_WINDOW_OVERLAP",
            "The evidence window must begin strictly after the recommendation window.",
            "evidence_window.start",
            "Choose a post-recommendation evidence window with no overlapping date.",
        )


def _validate_metric_family(metrics: Sequence[Mapping[str, Any]]) -> None:
    uris = [str(item["metric_uri"]) for item in metrics]
    if len(uris) != len(set(uris)):
        _fail(
            "OPERATOR_INPUT_INVALID",
            "Metric URIs must be unique within one comparison family.",
            "metrics[].metric_uri",
            "Remove duplicate metric comparisons and retry.",
        )
    primary_count = sum(item["role"] == "primary" for item in metrics)
    if primary_count != 1:
        _fail(
            "OPERATOR_INPUT_INVALID",
            "Exactly one metric must have role=primary.",
            "metrics[].role",
            "Mark exactly one metric as primary; mark the remainder as guardrail.",
        )


def _metric_result(
    metric: Mapping[str, Any],
    index: int,
    *,
    alpha: float,
    adjusted_alpha: float,
) -> dict[str, Any]:
    control = _arm(metric["control"], f"metrics[{index}].control")
    treatment = _arm(metric["treatment"], f"metrics[{index}].treatment")
    pooled = (control["successes"] + treatment["successes"]) / (
        control["trials"] + treatment["trials"]
    )
    if pooled <= 0.0 or pooled >= 1.0:
        _fail(
            "OPERATOR_VARIANCE_DEGENERATE",
            "The pooled binary-outcome variance is zero.",
            f"metrics[{index}]",
            "Provide a window with both observed outcomes or use another registered exact method.",
        )
    observed_cells = (
        control["successes"],
        control["trials"] - control["successes"],
        treatment["successes"],
        treatment["trials"] - treatment["successes"],
    )
    if min(observed_cells) < _MINIMUM_CELL_COUNT:
        _fail(
            "OPERATOR_SAMPLE_INSUFFICIENT",
            "Every observed success/failure cell must contain at least five samples.",
            f"metrics[{index}]",
            "Extend the evidence window or use a separately registered small-sample method.",
        )
    control_rate = control["successes"] / control["trials"]
    treatment_rate = treatment["successes"] / treatment["trials"]
    difference = treatment_rate - control_rate
    null_se = math.sqrt(
        pooled * (1.0 - pooled) * (1.0 / control["trials"] + 1.0 / treatment["trials"])
    )
    interval_se = math.sqrt(
        control_rate * (1.0 - control_rate) / control["trials"]
        + treatment_rate * (1.0 - treatment_rate) / treatment["trials"]
    )
    z_statistic = difference / null_se
    p_value = _p_value(z_statistic, str(metric["alternative"]))
    adjusted_p_value = min(1.0, p_value * (alpha / adjusted_alpha))
    critical = NormalDist().inv_cdf(1.0 - adjusted_alpha / 2.0)
    lower = max(-1.0, difference - critical * interval_se)
    upper = min(1.0, difference + critical * interval_se)
    return {
        "metric_uri": metric["metric_uri"],
        "role": metric["role"],
        "alternative": metric["alternative"],
        "control": {**control, "rate": _render(control_rate)},
        "treatment": {**treatment, "rate": _render(treatment_rate)},
        "observed_risk_difference": _render(difference),
        "observed_relative_lift": (
            None if control_rate == 0.0 else _render(difference / control_rate)
        ),
        "standard_error_null": _render(null_se),
        "z_statistic": _render(z_statistic),
        "p_value": _render(p_value),
        "adjusted_p_value": _render(adjusted_p_value),
        "significant": adjusted_p_value <= alpha,
        "observed_direction": (
            "increase" if difference > 0 else "decrease" if difference < 0 else "no_change"
        ),
        "confidence_interval": {
            "level": _render(1.0 - adjusted_alpha),
            "lower": _render(lower),
            "upper": _render(upper),
            "method": "two-sided-unpooled-wald-risk-difference",
        },
        "fact_references": [
            {"path": f"/metrics/{index}/control"},
            {"path": f"/metrics/{index}/treatment"},
        ],
    }


def _arm(value: Mapping[str, Any], field: str) -> dict[str, int]:
    successes = int(value["successes"])
    trials = int(value["trials"])
    if trials <= 0 or successes < 0 or successes > trials:
        _fail(
            "OPERATOR_INPUT_INVALID",
            "Arm counts require 0 <= successes <= positive trials.",
            field,
            "Correct the aggregate success and trial counts for this arm.",
        )
    return {"successes": successes, "trials": trials}


def _p_value(z_statistic: float, alternative: str) -> float:
    if alternative == "greater":
        return 0.5 * math.erfc(z_statistic / math.sqrt(2.0))
    if alternative == "less":
        return 0.5 * math.erfc(-z_statistic / math.sqrt(2.0))
    return math.erfc(abs(z_statistic) / math.sqrt(2.0))


def _window(value: Mapping[str, Any], field: str) -> dict[str, str]:
    selected = {name: str(value[name]) for name in ("start", "end", "timezone")}
    try:
        start = date.fromisoformat(selected["start"])
        end = date.fromisoformat(selected["end"])
        ZoneInfo(selected["timezone"])
    except (KeyError, TypeError, ValueError, ZoneInfoNotFoundError):
        _fail(
            "OPERATOR_EVIDENCE_WINDOW_INVALID",
            "Evidence dates and timezone must be valid.",
            field,
            "Use ordered YYYY-MM-DD dates and an IANA timezone.",
        )
    if start > end:
        _fail(
            "OPERATOR_EVIDENCE_WINDOW_INVALID",
            "Window start must not follow its end.",
            field,
            "Correct the ordered recommendation and evidence dates.",
        )
    return selected


def _probability(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail(
            "OPERATOR_NUMERIC_INVALID",
            "Alpha must be a finite probability strictly between zero and one.",
            field,
            "Provide an explicit numeric alpha such as 0.05.",
        )
    selected = float(value)
    if not math.isfinite(selected) or not 0.000001 <= selected <= 0.5:
        _fail(
            "OPERATOR_NUMERIC_INVALID",
            "Alpha must be within the supported numeric domain 0.000001..0.5.",
            field,
            "Provide an explicit alpha between 0.000001 and 0.5, such as 0.05.",
        )
    return selected


def _render(value: float) -> str:
    if value == 0.0:
        return "0"
    return format(value, ".12g")


def _fail(reason: str, message: str, field: str, next_action: str) -> None:
    raise OperatorMethodError(
        reason,
        message,
        field=field,
        next_action=next_action,
    )


__all__ = ["significance_test"]
