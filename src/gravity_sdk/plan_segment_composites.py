"""One Plan routing seam for Segment evaluation and inspection products."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .plan import AdapterContext
from . import plan_segment_adapter as evaluate
from . import plan_segment_snapshot_adapter as snapshot
from . import plan_segment_members_adapter as members


COMPOSITE_NAMES = frozenset(
    {
        evaluate.SEGMENT_EVALUATE_NAME,
        snapshot.SEGMENT_SNAPSHOT_NAME,
        members.SEGMENT_MEMBERS_NAME,
    }
)


def is_segment_composite(name: Any) -> bool:
    return name in COMPOSITE_NAMES


def validate_segment_composite(
    insight: Any,
    workspace: Any,
    request: Mapping[str, Any],
    context: AdapterContext,
) -> None:
    if request.get("name") == snapshot.SEGMENT_SNAPSHOT_NAME:
        snapshot.validate_segment_snapshot_plan(request, context, workspace)
    elif request.get("name") == members.SEGMENT_MEMBERS_NAME:
        members.validate_segment_members_plan(request, context, workspace)
    else:
        evaluate.validate_segment_evaluate_plan(
            insight, workspace, request, context
        )


def execute_segment_composite(
    sdk: Any, request: Mapping[str, Any], context: AdapterContext
) -> dict[str, Any]:
    if request.get("name") == snapshot.SEGMENT_SNAPSHOT_NAME:
        return snapshot.execute_segment_snapshot_plan(sdk, request, context)
    if request.get("name") == members.SEGMENT_MEMBERS_NAME:
        return members.execute_segment_members_plan(sdk, request, context)
    return evaluate.execute_segment_evaluate_plan(sdk, request, context)


def is_segment_result(result: Any) -> bool:
    return evaluate.is_segment_evaluate_result(
        result
    ) or snapshot.is_segment_snapshot_result(result) or members.is_segment_members_result(result)


def project_segment_result(
    result: Any, fields: tuple[str, ...], context: AdapterContext
) -> dict[str, Any]:
    if snapshot.is_segment_snapshot_result(result):
        return snapshot.project_segment_snapshot_result(result, fields, context)
    if members.is_segment_members_result(result):
        return members.project_segment_members_result(result, fields, context)
    return evaluate.project_segment_evaluate_result(result, fields, context)


__all__ = [
    "COMPOSITE_NAMES",
    "execute_segment_composite",
    "is_segment_composite",
    "is_segment_result",
    "project_segment_result",
    "validate_segment_composite",
]
