"""Plan v1 boundary for the Material Performance product."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .errors import InputValidationError
from .material_performance import (
    DEFAULT_PLATFORMS,
    normalize_material_apps,
    normalize_material_platforms,
    normalize_material_window,
)
from .material_performance_result import material_performance_item_count
from .material_performance_plan_result import (
    is_material_performance_result,
    project_material_performance_result,
    sanitize_product_result,
)
from .plan import AdapterContext
from .plan_adapter_support import (
    input_error,
    validate_exact_targets,
    validate_selected_fields,
)


MATERIAL_PERFORMANCE_NAME = "material_performance"
MATERIAL_PERFORMANCE_FIELDS = frozenset(
    {"name", "apps", "start", "end", "platforms"}
)
MATERIAL_PERFORMANCE_OUTPUT_FIELDS = frozenset(
    {
        "app_count", "date_range", "failure_count", "limits", "operation_id",
        "platform_count", "platforms", "results", "returned_items",
        "success_count", "total_count",
    }
)
_TARGETS = frozenset({"/start", "/end"})


def validate_material_performance_plan(
    request: Mapping[str, Any],
    context: AdapterContext,
    workspace: Any,
) -> None:
    """Fully validate literal arrays while allowing only scalar date bindings."""

    if set(request) - MATERIAL_PERFORMANCE_FIELDS:
        raise input_error(
            "material_performance request contains unavailable fields", "request"
        )
    if request.get("name") != MATERIAL_PERFORMANCE_NAME:
        raise input_error("material_performance name is invalid", "name")
    validate_exact_targets(context, _TARGETS)
    apps = request.get("apps")
    if not isinstance(apps, list) or not 1 <= len(apps) <= 100:
        raise input_error(
            "material_performance apps must contain 1 through 100 values", "apps"
        )
    try:
        resolved = [workspace.resolve_app(value) for value in apps]
        normalized = normalize_material_apps(resolved)
    except (KeyError, TypeError, ValueError):
        raise input_error(
            "material_performance apps must select configured workspace Apps", "apps"
        ) from None
    if len(normalized) != len(apps):
        raise input_error("material_performance apps must resolve uniquely", "apps")
    try:
        platforms = normalize_material_platforms(
            request.get("platforms", list(DEFAULT_PLATFORMS))
        )
    except InputValidationError as exc:
        raise input_error(str(exc), "platforms") from None
    if context.max_items < len(platforms):
        raise input_error(
            "material_performance platforms exceed this node max_items",
            "limits.max_items",
        )
    _validate_dates(request, set(context.dynamic_targets))
    validate_selected_fields(
        context.output_fields,
        MATERIAL_PERFORMANCE_OUTPUT_FIELDS,
        "output_fields",
    )


def execute_material_performance_plan(
    sdk: Any,
    request: Mapping[str, Any],
    context: AdapterContext,
) -> dict[str, Any]:
    """Execute with inner worker one, then re-verify the public envelope."""

    platforms = tuple(request.get("platforms", DEFAULT_PLATFORMS))
    result = sdk.material_performance(
        request["apps"],
        request["start"],
        request["end"],
        platforms=platforms,
        max_workers=1,
        max_pages=context.max_pages,
        max_items=context.max_items,
        workspace=context.workspace,
    )
    safe = sanitize_product_result(
        result,
        expected_platforms=platforms,
        expected_app_count=len(request["apps"]),
        expected_window=(request["start"], request["end"]),
        expected_max_pages=context.max_pages,
        expected_max_items=context.max_items,
        expected_max_workers=1,
    )
    if material_performance_item_count(safe) > context.max_items:
        raise input_error(
            "material_performance exceeded its Plan item budget", "limits.max_items"
        )
    return safe


def _validate_dates(request: Mapping[str, Any], dynamic: set[str]) -> None:
    start, end = request.get("start"), request.get("end")
    if "/start" not in dynamic and not isinstance(start, str):
        raise input_error("material_performance start must be a literal date", "start")
    if "/end" not in dynamic and not isinstance(end, str):
        raise input_error("material_performance end must be a literal date", "end")
    first = "2026-01-01" if "/start" in dynamic else start
    last = "2026-01-02" if "/end" in dynamic else end
    if not dynamic:
        try:
            normalize_material_window(first, last)
        except InputValidationError as exc:
            raise input_error(str(exc), "start/end") from None
        return
    for field, value in (("start", first), ("end", last)):
        try:
            normalize_material_window(value, value)
        except InputValidationError as exc:
            raise input_error(str(exc), field) from None


__all__ = [
    "MATERIAL_PERFORMANCE_FIELDS",
    "MATERIAL_PERFORMANCE_NAME",
    "MATERIAL_PERFORMANCE_OUTPUT_FIELDS",
    "execute_material_performance_plan",
    "is_material_performance_result",
    "project_material_performance_result",
    "validate_material_performance_plan",
]
