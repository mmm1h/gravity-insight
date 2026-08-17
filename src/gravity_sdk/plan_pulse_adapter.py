"""Plan v1 validation and execution for the business pulse composite."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import Any

from .business_pulse import DEFAULT_PLATFORMS
from .plan import AdapterContext
from .plan_adapter_support import (
    input_error,
    validate_exact_targets,
    validate_selected_fields,
)
from .actionable_error_values import actual_value


_FIELDS = frozenset(
    {"name", "apps", "start", "end", "platforms", "include_hourly"}
)
_TARGETS = frozenset({"/start", "/end", "/include_hourly"})


def validate_business_pulse(
    request: Mapping[str, Any],
    context: AdapterContext,
    workspace: Any,
    output_fields: frozenset[str],
) -> None:
    if set(request) - _FIELDS:
        raise input_error(
            "business_pulse request contains unavailable fields; must use only available fields; remove extras", "request"
        )
    validate_exact_targets(context, _TARGETS)
    dynamic = set(context.dynamic_targets)
    _validate_apps(request, workspace)
    _validate_dates(request, dynamic)
    _validate_platforms(request)
    hourly = request.get("include_hourly", False)
    if "/include_hourly" not in dynamic and not isinstance(hourly, bool):
        raise input_error(
            f"actual value: {actual_value(request.get('include_hourly'))}; " + ("business_pulse include_hourly must be a boolean"), "include_hourly"
        )
    required_sources = 3 if "/include_hourly" in dynamic or hourly is True else 2
    if context.max_items < required_sources:
        raise input_error(
            "business_pulse sources exceed this node max_items; must stay at or below this node max_items; raise limits.max_items", "limits.max_items"
        )
    validate_selected_fields(context.output_fields, output_fields, "output_fields")


def execute_business_pulse(
    sdk: Any, request: Mapping[str, Any], context: AdapterContext
) -> Any:
    return sdk.business_pulse(
        request["apps"],
        request["start"],
        request["end"],
        platforms=request.get("platforms", DEFAULT_PLATFORMS),
        include_hourly=request.get("include_hourly", False),
        max_workers=1,
        max_pages=context.max_pages,
        max_items=context.max_items,
        workspace=context.workspace,
    )


def _validate_apps(request: Mapping[str, Any], workspace: Any) -> None:
    apps = request.get("apps")
    if not isinstance(apps, list) or not 1 <= len(apps) <= 100:
        raise input_error(
            f"actual value: {actual_value(apps)}; " + ("business_pulse apps must contain 1 through 100 values"), "apps"
        )
    for value in apps:
        workspace.resolve_app(value)


def _validate_dates(request: Mapping[str, Any], dynamic: set[str]) -> None:
    parsed: dict[str, date] = {}
    for field in ("start", "end"):
        if f"/{field}" in dynamic:
            continue
        try:
            parsed[field] = date.fromisoformat(request.get(field))
        except (TypeError, ValueError):
            raise input_error(
                f"actual value: {actual_value(request.get(field))}; " + ("business_pulse dates must use YYYY-MM-DD"), field
            ) from None
    if set(parsed) == {"start", "end"} and parsed["start"] > parsed["end"]:
        raise input_error(
            f"actual value: {actual_value((request.get('start'), request.get('end')))}; " + ("business_pulse start must not follow end"), "start/end"
        )


def _validate_platforms(request: Mapping[str, Any]) -> None:
    platforms = request.get("platforms", list(DEFAULT_PLATFORMS))
    if (
        not isinstance(platforms, list)
        or not platforms
        or any(value not in DEFAULT_PLATFORMS for value in platforms)
    ):
        raise input_error("business_pulse platforms are invalid; must be one of the supported platforms", "platforms")


__all__ = ["execute_business_pulse", "validate_business_pulse"]
