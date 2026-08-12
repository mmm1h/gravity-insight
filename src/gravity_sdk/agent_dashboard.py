"""Value-free Dashboard Snapshot intent and Plan handoff helpers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def dashboard_snapshot_query(query: str) -> bool:
    """Recognize control-plane requests without capturing chart execution."""

    selected = query.strip().casefold()
    if any(term in selected for term in ("chart", "图表")):
        return False
    english = (
        "snapshot", "context", "control", "detail", "member", "filter",
        "favourite", "favorite", "inspect", "show", "view", "check", "get",
    )
    chinese = (
        "快照", "上下文", "控制面", "详情", "成员", "筛选", "收藏", "查看",
        "检查", "获取", "展示", "查询",
    )
    return (
        "dashboard" in selected and any(term in selected for term in english)
    ) or ("看板" in selected and any(term in selected for term in chinese))


def dashboard_plan_request(card: Mapping[str, Any]) -> dict[str, Any]:
    """Build one mechanically fillable composite request from a discovery card."""

    request = {"name": "dashboard_snapshot"}
    schema = card.get("input_schema")
    fields = schema if isinstance(schema, Mapping) else {}
    for field in ("app", "ref"):
        value = card.get(field)
        request[field] = value if value is not None else _placeholder(field, fields.get(field))
    return request


def _placeholder(name: str, specification: Any) -> str:
    selected_type = (
        str(specification.get("type", "value"))
        if isinstance(specification, Mapping)
        else "value"
    )
    return f"<{name}:{selected_type}>"


__all__ = ["dashboard_plan_request", "dashboard_snapshot_query"]
