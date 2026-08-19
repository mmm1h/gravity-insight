"""Plan v1 adapter for the governed Analysis Dashboard snapshot.

The adapter deliberately owns only the Plan boundary.  Dashboard discovery,
source ordering, pagination, and partial-failure handling remain in the SDK
product.  This module prevents a Plan from widening that product's request,
concurrency, item budget, or returned top-level envelope.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from .dashboard_snapshot import MIN_SNAPSHOT_ITEMS, SCHEMA_VERSION
from .errors import ErrorCategory, ErrorCode, ErrorDetail, exit_code_for_category
from .plan import AdapterContext
from .plan_adapter_support import (
    has_dynamic,
    input_error,
    request_object,
    validate_exact_targets,
    validate_selected_fields,
)
from .actionable_error_values import actual_value


DASHBOARD_SNAPSHOT_NAME = "dashboard_snapshot"
DASHBOARD_SNAPSHOT_SOURCE_COUNT = 5
DASHBOARD_SNAPSHOT_MIN_ITEMS = MIN_SNAPSHOT_ITEMS
DASHBOARD_SNAPSHOT_REQUEST_FIELDS = frozenset({"name", "app", "ref"})
DASHBOARD_SNAPSHOT_OUTPUT_FIELDS = frozenset(
    {"app_id", "dashboard", "results", "scopes", "source_count"}
)

_DYNAMIC_TARGETS = frozenset({"/app", "/ref"})
_STRUCTURAL_FIELDS = frozenset(
    {
        "schema_version",
        "ok",
        "status",
        "exit_code",
        "total_count",
        "success_count",
        "failure_count",
        "next_action",
        "error",
    }
)
_SAFE_FIELDS = _STRUCTURAL_FIELDS | DASHBOARD_SNAPSHOT_OUTPUT_FIELDS


def validate_dashboard_snapshot_plan(
    request: Mapping[str, Any],
    context: AdapterContext,
    workspace: Any,
) -> None:
    """Preflight one Dashboard snapshot without making a remote read.

    Literal Apps are resolved exactly once against the Plan workspace.  A
    bound App cannot be resolved until execution, so its binding location is
    checked here and the post-binding Plan validation resolves it later.
    """

    request_object(
        request,
        DASHBOARD_SNAPSHOT_REQUEST_FIELDS,
        DASHBOARD_SNAPSHOT_NAME,
    )
    if request.get("name") != DASHBOARD_SNAPSHOT_NAME:
        raise input_error(
            f"actual value: {actual_value(request.get('name'))}; dashboard snapshot "
            "composite name is invalid; must match the documented composite name",
            "name",
        )

    validate_exact_targets(context, _DYNAMIC_TARGETS)
    if not has_dynamic(context, "/app"):
        if "app" not in request:
            raise input_error(f"actual value: {actual_value(request.get('app'))}; " + ("dashboard snapshot requires app"), "app")
        _resolve_literal_app(workspace, request["app"])
    if not has_dynamic(context, "/ref"):
        if "ref" not in request:
            raise input_error(f"actual value: {actual_value(request.get('ref'))}; " + ("dashboard snapshot requires ref"), "ref")
        _validate_reference(request["ref"])

    if context.max_items < DASHBOARD_SNAPSHOT_MIN_ITEMS:
        raise input_error(
            f"actual value: {actual_value((context.max_items, DASHBOARD_SNAPSHOT_MIN_ITEMS))}; "
            "dashboard snapshot fixed sources exceed this node max_items; must stay at or below "
            "this node max_items; raise limits.max_items",
            "limits.max_items",
        )
    validate_selected_fields(
        context.output_fields,
        DASHBOARD_SNAPSHOT_OUTPUT_FIELDS,
        "output_fields",
    )


def execute_dashboard_snapshot_plan(
    sdk: Any,
    request: Mapping[str, Any],
    context: AdapterContext,
) -> dict[str, Any]:
    """Execute through the public SDK facade with fixed inner concurrency.

    The Plan scheduler owns outer concurrency.  Keeping this composite's inner
    worker count at one prevents a ready layer from multiplying its network
    concurrency.  The request reference is never copied into the returned
    Plan value.
    """

    result = sdk.dashboard_snapshot(
        request.get("app"),
        request.get("ref"),
        max_workers=1,
        max_pages=context.max_pages,
        max_items=context.max_items,
        workspace=context.workspace,
    )
    return safe_dashboard_snapshot_envelope(result)


def project_dashboard_snapshot_result(
    result: Any,
    fields: tuple[str, ...],
    _context: AdapterContext,
) -> dict[str, Any]:
    """Apply adapter-owned output fields while retaining Plan structure."""

    validate_selected_fields(
        fields,
        DASHBOARD_SNAPSHOT_OUTPUT_FIELDS,
        "output_fields",
    )
    selected = safe_dashboard_snapshot_envelope(result)
    return {
        key: copy.deepcopy(value)
        for key, value in selected.items()
        if key in _STRUCTURAL_FIELDS or key in fields
    }


def is_dashboard_snapshot_result(result: Any) -> bool:
    """Return whether a result belongs to this composite contract."""

    return (
        isinstance(result, Mapping)
        and result.get("schema_version") == SCHEMA_VERSION
    )


def safe_dashboard_snapshot_envelope(result: Any) -> dict[str, Any]:
    """Return only the governed top-level Dashboard snapshot envelope.

    Product-owned nested result envelopes are retained verbatim because their
    own stable contracts and scrubbers govern those values.  Plan-only or
    caller-originated keys such as ``request``, ``ref``, and exception text are
    omitted by construction.
    """

    if not isinstance(result, Mapping):
        return _failure_envelope(
            ErrorDetail.create(
                "DASHBOARD_SNAPSHOT_RESULT_INVALID",
                "Dashboard snapshot returned an invalid Plan result.",
                category=ErrorCategory.LOCAL,
                next_action="Retry once; inspect the local Dashboard snapshot adapter if it repeats.",
            )
        )
    if result.get("schema_version") != SCHEMA_VERSION:
        return _failure_envelope(
            ErrorDetail.create(
                ErrorCode.CONTRACT_CHANGED,
                "Dashboard snapshot result contract changed.",
                next_action="Stop this Plan until the Dashboard snapshot contract is re-verified.",
            )
        )
    selected = {
        key: copy.deepcopy(value)
        for key, value in result.items()
        if key in _SAFE_FIELDS
    }
    if _native_failure(result):
        selected["ok"] = False
        selected["error"] = _aggregate_failure_detail(result).to_dict()
    else:
        selected.pop("error", None)
    return selected


def _native_failure(result: Mapping[str, Any]) -> bool:
    return result.get("ok") is False or str(result.get("status", "")).casefold() in {
        "error",
        "failed",
        "partial",
        "unavailable",
    }


def _aggregate_failure_detail(result: Mapping[str, Any]) -> ErrorDetail:
    """Summarize the highest-precedence source failure without its text."""

    candidates: list[tuple[int, int, Mapping[str, Any]]] = []
    rows = result.get("results")
    if isinstance(rows, list):
        for index, row in enumerate(rows):
            if not isinstance(row, Mapping) or row.get("ok") is True:
                continue
            error = row.get("error")
            if not isinstance(error, Mapping):
                continue
            category = _category(error.get("category"), result.get("exit_code"))
            candidates.append((_CATEGORY_EXIT[category], -index, error))

    if candidates:
        _rank, _order, source = max(candidates)
        category = _category(source.get("category"), result.get("exit_code"))
        code = source.get("code")
        field = source.get("field")
        retryable = source.get("retryable")
        retry_after_ms = source.get("retry_after_ms")
    else:
        source = {}
        category = _category(None, result.get("exit_code"))
        code = "DASHBOARD_SNAPSHOT_FAILED"
        field = retryable = retry_after_ms = None

    try:
        return ErrorDetail.create(
            code if isinstance(code, str) and code else "DASHBOARD_SNAPSHOT_FAILED",
            "Dashboard snapshot contains one or more failed sources.",
            category=category,
            field=field if isinstance(field, str) else None,
            retryable=retryable if isinstance(retryable, bool) else None,
            retry_after_ms=retry_after_ms if type(retry_after_ms) is int else None,
            next_action=_category_action(category),
        )
    except (TypeError, ValueError):
        return ErrorDetail.create(
            "DASHBOARD_SNAPSHOT_FAILED",
            "Dashboard snapshot contains one or more failed sources.",
            category=category,
            next_action=_category_action(category),
        )


_CATEGORY_EXIT = {
    category.value: exit_code_for_category(category) for category in ErrorCategory
}


def _category(value: Any, exit_code: Any) -> str:
    if value in _CATEGORY_EXIT:
        return str(value)
    for category in ErrorCategory:
        if exit_code == exit_code_for_category(category):
            return category.value
    return ErrorCategory.LOCAL.value


def _category_action(category: str) -> str:
    return {
        ErrorCategory.CALLER.value: "Correct the failed source input or permission, then retry.",
        ErrorCategory.UPSTREAM.value: "Retry the same Dashboard snapshot once.",
        ErrorCategory.LOCAL.value: "Inspect the local source code/category before retrying.",
    }[category]


def _failure_envelope(detail: ErrorDetail) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "ok": False,
        "status": "error",
        "exit_code": _CATEGORY_EXIT[detail.category],
        "error": detail.to_dict(),
    }


def _resolve_literal_app(workspace: Any, value: Any) -> None:
    """Prove a literal App belongs to the fixed Plan workspace.

    Workspace resolution is local configuration lookup.  Its selected numeric
    identity is intentionally discarded so neither the request nor a binding
    value is copied into the adapter result.
    """

    rendered = str(value).strip() if isinstance(value, (str, int)) and not isinstance(value, bool) else ""
    if not rendered or len(rendered) > 256:
        raise input_error(
            f"actual value: {actual_value(rendered)}; " + ("dashboard snapshot app must select a configured workspace App"),
            "app",
        )
    try:
        workspace.resolve_app(value)
    except (KeyError, TypeError, ValueError):
        raise input_error(
            f"actual value: {actual_value(value)}; " + ("dashboard snapshot app must select a configured workspace App"),
            "app",
        ) from None


def _validate_reference(value: Any) -> None:
    """Accept an explicit bounded dashboard id or exact display name."""

    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise input_error(
            f"actual value: {actual_value(value)}; " + ("dashboard snapshot ref must be an explicit id or exact name"),
            "ref",
        )
    rendered = str(value).strip()
    if not rendered or len(rendered) > 256:
        raise input_error(
            f"actual value: {actual_value(rendered)}; " + ("dashboard snapshot ref must be a bounded id or exact name"),
            "ref",
        )


__all__ = [
    "DASHBOARD_SNAPSHOT_NAME",
    "DASHBOARD_SNAPSHOT_MIN_ITEMS",
    "DASHBOARD_SNAPSHOT_OUTPUT_FIELDS",
    "DASHBOARD_SNAPSHOT_REQUEST_FIELDS",
    "DASHBOARD_SNAPSHOT_SOURCE_COUNT",
    "execute_dashboard_snapshot_plan",
    "is_dashboard_snapshot_result",
    "project_dashboard_snapshot_result",
    "safe_dashboard_snapshot_envelope",
    "validate_dashboard_snapshot_plan",
]
