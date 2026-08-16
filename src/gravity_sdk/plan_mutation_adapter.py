"""Narrow family router for governed mutation Plan adapters."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from . import plan_custom_metric_adapter as custom_metric
from . import plan_kanban_mutation_adapter as kanban
from .plan import AdapterContext


NAMES = frozenset({kanban.NAME, custom_metric.NAME})


def accepts(name: Any) -> bool:
    return name in NAMES


def validate_mutation_plan(request: Mapping[str, Any], context: AdapterContext) -> None:
    if request.get("name") == custom_metric.NAME:
        custom_metric.validate_custom_metric_plan(request, context)
        return
    kanban.validate_kanban_plan(request, context)


def execute_mutation_plan(
    sdk: Any, request: Mapping[str, Any], context: AdapterContext
) -> dict[str, Any]:
    if request.get("name") == custom_metric.NAME:
        return custom_metric.execute_custom_metric_plan(sdk, request, context)
    return kanban.execute_kanban_plan(sdk, request, context)


def is_mutation_result(value: Any) -> bool:
    return kanban.is_kanban_result(value) or custom_metric.is_custom_metric_result(value)


def project_mutation_result(
    result: Any, fields: tuple[str, ...], context: AdapterContext
) -> dict[str, Any]:
    if custom_metric.is_custom_metric_result(result):
        return custom_metric.project_custom_metric_result(result, fields, context)
    return kanban.project_kanban_result(result, fields, context)


__all__ = [
    "NAMES", "accepts", "execute_mutation_plan", "is_mutation_result",
    "project_mutation_result", "validate_mutation_plan",
]
