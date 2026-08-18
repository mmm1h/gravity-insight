"""Plan v1 boundary for the realtime-event catalog."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from .errors import ErrorCode, ErrorDetail, exit_code_for_error
from .plan import AdapterContext
from .plan_adapter_support import (
    has_dynamic,
    request_object,
    validate_exact_targets,
    validate_selected_fields,
)
from .realtime_event_catalog import SCHEMA_VERSION
from .result_source import GOVERNED_PRODUCT, result_source
from .workspace_app import resolve_workspace_app


REALTIME_EVENT_CATALOG_NAME = "realtime_event_catalog"
REQUEST_FIELDS = frozenset({"name", "app", "start", "end", "event_type"})
OUTPUT_FIELDS = frozenset(
    {
        "operation_id",
        "app_id",
        "start",
        "end",
        "event_type",
        "item_count",
        "data",
    }
)
_STRUCTURAL_FIELDS = frozenset(
    {
        "schema_version",
        "result_source",
        "ok",
        "status",
        "exit_code",
        "error",
        "result_audit",
    }
)
_SAFE_FIELDS = _STRUCTURAL_FIELDS | OUTPUT_FIELDS


def validate_realtime_event_catalog_plan(
    request: Mapping[str, Any], context: AdapterContext, workspace: Any
) -> None:
    request_object(request, REQUEST_FIELDS, REALTIME_EVENT_CATALOG_NAME)
    validate_exact_targets(context, frozenset({"/app"}))
    if not has_dynamic(context, "/app"):
        resolve_workspace_app(workspace, request.get("app"))
    validate_selected_fields(context.output_fields, OUTPUT_FIELDS, "output_fields")


def execute_realtime_event_catalog_plan(
    sdk: Any, request: Mapping[str, Any], context: AdapterContext
) -> dict[str, Any]:
    return safe_realtime_event_catalog_envelope(
        sdk.realtime_event_catalog(
            request.get("app"),
            start=request.get("start"),
            end=request.get("end"),
            event_type=request.get("event_type", "profile"),
            workspace=context.workspace,
        )
    )


def project_realtime_event_catalog_result(
    result: Any, fields: tuple[str, ...], _context: AdapterContext
) -> dict[str, Any]:
    validate_selected_fields(fields, OUTPUT_FIELDS, "output_fields")
    selected = safe_realtime_event_catalog_envelope(result)
    return {
        key: copy.deepcopy(value)
        for key, value in selected.items()
        if key in _STRUCTURAL_FIELDS or key in fields
    }


def safe_realtime_event_catalog_envelope(result: Any) -> dict[str, Any]:
    if not isinstance(result, Mapping) or result.get("schema_version") != SCHEMA_VERSION:
        detail = ErrorDetail.create(
            ErrorCode.CONTRACT_CHANGED,
            "Realtime-event catalog result contract changed.",
        )
        return {
            "schema_version": SCHEMA_VERSION,
            "result_source": result_source(GOVERNED_PRODUCT),
            "ok": False,
            "status": "contract_changed",
            "exit_code": exit_code_for_error(detail),
            "error": detail.to_dict(),
        }
    return {
        key: copy.deepcopy(value) for key, value in result.items() if key in _SAFE_FIELDS
    }


def is_realtime_event_catalog_result(result: Any) -> bool:
    return isinstance(result, Mapping) and result.get("schema_version") == SCHEMA_VERSION


__all__ = [
    "OUTPUT_FIELDS",
    "REALTIME_EVENT_CATALOG_NAME",
    "execute_realtime_event_catalog_plan",
    "is_realtime_event_catalog_result",
    "project_realtime_event_catalog_result",
    "safe_realtime_event_catalog_envelope",
    "validate_realtime_event_catalog_plan",
]
