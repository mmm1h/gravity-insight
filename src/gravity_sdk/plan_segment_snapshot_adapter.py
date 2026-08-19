"""Plan v1 boundary for one governed aggregate Segment snapshot."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from datetime import date as date_type
from typing import Any

from .errors import ErrorCategory, ErrorCode, ErrorDetail, exit_code_for_category
from .plan import AdapterContext
from .plan_adapter_support import (
    has_dynamic,
    input_error,
    request_object,
    validate_exact_targets,
    validate_selected_fields,
)
from .segment_snapshot import MIN_SNAPSHOT_ITEMS, SCHEMA_VERSION
from .actionable_error_values import actual_value


SEGMENT_SNAPSHOT_NAME = "segment_snapshot"
SEGMENT_SNAPSHOT_REQUEST_FIELDS = frozenset({"name", "app", "ref", "date"})
SEGMENT_SNAPSHOT_OUTPUT_FIELDS = frozenset(
    {"app_id", "segment", "date", "results", "scopes", "source_count"}
)
_DYNAMIC_TARGETS = frozenset({"/app"})
_STRUCTURAL_FIELDS = frozenset(
    {
        "schema_version", "ok", "status", "exit_code", "total_count",
        "success_count", "failure_count", "next_action", "error",
    }
)
_SAFE_FIELDS = _STRUCTURAL_FIELDS | SEGMENT_SNAPSHOT_OUTPUT_FIELDS
_CATEGORY_EXIT = {
    category.value: exit_code_for_category(category) for category in ErrorCategory
}


def validate_segment_snapshot_plan(
    request: Mapping[str, Any], context: AdapterContext, workspace: Any
) -> None:
    """Validate literal identity/date and aggregate limits without client access."""

    request_object(request, SEGMENT_SNAPSHOT_REQUEST_FIELDS, SEGMENT_SNAPSHOT_NAME)
    if request.get("name") != SEGMENT_SNAPSHOT_NAME:
        raise input_error(
            f"actual value: {actual_value(request.get('name'))}; segment snapshot composite "
            "name is invalid; must match the documented composite name",
            "name",
        )
    validate_exact_targets(context, _DYNAMIC_TARGETS)
    if not has_dynamic(context, "/app"):
        if "app" not in request:
            raise input_error(f"actual value: {actual_value(request.get('app'))}; " + ("segment snapshot requires app"), "app")
        _resolve_app(workspace, request["app"])
    _bounded_ref(request.get("ref"))
    _canonical_date(request.get("date"))
    if context.max_items < MIN_SNAPSHOT_ITEMS:
        raise input_error(
            f"actual value: {actual_value((context.max_items, MIN_SNAPSHOT_ITEMS))}; segment "
            "snapshot fixed structure exceeds this node max_items; must stay at or below this "
            "node max_items; raise limits.max_items",
            "limits.max_items",
        )
    validate_selected_fields(
        context.output_fields, SEGMENT_SNAPSHOT_OUTPUT_FIELDS, "output_fields"
    )


def execute_segment_snapshot_plan(
    sdk: Any, request: Mapping[str, Any], context: AdapterContext
) -> dict[str, Any]:
    """Delegate to the SDK with one inner worker under the global Plan pool."""

    result = sdk.segment_snapshot(
        request.get("app"),
        request.get("ref"),
        date=request.get("date"),
        max_workers=1,
        max_pages=context.max_pages,
        max_items=context.max_items,
        workspace=context.workspace,
    )
    return safe_segment_snapshot_envelope(result)


def project_segment_snapshot_result(
    result: Any, fields: tuple[str, ...], _context: AdapterContext
) -> dict[str, Any]:
    validate_selected_fields(fields, SEGMENT_SNAPSHOT_OUTPUT_FIELDS, "output_fields")
    selected = safe_segment_snapshot_envelope(result)
    return {
        key: copy.deepcopy(value)
        for key, value in selected.items()
        if key in _STRUCTURAL_FIELDS or key in fields
    }


def is_segment_snapshot_result(result: Any) -> bool:
    return isinstance(result, Mapping) and result.get("schema_version") == SCHEMA_VERSION


def safe_segment_snapshot_envelope(result: Any) -> dict[str, Any]:
    """Whitelist the product envelope and synthesize one safe Plan error."""

    if not isinstance(result, Mapping):
        return _failure(
            ErrorDetail.create(
                "SEGMENT_SNAPSHOT_RESULT_INVALID",
                "Segment snapshot returned an invalid Plan result.",
                category=ErrorCategory.LOCAL,
            )
        )
    if result.get("schema_version") != SCHEMA_VERSION:
        return _failure(
            ErrorDetail.create(
                ErrorCode.CONTRACT_CHANGED,
                "Segment snapshot result contract changed.",
            )
        )
    selected = {
        key: copy.deepcopy(value) for key, value in result.items() if key in _SAFE_FIELDS
    }
    safe_results = _safe_results(result.get("results"))
    if safe_results is None:
        return _failure(
            ErrorDetail.create(
                ErrorCode.CONTRACT_CHANGED,
                "Segment snapshot result sources changed.",
            )
        )
    selected["results"] = safe_results
    if _native_failure(result):
        selected["ok"] = False
        selected["error"] = _aggregate_error(result).to_dict()
    else:
        selected.pop("error", None)
    return selected


def _safe_results(value: Any) -> list[dict[str, Any]] | None:
    if not isinstance(value, list) or len(value) != 3:
        return None
    rows: list[dict[str, Any]] = []
    for expected, raw in zip(("detail", "history", "daily_result"), value, strict=True):
        if not isinstance(raw, Mapping):
            return None
        if raw.get("source") != expected or not isinstance(raw.get("ok"), bool):
            return None
        row = {
            key: copy.deepcopy(raw[key])
            for key in (
                "operation_id", "ok", "status", "data", "source", "scope",
                "continuation",
            )
            if key in raw
        }
        if raw.get("ok") is not True:
            row["data"] = None
            error = raw.get("error") if isinstance(raw.get("error"), Mapping) else {}
            category = _category(error.get("category"), None)
            code = error.get("code") if isinstance(error.get("code"), str) else None
            try:
                row["error"] = ErrorDetail.create(
                    code or "SEGMENT_SNAPSHOT_SOURCE_FAILED",
                    "Segment snapshot source failed.",
                    category=category,
                    field=error.get("field") if isinstance(error.get("field"), str) else None,
                    next_action=_next_action(category),
                ).to_dict()
            except (TypeError, ValueError):
                row["error"] = ErrorDetail.create(
                    "SEGMENT_SNAPSHOT_SOURCE_FAILED",
                    "Segment snapshot source failed.",
                    category=category,
                    next_action=_next_action(category),
                ).to_dict()
        rows.append(row)
    return rows


def _native_failure(result: Mapping[str, Any]) -> bool:
    return result.get("ok") is False or str(result.get("status", "")).casefold() in {
        "error", "failed", "partial", "unavailable",
    }


def _aggregate_error(result: Mapping[str, Any]) -> ErrorDetail:
    candidates: list[tuple[int, int, Mapping[str, Any]]] = []
    rows = result.get("results")
    if isinstance(rows, list):
        for index, row in enumerate(rows):
            if not isinstance(row, Mapping) or row.get("ok") is True:
                continue
            error = row.get("error")
            if isinstance(error, Mapping):
                category = _category(error.get("category"), result.get("exit_code"))
                candidates.append((_CATEGORY_EXIT[category], -index, error))
    if candidates:
        _, _, source = max(candidates)
        category = _category(source.get("category"), result.get("exit_code"))
        code = source.get("code") if isinstance(source.get("code"), str) else None
        field = source.get("field") if isinstance(source.get("field"), str) else None
        retry_after = source.get("retry_after_ms")
    else:
        category = _category(None, result.get("exit_code"))
        code = field = None
        retry_after = None
    try:
        return ErrorDetail.create(
            code or "SEGMENT_SNAPSHOT_FAILED",
            "Segment snapshot contains one or more failed sources.",
            category=category,
            field=field,
            retry_after_ms=retry_after if type(retry_after) is int else None,
            next_action=_next_action(category),
        )
    except (TypeError, ValueError):
        return ErrorDetail.create(
            "SEGMENT_SNAPSHOT_FAILED",
            "Segment snapshot contains one or more failed sources.",
            category=category,
            next_action=_next_action(category),
        )


def _category(value: Any, exit_code: Any) -> str:
    if value in _CATEGORY_EXIT:
        return str(value)
    for category in ErrorCategory:
        if exit_code == exit_code_for_category(category):
            return category.value
    return ErrorCategory.LOCAL.value


def _next_action(category: str) -> str:
    return {
        "caller": "Correct the selected Segment snapshot input, then retry.",
        "upstream": "Retry the same Segment snapshot once.",
        "local": "Inspect the local source code/category before retrying.",
    }[category]


def _failure(detail: ErrorDetail) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "ok": False,
        "status": "error",
        "exit_code": _CATEGORY_EXIT[detail.category],
        "error": detail.to_dict(),
    }


def _resolve_app(workspace: Any, value: Any) -> None:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise input_error(
            f"actual value: {actual_value(value)}; " + ("segment snapshot app must select a configured workspace App"), "app"
        )
    rendered = str(value).strip()
    if not rendered or len(rendered) > 256:
        raise input_error(
            f"actual value: {actual_value(rendered)}; " + ("segment snapshot app must select a configured workspace App"), "app"
        )
    try:
        workspace.resolve_app(value)
    except (KeyError, TypeError, ValueError):
        raise input_error(
            f"actual value: {actual_value(value)}; " + ("segment snapshot app must select a configured workspace App"), "app"
        ) from None


def _bounded_ref(value: Any) -> None:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise input_error(f"actual value: {actual_value(value)}; " + ("segment snapshot ref must be an exact id or name"), "ref")
    rendered = str(value).strip()
    if not rendered or len(rendered) > 256:
        raise input_error(f"actual value: {actual_value(rendered)}; " + ("segment snapshot ref must be a bounded id or name"), "ref")


def _canonical_date(value: Any) -> None:
    if not isinstance(value, str):
        raise input_error(f"actual value: {actual_value(value)}; " + ("segment snapshot date must be YYYY-MM-DD"), "date")
    try:
        parsed = date_type.fromisoformat(value)
    except ValueError:
        raise input_error(f"actual value: {actual_value(value)}; " + ("segment snapshot date must be YYYY-MM-DD"), "date") from None
    if parsed.isoformat() != value:
        raise input_error(f"actual value: {actual_value(value)}; " + ("segment snapshot date must be canonical YYYY-MM-DD"), "date")


__all__ = [
    "SEGMENT_SNAPSHOT_NAME",
    "SEGMENT_SNAPSHOT_OUTPUT_FIELDS",
    "SEGMENT_SNAPSHOT_REQUEST_FIELDS",
    "execute_segment_snapshot_plan",
    "is_segment_snapshot_result",
    "project_segment_snapshot_result",
    "safe_segment_snapshot_envelope",
    "validate_segment_snapshot_plan",
]
