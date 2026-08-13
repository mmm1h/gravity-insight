"""Thin Plan router for governed order products."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from . import plan_order_directory_adapter as directory_plan
from . import plan_order_trace_adapter as trace_plan
from .plan import AdapterContext


_NAMES = frozenset(
    {directory_plan.ORDER_DIRECTORY_NAME, trace_plan.ORDER_SPLIT_TRACE_NAME}
)
_TRACE_SCHEMA = "gravity-insight.order-split-trace.v1"
_DIRECTORY_SCHEMA = "gravity-insight.order-directory.v1"


def is_order_composite(value: Any) -> bool:
    return isinstance(value, str) and value in _NAMES


def validate_order_plan(
    request: Mapping[str, Any], context: AdapterContext, workspace: Any
) -> None:
    if request.get("name") == directory_plan.ORDER_DIRECTORY_NAME:
        directory_plan.validate_order_directory_plan(request, context, workspace)
        return
    trace_plan.validate_order_split_trace_plan(request, context, workspace)


def execute_order_plan(
    sdk: Any, request: Mapping[str, Any], context: AdapterContext
) -> dict[str, Any]:
    if request.get("name") == directory_plan.ORDER_DIRECTORY_NAME:
        return directory_plan.execute_order_directory_plan(sdk, request, context)
    return trace_plan.execute_order_split_trace_plan(sdk, request, context)


def is_order_result(value: Any) -> bool:
    return isinstance(value, Mapping) and value.get("schema_version") in {
        _TRACE_SCHEMA, _DIRECTORY_SCHEMA,
    }


def project_order_result(
    value: Any, fields: tuple[str, ...], context: AdapterContext
) -> dict[str, Any]:
    if isinstance(value, Mapping) and value.get(
        "schema_version"
    ) == _TRACE_SCHEMA:
        return trace_plan.project_order_split_trace_result(value, fields, context)
    return directory_plan.project_order_directory_result(value, fields, context)


__all__ = [
    "execute_order_plan",
    "is_order_composite",
    "is_order_result",
    "project_order_result",
    "validate_order_plan",
]
