"""Plan routing for fixed-source composite reads."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .plan import AdapterContext
from .plan_adapter_support import input_error


COMPOSITE_NAMES = frozenset(
    {"analysis_context", "app_snapshot", "attribution_snapshot", "attribution_performance"}
)
_REQUIRED_ITEMS = {
    "analysis_context": 13,
    "app_snapshot": 6,
    "attribution_snapshot": 8,
    "attribution_performance": 4,
}


def is_fixed_composite(name: Any) -> bool:
    return name in COMPOSITE_NAMES


def validate_fixed_composite(
    request: Mapping[str, Any], context: AdapterContext, name: str
) -> None:
    if name == "attribution_performance":
        from .plan_attribution_adapter import validate_attribution_performance_plan

        validate_attribution_performance_plan(request, context, context.workspace)
        return
    if set(request) - {"name", "app"}:
        raise input_error("composite request contains fields unavailable for this name", "request")
    if context.max_items < _REQUIRED_ITEMS[name]:
        raise input_error(
            "composite fixed sources exceed this node max_items", "limits.max_items"
        )


def execute_fixed_composite(
    sdk: Any, request: Mapping[str, Any], context: AdapterContext
) -> Any:
    name, app = str(request["name"]), request.get("app")
    if name == "attribution_performance":
        from .plan_attribution_adapter import execute_attribution_performance_plan

        return execute_attribution_performance_plan(sdk, request, context)
    options = {
        "max_pages": context.max_pages,
        "max_items": context.max_items,
        "workspace": context.workspace,
    }
    if name == "analysis_context":
        with context.borrow_workers(_REQUIRED_ITEMS[name]) as workers:
            return sdk.analysis_context(app, max_workers=workers, **options)
    method = sdk.app_snapshot if name == "app_snapshot" else sdk.attribution_snapshot
    return method(app, max_workers=1, **options)


__all__ = [
    "COMPOSITE_NAMES",
    "execute_fixed_composite",
    "is_fixed_composite",
    "validate_fixed_composite",
]
