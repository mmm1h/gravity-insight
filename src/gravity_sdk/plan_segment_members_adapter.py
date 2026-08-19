"""Plan v1 boundary for complete Segment member rows."""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from typing import Any

from .errors import ErrorCategory, ErrorCode, ErrorDetail, exit_code_for_error
from .plan import AdapterContext
from .plan_adapter_support import (
    has_dynamic,
    input_error,
    request_object,
    validate_exact_targets,
    validate_selected_fields,
)
from .segment_members import SCHEMA_VERSION, validate_segment_members_request
from .actionable_error_values import actual_value


SEGMENT_MEMBERS_NAME = "segment_members"
SEGMENT_MEMBERS_REQUEST_FIELDS = frozenset(
    {"name", "app", "ref", "fields", "segment_version_id"}
)
SEGMENT_MEMBERS_OUTPUT_FIELDS = frozenset(
    {
        "operation_id", "app_id", "segment", "segment_version_id", "fields",
        "returned_items", "total_items", "complete", "limits", "data",
    }
)
_STRUCTURAL_FIELDS = frozenset(
    {"schema_version", "ok", "status", "exit_code", "error", "next_action"}
)
_SAFE_FIELDS = _STRUCTURAL_FIELDS | SEGMENT_MEMBERS_OUTPUT_FIELDS


def validate_segment_members_plan(
    request: Mapping[str, Any], context: AdapterContext, workspace: Any
) -> None:
    request_object(request, SEGMENT_MEMBERS_REQUEST_FIELDS, SEGMENT_MEMBERS_NAME)
    if request.get("name") != SEGMENT_MEMBERS_NAME:
        raise input_error(
            f"actual value: {actual_value(request.get('name'))}; segment members composite "
            "name is invalid; must match the documented composite name",
            "name",
        )
    validate_exact_targets(context, frozenset({"/app"}))
    app_id: str | int = "1"
    if not has_dynamic(context, "/app"):
        if "app" not in request:
            raise input_error(f"actual value: {actual_value(request.get('app'))}; " + ("segment members requires app"), "app")
        try:
            app_id = workspace.resolve_app(request["app"])
        except (KeyError, TypeError, ValueError):
            raise input_error(
                f"actual value: {actual_value(request.get('app'))}; " + ("segment members app must select a configured workspace App"), "app"
            ) from None
    try:
        validate_segment_members_request(
            app_id,
            request.get("ref"),
            fields=_request_fields(request.get("fields")),
            segment_version_id=request.get("segment_version_id"),
            max_workers=1,
            max_pages=context.max_pages,
            max_items=context.max_items,
        )
    except Exception as exc:
        raise input_error(("must correct: " + str(str(exc))), getattr(exc, "field", None) or "request") from None
    validate_selected_fields(
        context.output_fields, SEGMENT_MEMBERS_OUTPUT_FIELDS, "output_fields"
    )


def execute_segment_members_plan(
    sdk: Any, request: Mapping[str, Any], context: AdapterContext
) -> dict[str, Any]:
    result = sdk.segment_members(
        request.get("app"),
        request.get("ref"),
        fields=_request_fields(request.get("fields")),
        segment_version_id=request.get("segment_version_id"),
        max_workers=1,
        max_pages=context.max_pages,
        max_items=context.max_items,
        workspace=context.workspace,
    )
    return safe_segment_members_envelope(result)


def project_segment_members_result(
    result: Any, fields: tuple[str, ...], _context: AdapterContext
) -> dict[str, Any]:
    validate_selected_fields(fields, SEGMENT_MEMBERS_OUTPUT_FIELDS, "output_fields")
    selected = safe_segment_members_envelope(result)
    return {
        key: copy.deepcopy(value)
        for key, value in selected.items()
        if key in _STRUCTURAL_FIELDS or key in fields
    }


def safe_segment_members_envelope(result: Any) -> dict[str, Any]:
    if not isinstance(result, Mapping) or result.get("schema_version") != SCHEMA_VERSION:
        detail = ErrorDetail.create(
            ErrorCode.CONTRACT_CHANGED,
            "Segment members result contract changed.",
            category=ErrorCategory.UPSTREAM,
        )
        return {
            "schema_version": SCHEMA_VERSION,
            "ok": False,
            "status": "contract_changed",
            "exit_code": exit_code_for_error(detail),
            "error": detail.to_dict(),
            "next_action": "Refresh the registered response shape, then retry.",
        }
    return {
        key: copy.deepcopy(value) for key, value in result.items() if key in _SAFE_FIELDS
    }


def is_segment_members_result(result: Any) -> bool:
    return isinstance(result, Mapping) and result.get("schema_version") == SCHEMA_VERSION


def _request_fields(value: Any) -> tuple[str, ...]:
    if value in (None, (), []):
        return ()
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return tuple(value)
    raise input_error(f"actual value: {actual_value(value)}; " + ("segment members fields must be a list"), "fields")


__all__ = [
    "SEGMENT_MEMBERS_NAME",
    "SEGMENT_MEMBERS_OUTPUT_FIELDS",
    "SEGMENT_MEMBERS_REQUEST_FIELDS",
    "execute_segment_members_plan",
    "is_segment_members_result",
    "project_segment_members_result",
    "safe_segment_members_envelope",
    "validate_segment_members_plan",
]
