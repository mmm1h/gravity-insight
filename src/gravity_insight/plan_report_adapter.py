"""Narrow Plan family router for governed report composites."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .actionable_error_values import actual_value
from . import plan_advertiser_profile_adapter as advertiser_plan
from . import plan_custom_audience_adapter as custom_audience_plan
from .agents.company_usage import COMPANY_USAGE_NAME
from .agents.report_directory import REPORT_DIRECTORY_NAME, REPORT_SUBSCRIPTIONS_NAME
from .plan import AdapterContext
from .plan_adapter_support import input_error, validate_selected_fields
from .plan_pulse_adapter import execute_business_pulse, validate_business_pulse


BUSINESS_PULSE_NAME = "business_pulse"
COMPOSITE_NAMES = frozenset({
    advertiser_plan.ADVERTISER_PROFILE_NAME,
    BUSINESS_PULSE_NAME,
    COMPANY_USAGE_NAME,
    REPORT_DIRECTORY_NAME,
    REPORT_SUBSCRIPTIONS_NAME,
    custom_audience_plan.CUSTOM_AUDIENCE_NAME,
})


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
    if request.get("name") == advertiser_plan.ADVERTISER_PROFILE_NAME:
        advertiser_plan.validate_advertiser_profile_plan(
            request, context, output_fields
        )
        return
    if request.get("name") == custom_audience_plan.CUSTOM_AUDIENCE_NAME:
        custom_audience_plan.validate_custom_audience_plan(
            request, context, output_fields
        )
        return
    if request.get("name") in {REPORT_DIRECTORY_NAME, REPORT_SUBSCRIPTIONS_NAME}:
        if set(request) != {"name"}:
            raise input_error(
                f"actual value: {actual_value(sorted(request))}; allowed value: a report catalog request containing only name; use only the selected composite name",
                "request",
            )
        if context.dynamic_targets:
            raise input_error(
                f"actual value: {actual_value(context.dynamic_targets)}; allowed value: no report catalog bindings; remove every binding target",
                "bindings",
            )
        if context.max_items < 1:
            raise input_error(
                f"actual value: {actual_value(context.max_items)}; allowed range: 1 or greater; set limits.max_items to at least 1",
                "limits.max_items",
            )
        validate_selected_fields(context.output_fields, output_fields, "output_fields")
        return
    if set(request) != {"name"}:
        raise input_error(f"actual value: {actual_value(sorted(request))}; company_usage request accepts only its name; must contain only its name; remove extras", "request")
    if context.dynamic_targets:
        raise input_error(f"actual value: {actual_value(context.dynamic_targets)}; company_usage has no binding targets; must contain only its name; remove extras", "bindings")
    if context.max_items < 1:
        raise input_error(f"actual value: {actual_value(context.max_items)}; " + ("company_usage requires one source item"), "limits.max_items")
    validate_selected_fields(context.output_fields, output_fields, "output_fields")


def execute_report_composite(
    sdk: Any, request: Mapping[str, Any], context: AdapterContext
) -> Any:
    if request.get("name") == BUSINESS_PULSE_NAME:
        return execute_business_pulse(sdk, request, context)
    if request.get("name") == advertiser_plan.ADVERTISER_PROFILE_NAME:
        return advertiser_plan.execute_advertiser_profile_plan(
            sdk, request, context
        )
    if request.get("name") == custom_audience_plan.CUSTOM_AUDIENCE_NAME:
        return custom_audience_plan.execute_custom_audience_plan(
            sdk, request, context
        )
    if request.get("name") == REPORT_DIRECTORY_NAME:
        return sdk.report_directory(
            max_pages=context.max_pages, max_items=context.max_items,
            max_workers=context.max_workers,
        )
    if request.get("name") == REPORT_SUBSCRIPTIONS_NAME:
        return sdk.report_subscriptions(
            max_pages=context.max_pages, max_items=context.max_items,
        )
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
