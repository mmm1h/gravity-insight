"""Narrow Plan family router for governed report composites."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .agent_company_usage import COMPANY_USAGE_NAME
from .plan import AdapterContext
from .plan_adapter_support import input_error, validate_selected_fields
from .plan_pulse_adapter import execute_business_pulse, validate_business_pulse


BUSINESS_PULSE_NAME = "business_pulse"
COMPOSITE_NAMES = frozenset({BUSINESS_PULSE_NAME, COMPANY_USAGE_NAME})


def is_report_composite(name: Any) -> bool:
    return name in COMPOSITE_NAMES


def validate_report_composite(
    request: Mapping[str, Any],
    context: AdapterContext,
    workspace: Any,
    output_fields: frozenset[str],
) -> None:
    if request.get("name") == BUSINESS_PULSE_NAME:
        validate_business_pulse(request, context, workspace, output_fields)
        return
    if set(request) != {"name"}:
        raise input_error("company_usage request accepts only its name", "request")
    if context.dynamic_targets:
        raise input_error("company_usage has no binding targets", "bindings")
    if context.max_items < 1:
        raise input_error("company_usage requires one source item", "limits.max_items")
    validate_selected_fields(context.output_fields, output_fields, "output_fields")


def execute_report_composite(
    sdk: Any, request: Mapping[str, Any], context: AdapterContext
) -> Any:
    if request.get("name") == BUSINESS_PULSE_NAME:
        return execute_business_pulse(sdk, request, context)
    return sdk.company_usage(
        max_pages=context.max_pages,
        max_items=context.max_items,
    )


__all__ = [
    "COMPOSITE_NAMES",
    "execute_report_composite",
    "is_report_composite",
    "validate_report_composite",
]
