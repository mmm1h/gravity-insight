"""Plan v1 adapter for the governed single-user journey composite."""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from typing import Any

from .plan import AdapterContext
from .plan_adapter_support import (
    has_dynamic,
    input_error,
    request_object,
    validate_exact_targets,
    validate_selected_fields,
)
from .user_journey import SCHEMA_VERSION, user_journey, validate_user_journey_input


USER_JOURNEY_NAME = "user_journey"
USER_JOURNEY_REQUEST_FIELDS = frozenset(
    {
        "name",
        "app",
        "client_id",
        "date",
        "start",
        "end",
        "page",
        "page_size",
        "fields",
        "events",
    }
)
USER_JOURNEY_OUTPUT_FIELDS = frozenset(
    {"app_id", "continuation", "results", "scope", "source_count"}
)
_DYNAMIC_TARGETS = frozenset({"/app", "/client_id"})
_SAFE_ENVELOPE_FIELDS = frozenset(
    {
        "schema_version",
        "ok",
        "status",
        "exit_code",
        "total_count",
        "success_count",
        "failure_count",
        *USER_JOURNEY_OUTPUT_FIELDS,
        "next_action",
    }
)


def validate_user_journey_plan(
    request: Mapping[str, Any], context: AdapterContext, workspace: Any
) -> None:
    """Preflight literals and binding locations without issuing a client call."""

    request_object(request, USER_JOURNEY_REQUEST_FIELDS, USER_JOURNEY_NAME)
    if request.get("name") != USER_JOURNEY_NAME:
        raise input_error("user journey composite name is invalid", "name")
    validate_exact_targets(context, _DYNAMIC_TARGETS)
    dynamic_app = has_dynamic(context, "/app")
    dynamic_client = has_dynamic(context, "/client_id")
    if not dynamic_app and "app" not in request:
        raise input_error("user journey requires app", "app")
    if not dynamic_client and "client_id" not in request:
        raise input_error("user journey requires client_id", "client_id")
    try:
        app_id = 1 if dynamic_app else workspace.resolve_app(request.get("app"))
    except (KeyError, TypeError, ValueError):
        raise input_error(
            "user journey app must select a configured workspace App", "app"
        ) from None
    validate_user_journey_input(
        app_id,
        "plan-bound-client" if dynamic_client else request.get("client_id"),
        **_options(request),
        max_workers=1,
        max_items=context.max_items,
    )
    validate_selected_fields(
        context.output_fields, USER_JOURNEY_OUTPUT_FIELDS, "output_fields"
    )


def execute_user_journey_plan(
    sdk: Any, request: Mapping[str, Any], context: AdapterContext
) -> dict[str, Any]:
    """Bind the App once and return only the product's scrubbed envelope."""

    app_id = context.workspace.resolve_app(request.get("app"))
    result = user_journey(
        sdk.insight,
        app_id,
        request.get("client_id"),
        **_options(request),
        max_workers=1,
        max_items=context.max_items,
    )
    return safe_user_journey_envelope(result)


def project_user_journey_result(
    result: Any, fields: tuple[str, ...], _context: AdapterContext
) -> dict[str, Any]:
    selected = safe_user_journey_envelope(result)
    structural = _SAFE_ENVELOPE_FIELDS - USER_JOURNEY_OUTPUT_FIELDS
    return {
        key: copy.deepcopy(value)
        for key, value in selected.items()
        if key in structural or key in fields
    }


def is_user_journey_result(result: Any) -> bool:
    return isinstance(result, Mapping) and result.get("schema_version") == SCHEMA_VERSION


def safe_user_journey_envelope(result: Any) -> dict[str, Any]:
    if not isinstance(result, Mapping):
        raise input_error("user journey result is invalid", "result")
    return {
        key: copy.deepcopy(value)
        for key, value in result.items()
        if key in _SAFE_ENVELOPE_FIELDS
    }


def _options(request: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "date_value": request.get("date"),
        "start": request.get("start"),
        "end": request.get("end"),
        "page": request.get("page", 1),
        "page_size": request.get("page_size", 20),
        "fields": _array(request.get("fields", []), "fields"),
        "events": _array(request.get("events", []), "events"),
    }


def _array(value: Any, field: str) -> Sequence[str]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise input_error(f"user journey {field} must be an array", field)
    return value


__all__ = [
    "USER_JOURNEY_NAME",
    "USER_JOURNEY_OUTPUT_FIELDS",
    "USER_JOURNEY_REQUEST_FIELDS",
    "execute_user_journey_plan",
    "is_user_journey_result",
    "project_user_journey_result",
    "safe_user_journey_envelope",
    "validate_user_journey_plan",
]
