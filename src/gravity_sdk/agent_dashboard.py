"""Value-free Dashboard control-plane and chart-replay Agent handoffs."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


DASHBOARD_ANALYSIS_CAPABILITY: Mapping[str, Any] = {
    "name": "dashboard_analysis",
    "domain": "analysis",
    "accepted_domains": ("analysis", "report"),
    "aliases": (
        "run dashboard charts",
        "replay dashboard charts",
        "execute dashboard charts",
        "rerun dashboard charts",
        "analyze dashboard charts",
        "执行看板图表",
        "运行看板图表",
        "重放看板图表",
        "重跑看板图表",
        "分析看板图表",
    ),
    "intent_terms": (
        "run dashboard chart",
        "replay dashboard chart",
        "execute dashboard chart",
        "rerun dashboard chart",
        "执行看板图表",
        "运行看板图表",
        "重放看板图表",
        "重跑看板图表",
        "分析看板图表",
    ),
    "description": (
        "按精确 ID 或名称解析看板，把受支持的 Web 图表配置编译为稳定 "
        "Analysis 查询，并发执行且按看板声明顺序返回；不模拟页面布局或收藏筛选。"
    ),
    "required_inputs": ("app", "ref", "start", "end"),
    "input_schema": {
        "app": {"type": "string|integer", "required": True, "nullable": False},
        "ref": {
            "type": "string|integer",
            "required": True,
            "nullable": False,
            "description": "Exact dashboard id or exact dashboard name.",
        },
        "start": {"type": "string", "required": True, "nullable": False},
        "end": {"type": "string", "required": True, "nullable": False},
        "mode": {
            "type": "string",
            "required": False,
            "enum": ["prepare", "run"],
            "default": "run",
        },
    },
}


def dashboard_snapshot_query(query: str) -> bool:
    """Recognize control-plane requests without capturing chart execution."""

    selected = query.strip().casefold()
    from .agent_intent_routing import adjacent_product_conflict

    if adjacent_product_conflict("dashboard_snapshot", selected):
        return False
    return dashboard_snapshot_intent(query)


def dashboard_snapshot_intent(query: str) -> bool:
    """Return positive snapshot evidence without applying adjacent-product policy."""

    selected = query.strip().casefold()
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


def dashboard_analysis_query(query: str) -> bool:
    """Recognize explicit chart execution/replay without capturing snapshots."""

    selected = query.strip().casefold()
    from .agent_intent_routing import adjacent_product_conflict

    # Here "saved" modifies dashboard; it is not evidence for the separate
    # Saved Analysis wrapper that the adjacent-product guard protects.
    if "saved dashboard" in selected and dashboard_analysis_intent(query):
        return True
    if adjacent_product_conflict("dashboard_analysis", selected):
        return False
    return dashboard_analysis_intent(query)


def dashboard_analysis_intent(query: str) -> bool:
    """Return positive chart-replay evidence without adjacent-product policy."""

    selected = query.strip().casefold()
    english_action = ("run", "replay", "execute", "rerun", "refresh", "analyze")
    chinese_action = ("执行", "运行", "重放", "重跑", "刷新", "分析")
    return (
        "dashboard" in selected
        and "chart" in selected
        and any(term in selected for term in english_action)
    ) or (
        "看板" in selected
        and "图表" in selected
        and any(term in selected for term in chinese_action)
    )


def dashboard_plan_request(card: Mapping[str, Any]) -> dict[str, Any]:
    """Build one mechanically fillable composite request from a discovery card."""

    request = {"name": "dashboard_snapshot"}
    schema = card.get("input_schema")
    fields = schema if isinstance(schema, Mapping) else {}
    for field in ("app", "ref"):
        value = card.get(field)
        request[field] = value if value is not None else _placeholder(field, fields.get(field))
    return request


def dashboard_analysis_plan_request(card: Mapping[str, Any]) -> dict[str, Any]:
    """Build a non-executing, mechanically fillable chart replay Plan node."""

    request = {"name": "dashboard_analysis", "mode": card.get("mode", "run")}
    schema = card.get("input_schema")
    fields = schema if isinstance(schema, Mapping) else {}
    for field in ("app", "ref", "start", "end"):
        value = card.get(field)
        request[field] = value if value is not None else _placeholder(
            field, fields.get(field)
        )
    return request


def _placeholder(name: str, specification: Any) -> str:
    selected_type = (
        str(specification.get("type", "value"))
        if isinstance(specification, Mapping)
        else "value"
    )
    return f"<{name}:{selected_type}>"


__all__ = [
    "DASHBOARD_ANALYSIS_CAPABILITY",
    "dashboard_analysis_plan_request",
    "dashboard_analysis_intent",
    "dashboard_analysis_query",
    "dashboard_plan_request",
    "dashboard_snapshot_intent",
    "dashboard_snapshot_query",
]
