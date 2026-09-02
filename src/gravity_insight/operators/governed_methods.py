"""Bounded deterministic methods shared by Runtime-owned Operator contracts."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

from ..operator_ids import GOVERNED_METHOD_RESULT_SCHEMA
from ..operator_returned_dimension_change import OperatorMethodError


_METHODS: dict[
    str, Callable[[Sequence[Mapping[str, Any]], Mapping[str, Any]], dict[str, Any]]
] = {}
_METHOD_FIELDS = {
    "campaign-outcome-evaluation": {"current", "reference"},
    "churn-segment-profile": {"cohort_share", "comparison_share"},
    "funnel-diagnosis": {"order", "entered", "reached"},
    "ltv-payback-period": {"day", "cumulative_value"},
    "metric-decomposition": {"current", "reference"},
    "price-elasticity": {"price", "quantity"},
    "retention-curve": {"day", "retention"},
    "scenario-projection": {"baseline", "coefficient", "change"},
    "sentiment-aggregation": {"count"},
}
_METHOD_PARAMETERS = {
    "campaign-outcome-evaluation": set(),
    "churn-segment-profile": set(),
    "funnel-diagnosis": set(),
    "ltv-payback-period": {"acquisition_cost"},
    "metric-decomposition": set(),
    "price-elasticity": set(),
    "retention-curve": set(),
    "scenario-projection": {"horizon_days"},
    "sentiment-aggregation": set(),
}


def execute_governed_method(inputs: Mapping[str, Any]) -> dict[str, Any]:
    """Execute one exact method selected by its already validated input value."""

    method = str(inputs["method"])
    runner = _METHODS.get(method)
    if runner is None:
        _fail("OPERATOR_INPUT_INVALID", "governed method is not registered")
    if set(inputs["parameters"]) != _METHOD_PARAMETERS[method]:
        _fail("OPERATOR_INPUT_INVALID", "governed method parameters are not exact")
    if any(set(row["values"]) != _METHOD_FIELDS[method] for row in inputs["rows"]):
        _fail("OPERATOR_INPUT_INVALID", "governed method row values are not exact")
    return runner(inputs["rows"], inputs["parameters"])


def _campaign(
    rows: Sequence[Mapping[str, Any]], _parameters: Mapping[str, Any]
) -> dict[str, Any]:
    changes = _changes(rows, "current", "reference")
    current = sum((_value(row, "current") for row in rows), Decimal(0))
    reference = sum((_value(row, "reference") for row in rows), Decimal(0))
    delta = current - reference
    return _result(
        "campaign-outcome-evaluation",
        _direction(delta, "returned_outcome"),
        {
            "current_total": _render(current),
            "reference_total": _render(reference),
            "absolute_change": _render(delta),
        },
        _rank(changes),
        [
            "Only caller-gated returned outcomes are evaluated.",
            "Observed contribution is not incremental or causal effect.",
        ],
    )


def _churn_profile(
    rows: Sequence[Mapping[str, Any]], _parameters: Mapping[str, Any]
) -> dict[str, Any]:
    ranked: list[dict[str, Any]] = []
    for row in rows:
        churn = _bounded_ratio(row, "cohort_share")
        comparison = _bounded_ratio(row, "comparison_share")
        lift = None if comparison == 0 else churn / comparison
        ranked.append(
            _row_result(
                row,
                value=lift,
                contribution=churn - comparison,
            )
        )
    strongest = max(
        ranked,
        key=lambda item: abs(_decimal(item["contribution"])),
    )
    return _result(
        "churn-segment-profile",
        "returned_feature_difference_observed"
        if any(item["contribution"] != "0" for item in ranked)
        else "no_returned_feature_difference",
        {
            "strongest_feature": strongest["key"],
            "strongest_share_difference": strongest["contribution"],
        },
        _rank(ranked),
        [
            "Profile rows must use the same mature cohort and comparison scope.",
            "Feature lift is an aggregate association, never an individual cause.",
        ],
    )


def _funnel(
    rows: Sequence[Mapping[str, Any]], _parameters: Mapping[str, Any]
) -> dict[str, Any]:
    ordered = sorted(rows, key=lambda row: _integer(row, "order"))
    orders = [_integer(row, "order") for row in ordered]
    if len(orders) != len(set(orders)):
        _fail("OPERATOR_INPUT_INVALID", "funnel order values are duplicated")
    ranked: list[dict[str, Any]] = []
    for row in ordered:
        entered = _nonnegative(row, "entered")
        reached = _nonnegative(row, "reached")
        if reached > entered:
            _fail("OPERATOR_INPUT_INVALID", "funnel reached exceeds entered")
        rate = None if entered == 0 else reached / entered
        ranked.append(
            _row_result(row, value=rate, contribution=entered - reached)
        )
    first = _nonnegative(ordered[0], "entered")
    final = _nonnegative(ordered[-1], "reached")
    cumulative = None if first == 0 else final / first
    largest = max(ranked, key=lambda item: _decimal(item["contribution"]))
    return _result(
        "funnel-diagnosis",
        "returned_step_loss_observed"
        if largest["contribution"] != "0"
        else "no_returned_step_loss",
        {
            "first_step_entered": _render(first),
            "final_step_reached": _render(final),
            "cumulative_conversion": _optional(cumulative),
            "largest_loss_step": largest["key"],
        },
        _rank(ranked),
        [
            "Rows must already follow the project funnel definition and eligibility rules.",
            "A returned step loss does not identify product causality.",
        ],
    )


def _ltv_payback(
    rows: Sequence[Mapping[str, Any]], parameters: Mapping[str, Any]
) -> dict[str, Any]:
    cost = _positive_parameter(parameters, "acquisition_cost")
    ordered = sorted(rows, key=lambda row: _integer(row, "day"))
    days = [_integer(row, "day") for row in ordered]
    if len(days) != len(set(days)):
        _fail("OPERATOR_INPUT_INVALID", "payback day values are duplicated")
    cumulative_values = [
        _nonnegative(row, "cumulative_value") for row in ordered
    ]
    if any(
        right < left
        for left, right in zip(cumulative_values, cumulative_values[1:])
    ):
        _fail(
            "OPERATOR_INPUT_INVALID",
            "payback cumulative values must not decrease",
        )
    payback = next(
        (
            day
            for day, cumulative_value in zip(days, cumulative_values)
            if cumulative_value >= cost
        ),
        None,
    )
    ranked = [
        _row_result(
            row,
            value=cumulative_value,
            contribution=cumulative_value - cost,
        )
        for row, cumulative_value in zip(ordered, cumulative_values)
    ]
    return _result(
        "ltv-payback-period",
        "observed_payback_reached" if payback is not None else "payback_not_observed",
        {
            "acquisition_cost": _render(cost),
            "observed_payback_day": None if payback is None else str(payback),
            "latest_cumulative_value": ranked[-1]["value"],
        },
        _rank(ranked),
        [
            "Payback is reported only from supplied mature cumulative-value rows.",
            "No missing day or future value is inferred.",
        ],
    )


def _decomposition(
    rows: Sequence[Mapping[str, Any]], _parameters: Mapping[str, Any]
) -> dict[str, Any]:
    changes = _changes(rows, "current", "reference")
    total = sum((_decimal(item["contribution"]) for item in changes), Decimal(0))
    ranked = []
    for item in changes:
        delta = _decimal(item["contribution"])
        ranked.append(
            {
                **item,
                "value": _render(delta),
                "contribution": _optional(None if total == 0 else delta / total),
            }
        )
    return _result(
        "metric-decomposition",
        _direction(total, "returned_metric"),
        {"returned_total_change": _render(total)},
        _rank(ranked),
        [
            "Components must be mutually interpretable under one metric contract.",
            "Contribution shares describe returned arithmetic, not causality.",
        ],
    )


def _price_elasticity(
    rows: Sequence[Mapping[str, Any]], _parameters: Mapping[str, Any]
) -> dict[str, Any]:
    if len(rows) != 2:
        _fail("OPERATOR_SAMPLE_INSUFFICIENT", "price elasticity requires two states")
    first, second = rows
    p1, p2 = _positive(first, "price"), _positive(second, "price")
    q1, q2 = _nonnegative(first, "quantity"), _nonnegative(second, "quantity")
    p_mid = (p1 + p2) / Decimal(2)
    q_mid = (q1 + q2) / Decimal(2)
    if p1 == p2 or q_mid == 0:
        _fail("OPERATOR_INPUT_INVALID", "price or midpoint quantity has no variation")
    elasticity = ((q2 - q1) / q_mid) / ((p2 - p1) / p_mid)
    ranked = [
        _row_result(row, value=_positive(row, "price"), contribution=_nonnegative(row, "quantity"))
        for row in rows
    ]
    return _result(
        "price-elasticity",
        "returned_inverse_response"
        if elasticity < 0
        else "returned_non_inverse_response",
        {"arc_elasticity": _render(elasticity)},
        _rank(ranked),
        [
            "The two price states must be caller-gated as comparable exposures.",
            "Observed arc elasticity does not prove causal price response or an optimum.",
        ],
    )


def _retention_curve(
    rows: Sequence[Mapping[str, Any]], _parameters: Mapping[str, Any]
) -> dict[str, Any]:
    ordered = sorted(rows, key=lambda row: _integer(row, "day"))
    days = [_integer(row, "day") for row in ordered]
    if len(days) != len(set(days)) or any(right <= left for left, right in zip(days, days[1:])):
        _fail("OPERATOR_INPUT_INVALID", "retention days must be unique and increasing")
    values = [_bounded_ratio(row, "retention") for row in ordered]
    if any(right > left for left, right in zip(values, values[1:])):
        _fail("OPERATOR_INPUT_INVALID", "survival retention must not increase")
    area = Decimal(0)
    for index in range(1, len(ordered)):
        width = Decimal(days[index] - days[index - 1])
        area += (values[index - 1] + values[index]) / Decimal(2) * width
    ranked = [
        _row_result(row, value=_bounded_ratio(row, "retention"), contribution=None)
        for row in ordered
    ]
    return _result(
        "retention-curve",
        "returned_survival_curve_valid",
        {
            "observed_area": _render(area),
            "first_day": str(days[0]),
            "last_day": str(days[-1]),
        },
        _rank(ranked),
        [
            "The area covers only supplied mature retention nodes.",
            "No tail lifetime is extrapolated without a separately approved Model Artifact.",
        ],
    )


def _sentiment(
    rows: Sequence[Mapping[str, Any]], _parameters: Mapping[str, Any]
) -> dict[str, Any]:
    counts = [Decimal(_integer(row, "count")) for row in rows]
    total = sum(counts, Decimal(0))
    if total == 0:
        _fail("OPERATOR_SAMPLE_INSUFFICIENT", "sentiment counts sum to zero")
    ranked = [
        _row_result(row, value=count, contribution=count / total)
        for row, count in zip(rows, counts)
    ]
    return _result(
        "sentiment-aggregation",
        "returned_categories_aggregated",
        {"returned_total": _render(total)},
        _rank(ranked),
        [
            "Rows must already be classified under one project-approved taxonomy.",
            "Aggregation neither classifies text nor infers author intent.",
        ],
    )


def _scenario(
    rows: Sequence[Mapping[str, Any]], parameters: Mapping[str, Any]
) -> dict[str, Any]:
    horizon = _positive_integer_parameter(parameters, "horizon_days")
    ranked: list[dict[str, Any]] = []
    baseline_total = Decimal(0)
    scenario_total = Decimal(0)
    for row in rows:
        baseline = _value(row, "baseline")
        impact = _value(row, "coefficient") * _value(row, "change")
        baseline_total += baseline
        scenario_total += baseline + impact
        ranked.append(_row_result(row, value=baseline + impact, contribution=impact))
    return _result(
        "scenario-projection",
        _direction(scenario_total - baseline_total, "scenario"),
        {
            "horizon_days": _render(horizon),
            "baseline_total": _render(baseline_total),
            "scenario_total": _render(scenario_total),
            "scenario_change": _render(scenario_total - baseline_total),
        },
        _rank(ranked),
        [
            "Projection uses only caller-supplied coefficients and bounded parameter changes.",
            "The scenario is not a forecast guarantee or causal effect estimate.",
        ],
    )


def _changes(
    rows: Sequence[Mapping[str, Any]], current_key: str, reference_key: str
) -> list[dict[str, Any]]:
    return [
        _row_result(
            row,
            value=_value(row, current_key),
            contribution=_value(row, current_key) - _value(row, reference_key),
        )
        for row in rows
    ]


def _row_result(
    row: Mapping[str, Any], *, value: Decimal | None, contribution: Decimal | None
) -> dict[str, Any]:
    return {
        "key": str(row["key"]),
        "value": _optional(value),
        "contribution": _optional(contribution),
        "rank": 0,
        "evidence": {
            "step_id": str(row["evidence"]["step_id"]),
            "path": str(row["evidence"]["path"]),
        },
    }


def _rank(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted(
        rows,
        key=lambda item: (
            -abs(_decimal(item["contribution"]))
            if item.get("contribution") is not None
            else Decimal(0),
            str(item["key"]),
        ),
    )
    return [{**dict(item), "rank": index} for index, item in enumerate(ordered, 1)]


def _result(
    method: str,
    verdict: str,
    metrics: Mapping[str, str | None],
    ranked_rows: Sequence[Mapping[str, Any]],
    limitations: Sequence[str],
) -> dict[str, Any]:
    return {
        "schema_version": GOVERNED_METHOD_RESULT_SCHEMA,
        "method": method,
        "verdict": verdict,
        "metrics": dict(metrics),
        "ranked_rows": [dict(item) for item in ranked_rows],
        "limitations": list(limitations),
    }


def _value(row: Mapping[str, Any], name: str) -> Decimal:
    try:
        value = row["values"][name]
    except (KeyError, TypeError):
        _fail("OPERATOR_INPUT_INVALID", f"row value {name} is missing")
    return _decimal(value)


def _integer(row: Mapping[str, Any], name: str) -> int:
    value = _value(row, name)
    if value != value.to_integral_value() or value < 0:
        _fail("OPERATOR_INPUT_INVALID", f"row value {name} must be a nonnegative integer")
    return int(value)


def _nonnegative(row: Mapping[str, Any], name: str) -> Decimal:
    value = _value(row, name)
    if value < 0:
        _fail("OPERATOR_INPUT_INVALID", f"row value {name} must be nonnegative")
    return value


def _positive(row: Mapping[str, Any], name: str) -> Decimal:
    value = _value(row, name)
    if value <= 0:
        _fail("OPERATOR_INPUT_INVALID", f"row value {name} must be positive")
    return value


def _bounded_ratio(row: Mapping[str, Any], name: str) -> Decimal:
    value = _value(row, name)
    if value < 0 or value > 1:
        _fail("OPERATOR_INPUT_INVALID", f"row value {name} must be within zero and one")
    return value


def _positive_parameter(parameters: Mapping[str, Any], name: str) -> Decimal:
    try:
        value = _decimal(parameters[name])
    except KeyError:
        _fail("OPERATOR_INPUT_INVALID", f"parameter {name} is missing")
    if value <= 0:
        _fail("OPERATOR_INPUT_INVALID", f"parameter {name} must be positive")
    return value


def _positive_integer_parameter(
    parameters: Mapping[str, Any], name: str
) -> Decimal:
    value = _positive_parameter(parameters, name)
    if value != value.to_integral_value():
        _fail("OPERATOR_INPUT_INVALID", f"parameter {name} must be an integer")
    return value


def _decimal(value: Any) -> Decimal:
    if isinstance(value, bool) or value is None:
        _fail("OPERATOR_NUMERIC_INVALID", "numeric value is missing or invalid")
    try:
        selected = Decimal(str(value))
    except (InvalidOperation, ValueError):
        _fail("OPERATOR_NUMERIC_INVALID", "numeric value is missing or invalid")
    if not selected.is_finite():
        _fail("OPERATOR_NUMERIC_INVALID", "numeric value is not finite")
    return selected


def _direction(value: Decimal, prefix: str) -> str:
    if value > 0:
        return f"{prefix}_increase_observed"
    if value < 0:
        return f"{prefix}_decrease_observed"
    return f"no_{prefix}_change_observed"


def _optional(value: Decimal | None) -> str | None:
    return None if value is None else _render(value)


def _render(value: Decimal) -> str:
    selected = value.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
    rendered = format(selected, "f").rstrip("0").rstrip(".")
    return rendered or "0"


def _fail(reason_code: str, message: str) -> None:
    raise OperatorMethodError(reason_code, message)


_METHODS.update(
    {
        "campaign-outcome-evaluation": _campaign,
        "churn-segment-profile": _churn_profile,
        "funnel-diagnosis": _funnel,
        "ltv-payback-period": _ltv_payback,
        "metric-decomposition": _decomposition,
        "price-elasticity": _price_elasticity,
        "retention-curve": _retention_curve,
        "scenario-projection": _scenario,
        "sentiment-aggregation": _sentiment,
    }
)


__all__ = ["execute_governed_method"]
