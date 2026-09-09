"""Runtime-owned Operator input invariants; no registry or execution ownership."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from ..operator_returned_dimension_change import OperatorMethodError


_SCOPE_FIELDS = {
    "campaign-outcome-evaluation": ("current", "reference"),
    "metric-decomposition": ("current", "reference"),
    "scenario-projection": ("baseline", "projected"),
    "funnel-diagnosis": ("entered", "reached"),
    "sentiment-aggregation": ("count",),
}


def _validate_mode(method: str, mode: str) -> None:
    allowed = {"rowwise", "cumulative" if method == "funnel-diagnosis" else "aggregate"}
    if mode not in allowed:
        _reject("OPERATOR_INPUT_INVALID", "mode", "Mode does not match the method.",
                "Select a mode declared for this method in the described contract.")


def _validate_scopes(inputs: Mapping[str, Any], mode: str) -> None:
    roles = _SCOPE_FIELDS[inputs["method"]]
    for index, row in enumerate(inputs["rows"]):
        scopes = row["scopes"]
        field = f"rows[{index}].scopes"
        if set(scopes) != set(roles):
            _reject("OPERATOR_SCOPE_MISMATCH", field, "Value scopes must match the method.",
                    "Supply exactly these value scopes: " + ", ".join(roles) + ".")
        for scope in scopes.values():
            _validate_window(scope["window"], field + ".window")
        if any(scope["unit"] != inputs["unit"] for scope in scopes.values()):
            _reject("OPERATOR_UNIT_MISMATCH", field, "Value units disagree.",
                    "Bind every compared/projected value to the declared unit; do not mix units.")
        if len({scope["population"] for scope in scopes.values()}) != 1:
            _reject("OPERATOR_SCOPE_MISMATCH", field, "Compared populations disagree.",
                    "Bind comparable values to the same population.")
        if inputs["method"] == "funnel-diagnosis":
            _same_scope(scopes["entered"], scopes["reached"], field)
    if mode != "rowwise":
        _validate_complete_scope(inputs, roles)
    _validate_topology_fields(inputs, mode)


def _validate_window(window: Mapping[str, Any], field: str) -> None:
    try:
        valid = date.fromisoformat(window["start"]) <= date.fromisoformat(window["end"])
    except ValueError:
        valid = False
    if not valid:
        _reject("OPERATOR_SCOPE_MISMATCH", field, "Scope window dates are invalid or reversed.",
                "Supply an inclusive ISO date window with start <= end.")


def _validate_complete_scope(inputs: Mapping[str, Any], roles: Sequence[str]) -> None:
    if _completeness(inputs) != "complete":
        _reject("OPERATOR_COMPLETENESS_UNSUPPORTED", "rows.scopes.completeness",
                "Partial/unknown scopes cannot support totals or cumulative conversion.",
                "Supply complete scopes or explicitly request mode=rowwise.")
    first = inputs["rows"][0]["scopes"]
    for index, row in enumerate(inputs["rows"]):
        for role in roles:
            _same_scope(first[role], row["scopes"][role], f"rows[{index}].scopes.{role}")


def _same_scope(left: Mapping[str, Any], right: Mapping[str, Any], field: str) -> None:
    if any(left[key] != right[key] for key in ("unit", "population", "window")):
        _reject("OPERATOR_SCOPE_MISMATCH", field, "Cross-row scope or window disagrees.",
                "Use one population/window/unit per aggregated side, or request mode=rowwise.")


def _completeness(inputs: Mapping[str, Any]) -> str:
    values = {scope["completeness"] for row in inputs["rows"] for scope in row["scopes"].values()}
    return "unknown" if "unknown" in values else "prefix" if "prefix" in values else "complete"


def _validate_topology_fields(inputs: Mapping[str, Any], mode: str) -> None:
    funnel = inputs["method"] == "funnel-diagnosis"
    if funnel and inputs.get("topology") not in {"linear", "independent"}:
        _reject("OPERATOR_FUNNEL_LINEAGE_UNPROVEN", "topology", "Funnel topology is required.",
                "Declare topology=linear for cumulative or topology=independent for step comparisons.")
    if not funnel and ("topology" in inputs or any("lineage" in row for row in inputs["rows"])):
        _fail("OPERATOR_INPUT_INVALID", "non-funnel methods cannot declare funnel lineage")
    if mode != "aggregate" and "aggregation" in inputs:
        _fail("OPERATOR_INPUT_INVALID", "aggregation evidence is only valid in aggregate mode")


def _validate_aggregation(inputs: Mapping[str, Any]) -> None:
    aggregation = inputs.get("aggregation")
    if aggregation is None:
        _reject("OPERATOR_AGGREGATION_UNPROVEN", "aggregation", "Aggregation evidence is absent.",
                "Supply an axis, allowed axes and an evidenced disjoint partition, or use mode=rowwise.")
    if inputs["additivity"] == "non_additive" or aggregation["axis"] not in aggregation["allowed_axes"]:
        _reject("OPERATOR_ADDITIVITY_UNSUPPORTED", "aggregation.axis", "Metric is not additive on this axis.",
                "Use an additive metric on a declared allowed axis, or request mode=rowwise.")
    if set(aggregation["disjointness"]["members"]) != {row["key"] for row in inputs["rows"]}:
        _reject("OPERATOR_AGGREGATION_UNPROVEN", "aggregation.disjointness.members",
                "Disjoint partition must cover exactly the supplied components.",
                "Bind the partition evidence to every row key, without omitted or extra components.")


def _validate_lineage(inputs: Mapping[str, Any]) -> None:
    if inputs.get("topology") != "linear":
        _reject("OPERATOR_FUNNEL_LINEAGE_UNPROVEN", "topology", "Cumulative requires linear topology.",
                "Use mode=rowwise for independent/branch observations.")
    ordered = sorted(inputs["rows"], key=lambda row: _integer(row, "order"))
    previous = None
    for row in ordered:
        lineage = row.get("lineage")
        valid = lineage is not None and _lineage_matches(lineage, row, previous)
        if not valid:
            _reject("OPERATOR_FUNNEL_LINEAGE_UNPROVEN", "rows.lineage",
                    "Step boundary lacks a consistent root/equality/subset relation.",
                    "Supply evidenced ordered predecessor relations; subsets may enter fewer than previous reached.")
        previous = row


def _lineage_matches(
    lineage: Mapping[str, Any], row: Mapping[str, Any], previous: Mapping[str, Any] | None
) -> bool:
    if previous is None:
        return lineage["relation"] == "root" and lineage["predecessor"] is None
    if lineage["predecessor"] != previous["key"]:
        return False
    entered, reached = _nonnegative(row, "entered"), _nonnegative(previous, "reached")
    if lineage["relation"] == "equal":
        return entered == reached
    return lineage["relation"] == "subset" and entered <= reached


def _reject(reason: str, field: str, message: str, next_action: str) -> None:
    raise OperatorMethodError(reason, message, field=field, next_action=next_action)


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


def _fail(reason_code: str, message: str) -> None:
    raise OperatorMethodError(reason_code, message)
