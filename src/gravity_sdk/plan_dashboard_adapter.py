"""One Plan routing seam for Dashboard control and chart composites."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .plan import AdapterContext
from . import plan_dashboard_analysis_adapter as analysis
from . import plan_dashboard_snapshot_adapter as snapshot


COMPOSITE_NAMES = frozenset(
    {snapshot.DASHBOARD_SNAPSHOT_NAME, analysis.DASHBOARD_ANALYSIS_NAME}
)


def is_dashboard_composite(name: Any) -> bool:
    return name in COMPOSITE_NAMES


def validate_dashboard_plan(
    request: Mapping[str, Any], context: AdapterContext, workspace: Any
) -> None:
    if request.get("name") == analysis.DASHBOARD_ANALYSIS_NAME:
        analysis.validate_dashboard_analysis_plan(request, context, workspace)
    else:
        snapshot.validate_dashboard_snapshot_plan(request, context, workspace)


def execute_dashboard_plan(
    sdk: Any, request: Mapping[str, Any], context: AdapterContext
) -> dict[str, Any]:
    if request.get("name") == analysis.DASHBOARD_ANALYSIS_NAME:
        return analysis.execute_dashboard_analysis_plan(sdk, request, context)
    return snapshot.execute_dashboard_snapshot_plan(sdk, request, context)


def is_dashboard_result(result: Any) -> bool:
    return analysis.is_dashboard_analysis_result(
        result
    ) or snapshot.is_dashboard_snapshot_result(result)


def project_dashboard_result(
    result: Any, fields: tuple[str, ...], context: AdapterContext
) -> dict[str, Any]:
    if analysis.is_dashboard_analysis_result(result):
        return analysis.project_dashboard_analysis_result(result, fields, context)
    return snapshot.project_dashboard_snapshot_result(result, fields, context)


__all__ = [
    "COMPOSITE_NAMES",
    "execute_dashboard_plan",
    "is_dashboard_composite",
    "is_dashboard_result",
    "project_dashboard_result",
    "validate_dashboard_plan",
]
