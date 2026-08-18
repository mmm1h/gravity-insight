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
from .actionable_error_values import actual_value
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
            f"actual value: {actual_value(value.get('formula'))}; retention "
            "before/after formula must be one of +, -, *, /; request was not sent",
            field="formula",
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
                f"actual value: {actual_value(value.get(field_name))}; retention "
                "before/after precision must be one of two_point, three_point, "
                "four_point, percentage, integer; request was not sent",
                field=field_name,
            )
    if not isinstance(value.get("a_to_b", False), bool):
        raise InputValidationError(
            f"actual value: {actual_value(value.get('a_to_b'))}; retention before/after "
            "a_to_b must be a boolean; request was not sent",
            field="a_to_b",
        )
    name = value.get("name", "")
    if not isinstance(name, str) or not 1 <= len(name) <= 20 or "\x00" in name:
        raise InputValidationError(
            f"actual value: {actual_value(name)}; retention before/after name must be a "
            "1-20 character string; request was not sent",
            field="name",
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
            f"actual value: {actual_value(event_name)}; retention before/after "
            "event_name must be a non-empty string of at most 256 characters; request "
            "was not sent",
            field="event_name",
        )
    references.events.add(event_name)
    validate_optional_label(value.get("custom_name"), "custom_name")
    if before:
        validate_optional_label(value.get("customBeforeName"), "customBeforeName")
    if value.get("cond_logic", "AND") not in {"AND", "OR"}:
        raise InputValidationError(
            f"actual value: {actual_value(value.get('cond_logic'))}; retention "
            "before/after cond_logic must be one of AND, OR; request was not sent",
            field="cond_logic",
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
                f"actual value: {actual_value(field_value)}; retention before/after "
                "property must be a non-empty string of at most 256 characters; request "
                "was not sent",
                field=field_name,
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
            f"actual value: {actual_value(type(items).__name__) if not isinstance(items, (list, tuple)) else len(items)}; "
            "retention custom list must contain 1 through 50 event items; request was "
            "not sent",
            field="list",
        )
    for item in items:
        validate_retention_boundary_item(item, references, before=before)
    validate_analysis_conditions(
        value.get("conditions", ()), references, "retention custom conditions"
    )
    if value.get("cond_logic", "AND") not in {"AND", "OR"}:
        raise InputValidationError(
            f"actual value: {actual_value(value.get('cond_logic'))}; retention custom "
            "cond_logic must be one of AND, OR; request was not sent",
            field="cond_logic",
        )
    formula = value.get("formula")
    if not isinstance(formula, str) or not formula or not ANALYSIS_FORMULA_RE.fullmatch(formula):
        raise InputValidationError(
            f"actual value: {actual_value(formula)}; retention custom formula must "
            "match the bounded arithmetic pattern; request was not sent",
            field="formula",
        )
    if before:
        validate_optional_label(value.get("customBeforeName"), "customBeforeName")
