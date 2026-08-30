"""Plan routing for fixed-source composite reads."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .plan import AdapterContext
from .plan_adapter_support import has_dynamic, input_error
from .actionable_error_values import actual_value
from . import plan_metadata_sync_adapter as metadata_sync_plan


COMPOSITE_NAMES = frozenset(
    {
        "analysis_context", "app_snapshot", "attribution_snapshot",
        "attribution_performance", "attribution_user_detail",
        metadata_sync_plan.NAME,
    }
)
_REQUIRED_ITEMS = {
    "analysis_context": 13,
    "app_snapshot": 6,
    "attribution_snapshot": 8,
    "attribution_performance": 4,
    "attribution_user_detail": 1,
}


def is_fixed_composite(name: Any) -> bool:
    return name in COMPOSITE_NAMES


def validate_fixed_composite(
    request: Mapping[str, Any], context: AdapterContext, name: str
) -> None:
    if metadata_sync_plan.is_metadata_sync(name):
        metadata_sync_plan.validate_metadata_sync(request, context)
        return
    if name == "attribution_performance":
        from .plan_attribution_adapter import validate_attribution_performance_plan

        validate_attribution_performance_plan(request, context, context.workspace)
        return
    if name == "attribution_user_detail":
        from .plan_attribution_adapter import validate_attribution_user_detail_plan

        validate_attribution_user_detail_plan(request, context, context.workspace)
        return
    if set(request) - {"name", "app"}:
        raise input_error(f"actual value: {actual_value(sorted(set(request) - {'name', 'app'}))}; composite request must use only fields available for this name; remove extras", "request")
    if context.max_items < _REQUIRED_ITEMS[name]:
        raise input_error(
            f"actual value: {actual_value((_REQUIRED_ITEMS[name], context.max_items))}; composite fixed sources exceed this node max_items; must stay at or below this node max_items; raise limits.max_items", "limits.max_items"
        )
    if not has_dynamic(context, "/app"):
        context.workspace.resolve_app(request.get("app"))


def execute_fixed_composite(
    sdk: Any,
    request: Mapping[str, Any],
    context: AdapterContext,
    *,
    database: Path | None = None,
) -> Any:
    name, app = str(request["name"]), request.get("app")
    if metadata_sync_plan.is_metadata_sync(name):
        return metadata_sync_plan.execute_metadata_sync(
            sdk, request, context, database=database
        )
    if name == "attribution_performance":
        from .plan_attribution_adapter import execute_attribution_performance_plan

        return execute_attribution_performance_plan(sdk, request, context)
    if name == "attribution_user_detail":
        from .plan_attribution_adapter import execute_attribution_user_detail_plan

        return execute_attribution_user_detail_plan(sdk, request, context)
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
