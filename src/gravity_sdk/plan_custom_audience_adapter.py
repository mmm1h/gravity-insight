"""Plan adapter for the custom-audience coverage and status product."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .agent_custom_audience import CUSTOM_AUDIENCE_NAME
from .plan import AdapterContext
from .plan_adapter_support import input_error, validate_selected_fields
from .actionable_error_values import actual_value


def validate_custom_audience_plan(
    request: Mapping[str, Any],
    context: AdapterContext,
    output_fields: frozenset[str],
) -> None:
    if set(request) != {"name"}:
        raise input_error(
            "custom_audience request accepts only its name", "request"
        )
    if context.dynamic_targets:
        raise input_error("custom_audience has no binding targets", "bindings")
    if context.max_items < 1:
        raise input_error(
            f"actual value: {actual_value(context.max_items)}; " + ("custom_audience requires one source item"), "limits.max_items"
        )
    validate_selected_fields(context.output_fields, output_fields, "output_fields")


def execute_custom_audience_plan(
    sdk: Any, _request: Mapping[str, Any], context: AdapterContext
) -> Any:
    return sdk.custom_audiences(
        max_pages=context.max_pages,
        max_items=context.max_items,
    )


__all__ = [
    "CUSTOM_AUDIENCE_NAME",
    "execute_custom_audience_plan",
    "validate_custom_audience_plan",
]
