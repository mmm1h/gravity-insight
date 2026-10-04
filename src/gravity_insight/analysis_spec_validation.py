"""Actionable validation and evidence-scoped encoding for Analysis inputs."""

from __future__ import annotations

import copy
import re
from collections.abc import Iterator, Mapping, Sequence
from typing import Any

from .actionable_error_values import actual_value, allowed_values
from .errors import InputValidationError


EVENT_OPERATOR_REPLACEMENTS = {
    "GT": "GREATER", "GTE": "GREATER_EQUALS", "LT": "LESS", "LTE": "LESS_EQUALS",
}
VALUELESS_CONDITION_OPERATORS = frozenset({"WITH_VAL", "WITHOUT_VAL"})


def compile_condition_values(inputs: dict[str, Any]) -> dict[str, Any]:
    """Supply the wire-required empty array without mutating the caller's spec."""
    result = copy.deepcopy(inputs)
    for _, conditions in _condition_groups(result):
        for condition in conditions:
            if (
                isinstance(condition, dict)
                and isinstance(condition.get("operator"), str)
                and condition.get("operator") in VALUELESS_CONDITION_OPERATORS
                and "value" not in condition
            ):
                condition["value"] = []
    return result


def require_condition_value(condition: Mapping[str, Any], field: str) -> None:
    if "value" not in condition:
        raise InputValidationError(
            "actual value: missing condition value; request was not sent",
            field=f"{field}.value",
            next_action=(
                "Set value=[] for WITH_VAL/WITHOUT_VAL, or use a compact spec which supplies it."
                if condition.get("operator") in VALUELESS_CONDITION_OPERATORS else
                "Set value to the explicit scalar array required by this operator; do not retry unchanged."
            ),
        )


def validate_event_operators(inputs: Mapping[str, Any]) -> None:
    """Event pairs reject all four short forms; other kinds remain unproven."""
    for path, conditions in _condition_groups(inputs):
        for index, condition in enumerate(conditions):
            if not isinstance(condition, Mapping):
                continue
            operator = condition.get("operator")
            replacement = EVENT_OPERATOR_REPLACEMENTS.get(operator) if isinstance(operator, str) else None
            if replacement:
                raise InputValidationError(
                    f"actual value: operator={operator}; Event Analysis rejects this operator; request was not sent",
                    field=f"{path}[{index}].operator",
                    next_action=f"Replace {operator} with {replacement}; keep the field and values unchanged. Do not retry unchanged.",
                )


def _condition_groups(inputs: Mapping[str, Any], path: str = "") -> Iterator[tuple[str, Sequence[Any]]]:
    # Traverse only contract-owned condition containers, never caller values/maps.
    for key in ("conditions", "global_conditions", "property_condition"):
        value = inputs.get(key)
        if isinstance(value, (list, tuple)):
            yield f"{path}{key}", value
    for key in ("query_item_list", "custom_query_item_list", "list"):
        value = inputs.get(key)
        if isinstance(value, (list, tuple)):
            for index, item in enumerate(value):
                if isinstance(item, Mapping):
                    yield from _condition_groups(item, f"{path}{key}[{index}].")
    for key in ("query_item", "query_item_before_after", "before", "after", "before_custom", "after_custom"):
        value = inputs.get(key)
        if isinstance(value, Mapping):
            yield from _condition_groups(value, f"{path}{key}.")


def compile_event_quantile(target: dict[str, Any], field: str) -> None:
    """Mirror Event's public bundle: Quantile_N -> Quantile + quantile_level=N."""
    name = target["name"]
    match = re.fullmatch(r"Quantile_([1-9]|[1-9][0-9]|100)", name)
    level = target.get("quantile_level")
    if match:
        expected = int(match[1])
        if level is not None and level != expected:
            raise InputValidationError(
                "actual value: conflicting quantile declarations; request was not sent",
                field=f"{field}.quantile",
                next_action="Remove quantile when using Quantile_N, or set it to the same percentile N.",
            )
        target.update(name="Quantile", quantile_level=expected)
    elif name == "Quantile" and level is None:
        raise InputValidationError(
            "actual value: Quantile without a percentile; request was not sent",
            field=f"{field}.quantile",
            next_action="Set quantile to a number greater than 0 through 100, or use Quantile_N (N=1..100).",
        )


def event_input_definitions(definitions: Mapping[str, Any]) -> dict[str, Any]:
    """Refine only Event's shared spec definitions to its proven input contract."""
    condition = copy.deepcopy(definitions["condition"])
    operators = condition["properties"]["operator"]["enum"]
    condition["properties"]["operator"]["enum"] = sorted(set(operators) - EVENT_OPERATOR_REPLACEMENTS.keys())
    metric = copy.deepcopy(definitions["metric"])
    metric["allOf"] = [{
        "if": {"properties": {"aggregation": {"const": "Quantile"}}, "required": ["aggregation"]},
        "then": {"required": ["quantile"]},
    }]
    metric["description"] = (
        "Event Quantile_N compiles to name=Quantile and quantile_level=N. "
        "Bare Quantile requires quantile; a redundant quantile must equal N."
    )
    step = copy.deepcopy(definitions["event_step"])
    step["properties"]["conditions"]["items"] = {"$ref": "#/definitions/event_condition"}
    step["properties"]["metric"] = {"$ref": "#/definitions/event_metric"}
    return {"event_condition": condition, "event_metric": metric, "event_query_step": step}


def reject_keys(
    value: Mapping[str, Any], allowed: set[str] | frozenset[str], field: str
) -> None:
    unknown = sorted(set(value) - set(allowed))
    if unknown:
        raise InputValidationError(
            f"actual value: {actual_value(unknown)}; allowed fields: "
            f"{allowed_values(allowed)}",
            field=field,
        )


def mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        next_action = (
            "Add a metric object with `field` and `aggregation`; inspect the "
            "contract with `gravity analysis query --kind <kind> --spec-schema`."
            if field.endswith(".metric")
            else "Correct the Analysis spec and retry the same command."
        )
        raise InputValidationError(
            f"actual value: {actual_value(value)}; allowed type: object",
            field=field,
            next_action=next_action,
        )
    return value


def list_items(value: Any, field: str, maximum: int) -> list[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise InputValidationError(
            f"actual value: {actual_value(value)}; allowed type: array", field=field
        )
    items = list(value)
    if len(items) > maximum:
        raise InputValidationError(
            f"actual value: {len(items)} items; allowed maximum: {maximum} items",
            field=field,
        )
    return items


def bounded_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise InputValidationError(
            f"actual value: {actual_value(value)}; allowed value: a non-empty string "
            "of at most 256 characters",
            field=field,
        )
    return value.strip()


def optional_string(value: Any, field: str, default: str) -> str:
    if value is None:
        return default
    if not isinstance(value, str) or len(value) > 256:
        raise InputValidationError(
            f"actual value: {actual_value(value)}; allowed value: a string of at most "
            "256 characters",
            field=field,
        )
    return value


def boolean(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise InputValidationError(
            f"actual value: {actual_value(value)}; allowed values: true, false", field=field
        )
    return value


def logic(value: Any, field: str) -> str:
    return choice(value, {"AND", "OR"}, field)


def choice(value: Any, allowed: set[str], field: str) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise InputValidationError(
            f"actual value: {actual_value(value)}; allowed values: "
            f"{allowed_values(allowed)}",
            field=field,
        )
    return value


def integer_range(value: Any, minimum: int, maximum: int, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not minimum <= value <= maximum:
        raise InputValidationError(
            f"actual value: {actual_value(value)}; allowed range: integer from "
            f"{minimum} through {maximum}",
            field=field,
        )
    return value
