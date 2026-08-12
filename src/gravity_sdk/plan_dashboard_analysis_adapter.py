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

from .errors import ErrorCategory, ErrorCode, ErrorDetail
from .plan import AdapterContext
from .plan_adapter_support import (
    has_dynamic,
    input_error,
    request_object,
    validate_exact_targets,
    validate_selected_fields,
)


DASHBOARD_ANALYSIS_NAME = "dashboard_analysis"
DASHBOARD_ANALYSIS_MIN_ITEMS = 3
DASHBOARD_ANALYSIS_DEFAULT_MAX_CHARTS = 32
DASHBOARD_ANALYSIS_REQUEST_FIELDS = frozenset(
    {"name", "app", "ref", "mode", "start", "end"}
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
            raise input_error("dashboard analysis requires app", "app")
        _resolve_literal_app(workspace, request["app"])

    _validate_reference(request.get("ref"))
    mode = request.get("mode", "run")
    if mode not in _MODES:
        raise input_error("dashboard analysis mode must be prepare or run", "mode")
    _validate_window(request.get("start"), request.get("end"))
    if context.max_items < DASHBOARD_ANALYSIS_MIN_ITEMS:
        raise input_error(
            "dashboard analysis needs room for a directory, dashboard, and chart",
            "limits.max_items",
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
    """Run through the SDK while preventing scheduler concurrency multiplication."""

    options = {
        "start": request["start"],
        "end": request["end"],
        "max_charts": _chart_budget(context.max_items),
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
        result = sdk.run_dashboard_analysis(
            request.get("app"),
            request.get("ref"),
            max_workers=1,
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
        selected["error"] = _safe_error(
            selected["error"],
            message="Dashboard analysis failed.",
        )
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


def _safe_error(error: Mapping[str, Any], *, message: str) -> dict[str, Any]:
    selected = {
        key: copy.deepcopy(value)
        for key, value in error.items()
        if key in (_ERROR_FIELDS - {"message", "next_action"})
    }
    selected["message"] = message
    selected["next_action"] = "Inspect the chart status and correct its governed input before retrying."
    return selected


def _chart_budget(max_items: int) -> int:
    return min(DASHBOARD_ANALYSIS_DEFAULT_MAX_CHARTS, max_items - 2)


def _validate_window(start: Any, end: Any) -> None:
    if not isinstance(start, str) or not isinstance(end, str):
        raise input_error("dashboard analysis requires literal start and end", "start/end")
    try:
        start_day, end_day = date.fromisoformat(start), date.fromisoformat(end)
    except (TypeError, ValueError):
        raise input_error(
            "dashboard analysis start and end must be ISO dates",
            "start/end",
        ) from None
    if start_day > end_day or (end_day - start_day).days > 90:
        raise input_error(
            "dashboard analysis inclusive date window must not exceed 90 days",
            "start/end",
        )


def _resolve_literal_app(workspace: Any, value: Any) -> None:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise input_error("dashboard analysis app must select a workspace App", "app")
    try:
        workspace.resolve_app(value)
    except (KeyError, TypeError, ValueError):
        raise input_error("dashboard analysis app must select a workspace App", "app") from None


def _validate_reference(value: Any) -> None:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise input_error("dashboard analysis ref must be an explicit id or exact name", "ref")
    rendered = str(value).strip()
    if not rendered or len(rendered) > 256:
        raise input_error("dashboard analysis ref must be a bounded id or exact name", "ref")


def _failure(detail: ErrorDetail) -> dict[str, Any]:
    return {
        "schema_version": _SCHEMA_VERSION,
        "ok": False,
        "status": "error",
        "exit_code": {"caller": 2, "upstream": 3, "local": 4}[detail.category],
        "error": detail.to_dict(),
    }


__all__ = [
    "DASHBOARD_ANALYSIS_DEFAULT_MAX_CHARTS",
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
