"""Plan v1 boundary for the fixed attribution-performance panels."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .attribution import (
    validate_attribution_performance_request,
    validate_attribution_user_detail_request,
)
from .errors import InputValidationError
from .plan import AdapterContext
from .plan_adapter_support import validate_exact_targets, validate_selected_fields


ATTRIBUTION_PERFORMANCE_NAME = "attribution_performance"
REQUEST_FIELDS = frozenset({"name", "app", "start", "end"})
OUTPUT_FIELDS = frozenset(
    {
        "app_id",
        "date_range",
        "profiles",
        "results",
        "source_count",
    }
)
_TARGETS = frozenset({"/app", "/start", "/end"})
ATTRIBUTION_USER_DETAIL_NAME = "attribution_user_detail"
USER_DETAIL_REQUEST_FIELDS = frozenset({"name", "app", "device_id"})
USER_DETAIL_OUTPUT_FIELDS = frozenset(
    {"operation_id", "app_id", "device_id", "data"}
)
_USER_DETAIL_TARGETS = frozenset({"/app", "/device_id"})


def validate_attribution_performance_plan(
    request: Mapping[str, Any],
    context: AdapterContext,
    workspace: Any,
) -> None:
    if set(request) != REQUEST_FIELDS or request.get("name") != ATTRIBUTION_PERFORMANCE_NAME:
        raise _plan_input_error(
            "attribution_performance request has an invalid actual value; it must contain only name, app, start, and end",
            "request",
        )
    validate_exact_targets(context, _TARGETS)
    dynamic = set(context.dynamic_targets)
    app = 1 if "/app" in dynamic else workspace.resolve_app(request["app"])
    start = "2026-01-01" if "/start" in dynamic else request["start"]
    end = "2026-01-01" if "/end" in dynamic else request["end"]
    validate_attribution_performance_request(
        app,
        start,
        end,
        max_workers=4,
        max_pages=context.max_pages,
        max_items=context.max_items,
    )
    validate_selected_fields(context.output_fields, OUTPUT_FIELDS, "output_fields")


def execute_attribution_performance_plan(
    sdk: Any,
    request: Mapping[str, Any],
    context: AdapterContext,
) -> dict[str, Any]:
    with context.borrow_workers(4) as workers:
        return sdk.attribution_performance(
            request["app"],
            start=request["start"],
            end=request["end"],
            max_workers=workers,
            max_pages=context.max_pages,
            max_items=context.max_items,
            workspace=context.workspace,
        )


def validate_attribution_user_detail_plan(
    request: Mapping[str, Any],
    context: AdapterContext,
    workspace: Any,
) -> None:
    if (
        set(request) != USER_DETAIL_REQUEST_FIELDS
        or request.get("name") != ATTRIBUTION_USER_DETAIL_NAME
    ):
        raise _plan_input_error(
            "attribution_user_detail request has an invalid actual value; it must contain only name, app, and device_id",
            "request",
        )
    validate_exact_targets(context, _USER_DETAIL_TARGETS)
    dynamic = set(context.dynamic_targets)
    app = 1 if "/app" in dynamic else workspace.resolve_app(request["app"])
    device_id = 1 if "/device_id" in dynamic else request["device_id"]
    validate_attribution_user_detail_request(app, device_id)
    validate_selected_fields(
        context.output_fields, USER_DETAIL_OUTPUT_FIELDS, "output_fields"
    )


def execute_attribution_user_detail_plan(
    sdk: Any,
    request: Mapping[str, Any],
    context: AdapterContext,
) -> dict[str, Any]:
    return sdk.attribution_user_detail(
        request["app"],
        request["device_id"],
        workspace=context.workspace,
    )


def _plan_input_error(message: str, field: str) -> InputValidationError:
    product = "attribution_user_detail" if message.startswith("attribution_user_detail") else "attribution_performance"
    return InputValidationError(
        message,
        field=field,
        next_action=f"Use the {product} Agent input template and retry the Plan.",
    )


__all__ = [
    "ATTRIBUTION_PERFORMANCE_NAME",
    "ATTRIBUTION_USER_DETAIL_NAME",
    "OUTPUT_FIELDS",
    "USER_DETAIL_OUTPUT_FIELDS",
    "execute_attribution_performance_plan",
    "execute_attribution_user_detail_plan",
    "validate_attribution_performance_plan",
    "validate_attribution_user_detail_plan",
]
