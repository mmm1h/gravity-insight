"""Plan v1 boundary for the fixed attribution-performance panels."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .attribution import validate_attribution_performance_request
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


def _plan_input_error(message: str, field: str) -> InputValidationError:
    return InputValidationError(
        message,
        field=field,
        next_action=(
            "Use the attribution_performance Agent input template and retry the Plan."
        ),
    )


__all__ = [
    "ATTRIBUTION_PERFORMANCE_NAME",
    "OUTPUT_FIELDS",
    "execute_attribution_performance_plan",
    "validate_attribution_performance_plan",
]
