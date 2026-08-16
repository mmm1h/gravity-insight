"""Fail-closed validation for the frontend-proven custom-metric wire."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from .actionable_error_values import actual_value
from .custom_metric_contracts import CUSTOM_METRIC_DELETE, CUSTOM_METRIC_UPSERT
from .errors import InputValidationError


def validate_custom_metric_wire(
    operation_id: str, values: Mapping[str, Any]
) -> None:
    if operation_id == CUSTOM_METRIC_DELETE:
        _metric_id(values.get("id"), "id")
        return
    if operation_id != CUSTOM_METRIC_UPSERT:
        return
    _text(values.get("cname"), "cname", 128)
    tip = values.get("tip")
    if not isinstance(tip, str) or len(tip) > 2_000:
        raise custom_metric_wire_error(
            actual_value(tip), "text of at most 2000 characters", "tip",
            "Correct tip within the frontend-supported bound and rerun the dry-run.",
        )
    formula = _text(values.get("formula"), "formula", 4_096)
    display_format = values.get("display_format")
    if type(display_format) is not int or display_format not in range(1, 7):
        raise custom_metric_wire_error(
            actual_value(display_format), "an integer from 1 through 6",
            "display_format", "Choose one frontend-supported display format and rerun the dry-run.",
        )
    if "id" in values:
        _metric_id(values.get("id"), "id")
    config = values.get("config")
    try:
        decoded = json.loads(config) if isinstance(config, str) else None
    except json.JSONDecodeError:
        decoded = None
    expected = {"formula": formula, "display_format": display_format}
    if decoded != expected:
        raise custom_metric_wire_error(
            actual_value(decoded), actual_value(expected), "config",
            "Generate config through the custom-metric product; do not hand-edit the upsert wire.",
        )


def _metric_id(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 128:
        raise custom_metric_wire_error(
            actual_value(value), "a non-empty string ID returned by custom_metric.list",
            field, "Use the exact metric ID from the current list and rerun the dry-run.",
        )
    return value


def _text(value: Any, field: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise custom_metric_wire_error(
            actual_value(value), f"non-empty text of at most {maximum} characters",
            field, f"Correct {field} within the documented bound and rerun the dry-run.",
        )
    return value


def custom_metric_wire_error(
    actual: str, allowed: str, field: str, next_action: str
) -> InputValidationError:
    return InputValidationError(
        f"actual value: {actual}; allowed value: {allowed}",
        field=field,
        next_action=next_action,
    )


__all__ = ["validate_custom_metric_wire"]
