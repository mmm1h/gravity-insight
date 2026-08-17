"""Plan v1 boundary for deterministic Dashboard Analysis replay.

Only an App may be supplied by an upstream binding.  Dashboard identity,
mode, and the shared date window stay literal so preflight can prove the
artifact and budget shape before any Gravity request is made.  The product
owns Web-artifact translation, chart isolation, ordering, and query safety.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from datetime import date
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
from .actionable_error_values import actual_value


DASHBOARD_ANALYSIS_NAME = "dashboard_analysis"
DASHBOARD_ANALYSIS_MIN_ITEMS = 3
DASHBOARD_ANALYSIS_DEFAULT_MAX_CHARTS = 32
DASHBOARD_ANALYSIS_MAX_CHARTS = 64
DASHBOARD_ANALYSIS_REQUEST_FIELDS = frozenset(
    {"name", "app", "ref", "mode", "start", "end", "max_charts"}
)
DASHBOARD_ANALYSIS_OUTPUT_FIELDS = frozenset(
    {
        "app_id",
        "dashboard",
        "mode",
        "date_range",
        "charts",
        "chart_count",
        "supported_count",
        "unsupported_count",
        "success_count",
        "failure_count",
    }
)

_SCHEMA_VERSION = "gravity-insight.dashboard-analysis.v1"
_MODES = frozenset({"prepare", "run"})
_DYNAMIC_TARGETS = frozenset({"/app"})
_STRUCTURAL_FIELDS = frozenset(
    {
        "schema_version",
        "ok",
        "status",
        "exit_code",
        "total_count",
        "next_action",
        "error",
        "page_conditions",
    }
)
_CHART_FIELDS = frozenset(
    {
        "index",
        "report_id",
        "name",
        "subject",
        "kind",
        "operation_id",
        "supported",
        "query_executed",
        "validation_status",
        "live_metadata_dependencies",
        "date_override_applied",
        "limitations",
        "result",
        "error",
    }
)
_ERROR_FIELDS = frozenset(
    {
        "code",
        "category",
        "message",
        "field",
        "retryable",
        "retry_after_ms",
        "next_action",
    }
)
_PAGE_CONDITION_FIELDS = frozenset({
    "source_operation", "source_field", "present", "active",
    "condition_count", "application_status", "merge_semantics",
})


def validate_dashboard_analysis_plan(
    request: Mapping[str, Any],
    context: AdapterContext,
    workspace: Any,
) -> None:
    """Prove one replay shape and its fixed selectors without remote I/O."""

    request_object(
        request,
        DASHBOARD_ANALYSIS_REQUEST_FIELDS,
        DASHBOARD_ANALYSIS_NAME,
    )
    if request.get("name") != DASHBOARD_ANALYSIS_NAME:
        raise input_error("dashboard analysis composite name is invalid", "name")
    validate_exact_targets(context, _DYNAMIC_TARGETS)
    if not has_dynamic(context, "/app"):
        if "app" not in request:
            raise input_error(f"actual value: {actual_value(request.get('app'))}; " + ("dashboard analysis requires app"), "app")
        _resolve_literal_app(workspace, request["app"])

    _validate_reference(request.get("ref"))
    mode = request.get("mode", "run")
    if mode not in _MODES:
        raise input_error(f"actual value: {actual_value(mode)}; " + ("dashboard analysis mode must be prepare or run"), "mode")
    _validate_window(request.get("start"), request.get("end"))
    if context.max_items < DASHBOARD_ANALYSIS_MIN_ITEMS:
        raise input_error(
            "dashboard analysis needs room for a directory, dashboard, and chart",
            "limits.max_items",
        )
    _chart_budget(
        request.get("max_charts", DASHBOARD_ANALYSIS_DEFAULT_MAX_CHARTS),
        context.max_items,
    )
    validate_selected_fields(
        context.output_fields,
        DASHBOARD_ANALYSIS_OUTPUT_FIELDS,
        "output_fields",
    )


def execute_dashboard_analysis_plan(
    sdk: Any,
    request: Mapping[str, Any],
    context: AdapterContext,
) -> dict[str, Any]:
    """Run through the SDK using capacity borrowed from the Plan scheduler."""

    options = {
        "start": request["start"],
        "end": request["end"],
        "max_charts": _chart_budget(
            request.get("max_charts", DASHBOARD_ANALYSIS_DEFAULT_MAX_CHARTS),
            context.max_items,
        ),
        "max_items": context.max_items,
        "workspace": context.workspace,
    }
    if request.get("mode", "run") == "prepare":
        result = sdk.prepare_dashboard_analysis(
            request.get("app"),
            request.get("ref"),
            **options,
        )
    else:
        with context.borrow_workers(options["max_charts"]) as workers:
            result = sdk.run_dashboard_analysis(
                request.get("app"),
                request.get("ref"),
                max_workers=workers,
                **options,
            )
    return safe_dashboard_analysis_envelope(result)


def project_dashboard_analysis_result(
    result: Any,
    fields: tuple[str, ...],
    _context: AdapterContext,
) -> dict[str, Any]:
    """Crop only top-level product fields while retaining Plan structure."""

    validate_selected_fields(
        fields,
        DASHBOARD_ANALYSIS_OUTPUT_FIELDS,
        "output_fields",
    )
    selected = safe_dashboard_analysis_envelope(result)
    return {
        key: copy.deepcopy(value)
        for key, value in selected.items()
        if key in _STRUCTURAL_FIELDS or key in fields
    }


def is_dashboard_analysis_result(result: Any) -> bool:
    return isinstance(result, Mapping) and result.get("schema_version") == _SCHEMA_VERSION


def safe_dashboard_analysis_envelope(result: Any) -> dict[str, Any]:
    """Remove artifact inputs, opaque configs, requests, and exception spill."""

    if not isinstance(result, Mapping):
        return _failure(
            ErrorDetail.create(
                "DASHBOARD_ANALYSIS_RESULT_INVALID",
                "Dashboard analysis returned an invalid Plan result.",
                category=ErrorCategory.LOCAL,
                next_action="Retry once; inspect the local Dashboard analysis adapter if it repeats.",
            )
        )
    if result.get("schema_version") != _SCHEMA_VERSION:
        return _failure(
            ErrorDetail.create(
                ErrorCode.CONTRACT_CHANGED,
                "Dashboard analysis result contract changed.",
                next_action="Stop this Plan until the Dashboard analysis contract is re-verified.",
            )
        )
    selected = {
        key: copy.deepcopy(value)
        for key, value in result.items()
        if key in (_STRUCTURAL_FIELDS | DASHBOARD_ANALYSIS_OUTPUT_FIELDS) and key != "charts"
    }
    charts = result.get("charts")
    selected["charts"] = [
        _safe_chart(chart) for chart in charts if isinstance(chart, Mapping)
    ] if isinstance(charts, list) else []
    if isinstance(selected.get("error"), Mapping):
        page_gap = selected["error"].get("field") == "data.object.config.filter"
        selected["error"] = _safe_error(
            selected["error"],
            message="Dashboard analysis failed.",
            page_condition_gap=page_gap,
        )
    receipt = result.get("page_conditions")
    selected["page_conditions"] = {
        key: copy.deepcopy(value) for key, value in receipt.items()
        if key in _PAGE_CONDITION_FIELDS
    } if isinstance(receipt, Mapping) else {}
    return selected


def _safe_chart(chart: Mapping[str, Any]) -> dict[str, Any]:
    selected = {
        key: copy.deepcopy(value)
        for key, value in chart.items()
        if key in _CHART_FIELDS and key != "error"
    }
    if isinstance(chart.get("error"), Mapping):
        selected["error"] = _safe_error(
            chart["error"],
            message="Dashboard chart could not be compiled or executed.",
        )
    return selected


def _safe_error(
    error: Mapping[str, Any], *, message: str, page_condition_gap: bool = False
) -> dict[str, Any]:
    selected = {
        key: copy.deepcopy(value)
        for key, value in error.items()
        if key in (_ERROR_FIELDS - {"message", "next_action"})
    }
    selected["message"] = message
    selected["next_action"] = (
        "Capture one controlled Web query with conflicting page and chart "
        "conditions, then prove the upstream conflict rule before retrying."
        if page_condition_gap else
        "Inspect the chart status and correct its governed input before retrying."
    )
    return selected


def _chart_budget(value: Any, max_items: int) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 1 <= value <= DASHBOARD_ANALYSIS_MAX_CHARTS
    ):
        raise input_error(
            f"actual value: {actual_value(value)}; " + (f"dashboard analysis max_charts must be between 1 and {DASHBOARD_ANALYSIS_MAX_CHARTS}"),
            "max_charts",
        )
    return min(value, max_items - 2)


def _validate_window(start: Any, end: Any) -> None:
    if not isinstance(start, str) or not isinstance(end, str):
        raise input_error(f"actual value: {actual_value((start, end))}; " + ("dashboard analysis requires literal start and end"), "start/end")
    try:
        start_day, end_day = date.fromisoformat(start), date.fromisoformat(end)
    except (TypeError, ValueError):
        raise input_error(
            f"actual value: {actual_value((start, end))}; " + ("dashboard analysis start and end must be ISO dates"),
            "start/end",
        ) from None
    if start_day > end_day or (end_day - start_day).days > 90:
        raise input_error(
            f"actual value: {actual_value((start, end))}; " + ("dashboard analysis inclusive date window must not exceed 90 days"),
            "start/end",
        )


def _resolve_literal_app(workspace: Any, value: Any) -> None:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise input_error(f"actual value: {actual_value(value)}; " + ("dashboard analysis app must select a workspace App"), "app")
    try:
        workspace.resolve_app(value)
    except (KeyError, TypeError, ValueError):
        raise input_error(f"actual value: {actual_value(value)}; " + ("dashboard analysis app must select a workspace App"), "app") from None


def _validate_reference(value: Any) -> None:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise input_error(f"actual value: {actual_value(value)}; " + ("dashboard analysis ref must be an explicit id or exact name"), "ref")
    rendered = str(value).strip()
    if not rendered or len(rendered) > 256:
        raise input_error(f"actual value: {actual_value(rendered)}; " + ("dashboard analysis ref must be a bounded id or exact name"), "ref")


def _failure(detail: ErrorDetail) -> dict[str, Any]:
    return {
        "schema_version": _SCHEMA_VERSION,
        "ok": False,
        "status": "error",
        "exit_code": exit_code_for_error(detail),
        "error": detail.to_dict(),
    }


__all__ = [
    "DASHBOARD_ANALYSIS_DEFAULT_MAX_CHARTS",
    "DASHBOARD_ANALYSIS_MAX_CHARTS",
    "DASHBOARD_ANALYSIS_MIN_ITEMS",
    "DASHBOARD_ANALYSIS_NAME",
    "DASHBOARD_ANALYSIS_OUTPUT_FIELDS",
    "DASHBOARD_ANALYSIS_REQUEST_FIELDS",
    "execute_dashboard_analysis_plan",
    "is_dashboard_analysis_result",
    "project_dashboard_analysis_result",
    "safe_dashboard_analysis_envelope",
    "validate_dashboard_analysis_plan",
]
