"""Retention-specific validators for the Analysis query DSL."""

from __future__ import annotations

from typing import Any

from ._field_policy_conditions import (
    validate_analysis_conditions,
    validate_analysis_target,
)
from ._field_policy_shared import (
    ANALYSIS_FORMULA_RE,
    ANALYSIS_TARGET_METHODS,
    AnalysisReferences,
    require_exact_mapping,
    validate_optional_label,
)
from .errors import InputValidationError


def validate_retention_before_after(
    value: Any, references: AnalysisReferences
) -> None:
    if value in (None, {}):
        return
    require_exact_mapping(
        value,
        {
            "after",
            "after_custom",
            "before",
            "before_custom",
            "formula",
            "decimal_point",
            "before_decimal_point",
            "a_to_b",
            "name",
        },
        "retention query_item_before_after",
    )
    _validate_before_after_controls(value)
    for field_name in ("after", "before"):
        item = value.get(field_name)
        if item not in (None, {}):
            validate_retention_boundary_item(
                item, references, before=field_name == "before"
            )
    for field_name in ("after_custom", "before_custom"):
        item = value.get(field_name)
        if item not in (None, {}):
            validate_retention_custom_item(
                item, references, before=field_name == "before_custom"
            )


def _validate_before_after_controls(value: Any) -> None:
    if value.get("formula", "+") not in {"+", "-", "*", "/"}:
        raise InputValidationError(
            "retention before/after formula is invalid; request was not sent"
        )
    precision_values = {
        "two_point",
        "three_point",
        "four_point",
        "percentage",
        "integer",
    }
    for field_name in ("decimal_point", "before_decimal_point"):
        if value.get(field_name, "two_point") not in precision_values:
            raise InputValidationError(
                "retention before/after precision is invalid; request was not sent"
            )
    if not isinstance(value.get("a_to_b", False), bool):
        raise InputValidationError(
            "retention before/after direction is invalid; request was not sent"
        )
    name = value.get("name", "")
    if not isinstance(name, str) or not 1 <= len(name) <= 20 or "\x00" in name:
        raise InputValidationError(
            "retention before/after name is invalid; request was not sent"
        )


def validate_retention_boundary_item(
    value: Any,
    references: AnalysisReferences,
    *,
    before: bool,
) -> None:
    allowed = {
        "event_name",
        "custom_name",
        "target",
        "conditions",
        "cond_logic",
        "prop_to_calc",
        "prop_to_calc_target",
    }
    if before:
        allowed.add("customBeforeName")
    require_exact_mapping(value, allowed, "retention before/after event")
    event_name = value.get("event_name")
    if not isinstance(event_name, str) or not event_name or len(event_name) > 256:
        raise InputValidationError(
            "retention before/after event is invalid; request was not sent"
        )
    references.events.add(event_name)
    validate_optional_label(value.get("custom_name"), "custom_name")
    if before:
        validate_optional_label(value.get("customBeforeName"), "customBeforeName")
    if value.get("cond_logic", "AND") not in {"AND", "OR"}:
        raise InputValidationError(
            "retention before/after condition logic is invalid; request was not sent"
        )
    validate_analysis_target(
        value.get("target"),
        references.event_fields,
        references.event_dimension_tables,
    )
    validate_analysis_conditions(
        value.get("conditions", ()), references, "retention before/after conditions"
    )
    _add_retention_properties(value, references)


def _add_retention_properties(value: Any, references: AnalysisReferences) -> None:
    for field_name in ("prop_to_calc", "prop_to_calc_target"):
        field_value = value.get(field_name)
        if field_value in (None, ""):
            continue
        if (
            not isinstance(field_value, str)
            or len(field_value) > 256
            or "\x00" in field_value
        ):
            raise InputValidationError(
                "retention before/after property is invalid; request was not sent"
            )
        if field_value not in ANALYSIS_TARGET_METHODS:
            references.event_fields.add(field_value)


def validate_retention_custom_item(
    value: Any,
    references: AnalysisReferences,
    *,
    before: bool,
) -> None:
    allowed = {"list", "conditions", "cond_logic", "formula"}
    if before:
        allowed.add("customBeforeName")
    require_exact_mapping(value, allowed, "retention custom before/after")
    items = value.get("list")
    if not isinstance(items, (list, tuple)) or not 1 <= len(items) <= 50:
        raise InputValidationError(
            "retention custom event list is invalid; request was not sent"
        )
    for item in items:
        validate_retention_boundary_item(item, references, before=before)
    validate_analysis_conditions(
        value.get("conditions", ()), references, "retention custom conditions"
    )
    if value.get("cond_logic", "AND") not in {"AND", "OR"}:
        raise InputValidationError(
            "retention custom condition logic is invalid; request was not sent"
        )
    formula = value.get("formula")
    if not isinstance(formula, str) or not formula or not ANALYSIS_FORMULA_RE.fullmatch(formula):
        raise InputValidationError(
            "retention custom formula is invalid; request was not sent"
        )
    if before:
        validate_optional_label(value.get("customBeforeName"), "customBeforeName")
