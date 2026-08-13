"""Request-bound Plan v1 boundary for Monetization Detail."""

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


MONETIZATION_DETAIL_NAME = "monetization_detail"
REQUEST_FIELDS = frozenset({"name", "app", "date"})
OUTPUT_FIELDS = frozenset(
    {"app_id", "data", "date", "limits", "page", "returned_items"}
)
_TARGETS = frozenset({"/app", "/date"})
_STRUCTURAL = frozenset(
    {
        "schema_version",
        "ok",
        "status",
        "exit_code",
        "error",
        "next_action",
        "app_id",
        "date",
    }
)


class _VerifiedData(dict[str, Any]):
    """In-process marker added after request-bound reconstruction."""


def validate_monetization_detail_plan(
    request: Mapping[str, Any],
    context: AdapterContext,
    workspace: Any,
) -> None:
    """Validate the closed request and its two scalar binding targets."""

    if set(request) != REQUEST_FIELDS:
        raise input_error(
            "monetization_detail request fields are incomplete or unavailable",
            "request",
        )
    if request.get("name") != MONETIZATION_DETAIL_NAME:
        raise input_error("monetization_detail name is invalid", "name")
    validate_exact_targets(context, _TARGETS)
    _validate_bound_request(request, set(context.dynamic_targets), workspace, context)
    validate_selected_fields(context.output_fields, OUTPUT_FIELDS, "output_fields")


def execute_monetization_detail_plan(
    sdk: Any,
    request: Mapping[str, Any],
    context: AdapterContext,
) -> dict[str, Any]:
    """Execute serially inside Plan, then sanitize against the bound request."""

    from .monetization_detail import (
        monetization_detail_item_count,
        sanitize_monetization_detail_result,
        validate_monetization_detail_request,
    )

    try:
        app_id = context.workspace.resolve_app(request["app"])
        canonical = validate_monetization_detail_request(
            app_id,
            request["date"],
            max_workers=1,
            max_pages=context.max_pages,
            max_items=context.max_items,
        )
    except (KeyError, TypeError, ValueError):
        raise input_error(
            "monetization_detail bound request is invalid", "request"
        ) from None
    result = sdk.monetization_detail(
        request["app"],
        canonical[1],
        max_workers=1,
        max_pages=context.max_pages,
        max_items=context.max_items,
        workspace=context.workspace,
    )
    safe = sanitize_monetization_detail_result(
        result,
        canonical[0],
        canonical[1],
        max_workers=1,
        max_pages=context.max_pages,
        max_items=context.max_items,
    )
    if monetization_detail_item_count(safe) > context.max_items:
        raise input_error(
            "monetization_detail exceeded its Plan item budget", "limits.max_items"
        )
    if isinstance(safe.get("data"), Mapping):
        safe["data"] = _VerifiedData(safe["data"])
    return safe


def is_monetization_detail_result(value: Any) -> bool:
    from .monetization_detail import SCHEMA_VERSION

    return isinstance(value, Mapping) and value.get("schema_version") == SCHEMA_VERSION


def project_monetization_detail_result(
    value: Any,
    fields: tuple[str, ...],
    context: AdapterContext,
) -> dict[str, Any]:
    """Project only data verified by this adapter's executor."""

    if not isinstance(value, Mapping) or not isinstance(
        value.get("data"), _VerifiedData
    ):
        return _invalid_result(value, context)
    if not fields or value.get("status") == "contract_changed":
        return copy.deepcopy(dict(value))
    allowed = _STRUCTURAL | set(fields)
    return {
        key: copy.deepcopy(item) for key, item in value.items() if key in allowed
    }


def _validate_bound_request(
    request: Mapping[str, Any],
    dynamic: set[str],
    workspace: Any,
    context: AdapterContext,
) -> None:
    from .monetization_detail import validate_monetization_detail_request

    try:
        app = 1 if "/app" in dynamic else workspace.resolve_app(request.get("app"))
        date = "2026-01-01" if "/date" in dynamic else request.get("date")
        validate_monetization_detail_request(
            app,
            date,
            max_workers=1,
            max_pages=context.max_pages,
            max_items=context.max_items,
        )
    except (KeyError, TypeError, ValueError):
        raise input_error(
            "monetization_detail request is invalid", "request"
        ) from None


def _invalid_result(value: Any, context: AdapterContext) -> dict[str, Any]:
    from .monetization_detail import sanitize_monetization_detail_result

    app = value.get("app_id", "1") if isinstance(value, Mapping) else "1"
    date = value.get("date", "2026-01-01") if isinstance(value, Mapping) else "2026-01-01"
    try:
        return sanitize_monetization_detail_result(
            {}, app, date,
            max_workers=1, max_pages=context.max_pages, max_items=context.max_items,
        )
    except (TypeError, ValueError):
        return sanitize_monetization_detail_result(
            {}, "1", "2026-01-01",
            max_workers=1, max_pages=context.max_pages, max_items=context.max_items,
        )


__all__ = [
    "MONETIZATION_DETAIL_NAME",
    "execute_monetization_detail_plan",
    "is_monetization_detail_result",
    "project_monetization_detail_result",
    "validate_monetization_detail_plan",
]
