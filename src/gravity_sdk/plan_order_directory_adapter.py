"""Request-bound Plan v1 boundary for Order Directory."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from .plan import AdapterContext
from .plan_adapter_support import (
    input_error,
    validate_exact_targets,
    validate_selected_fields,
)


ORDER_DIRECTORY_NAME = "order_directory"
ORDER_DIRECTORY_FIELDS = frozenset({"name", "app", "date"})
ORDER_DIRECTORY_OUTPUT_FIELDS = frozenset(
    {"app_id", "data", "date", "limits", "page", "returned_items"}
)
_TARGETS = frozenset({"/app", "/date"})
_STRUCTURAL = frozenset(
    {
        "schema_version", "ok", "status", "exit_code", "error", "next_action",
        "app_id", "date",
    }
)


class _VerifiedData(dict[str, Any]):
    """In-process marker added only after request-bound reconstruction."""


def validate_order_directory_plan(
    request: Mapping[str, Any],
    context: AdapterContext,
    workspace: Any,
) -> None:
    """Validate the closed request and its two scalar binding targets."""

    if set(request) != ORDER_DIRECTORY_FIELDS:
        raise input_error(
            "order_directory request fields are incomplete or unavailable; must include the required product fields", "request"
        )
    if request.get("name") != ORDER_DIRECTORY_NAME:
        raise input_error("order_directory name is invalid; must match the documented composite name", "name")
    validate_exact_targets(context, _TARGETS)
    _validate_bound_request(request, set(context.dynamic_targets), workspace, context)
    validate_selected_fields(
        context.output_fields, ORDER_DIRECTORY_OUTPUT_FIELDS, "output_fields"
    )


def execute_order_directory_plan(
    sdk: Any,
    request: Mapping[str, Any],
    context: AdapterContext,
) -> dict[str, Any]:
    """Execute serially inside Plan, then re-sanitize against the request."""

    from .order_directory import (
        order_directory_item_count,
        sanitize_order_directory_result,
        validate_order_directory_request,
    )

    try:
        app_id = context.workspace.resolve_app(request["app"])
        canonical = validate_order_directory_request(
            app_id,
            request["date"],
            max_workers=1,
            max_pages=context.max_pages,
            max_items=context.max_items,
        )
    except (KeyError, TypeError, ValueError):
        raise input_error("order_directory bound request is invalid; must pass product validation", "request") from None
    result = sdk.order_directory(
        request["app"],
        canonical[1],
        max_workers=1,
        max_pages=context.max_pages,
        max_items=context.max_items,
        workspace=context.workspace,
    )
    safe = sanitize_order_directory_result(
        result,
        canonical[0],
        canonical[1],
        max_pages=context.max_pages,
        max_items=context.max_items,
        max_workers=1,
    )
    if order_directory_item_count(safe) > context.max_items:
        raise input_error(
            "order_directory exceeded its Plan item budget; must stay at or below this node max_items; raise limits.max_items", "limits.max_items"
        )
    if isinstance(safe.get("data"), Mapping):
        safe["data"] = _VerifiedData(safe["data"])
    return safe


def is_order_directory_result(value: Any) -> bool:
    from .order_directory import SCHEMA_VERSION

    return isinstance(value, Mapping) and value.get("schema_version") == SCHEMA_VERSION


def project_order_directory_result(
    value: Any,
    fields: tuple[str, ...],
    context: AdapterContext,
) -> dict[str, Any]:
    """Project only an envelope verified by this adapter's executor."""

    from .order_directory import sanitize_order_directory_result

    if not isinstance(value, Mapping) or not isinstance(
        value.get("data"), _VerifiedData
    ):
        app_id = value.get("app_id", "1") if isinstance(value, Mapping) else "1"
        date = value.get("date", "2026-01-01") if isinstance(value, Mapping) else "2026-01-01"
        try:
            return sanitize_order_directory_result(
                {}, app_id, date,
                max_pages=context.max_pages, max_items=context.max_items,
                max_workers=1,
            )
        except (TypeError, ValueError):
            return sanitize_order_directory_result(
                {}, "1", "2026-01-01", max_pages=context.max_pages,
                max_items=context.max_items, max_workers=1,
            )
    if not fields or value.get("status") == "contract_changed":
        return copy.deepcopy(dict(value))
    allowed = _STRUCTURAL | set(fields)
    return {
        key: copy.deepcopy(item)
        for key, item in value.items()
        if key in allowed
    }


def _validate_bound_request(
    request: Mapping[str, Any],
    dynamic: set[str],
    workspace: Any,
    context: AdapterContext,
) -> None:
    from .order_directory import validate_order_directory_request

    try:
        app = 1 if "/app" in dynamic else workspace.resolve_app(request.get("app"))
        date = "2026-01-01" if "/date" in dynamic else request.get("date")
        validate_order_directory_request(
            app,
            date,
            max_workers=1,
            max_pages=context.max_pages,
            max_items=context.max_items,
        )
    except (KeyError, TypeError, ValueError):
        raise input_error("order_directory request is invalid; must pass product validation", "request") from None


__all__ = [
    "ORDER_DIRECTORY_FIELDS",
    "ORDER_DIRECTORY_NAME",
    "ORDER_DIRECTORY_OUTPUT_FIELDS",
    "execute_order_directory_plan",
    "is_order_directory_result",
    "project_order_directory_result",
    "validate_order_directory_plan",
]
