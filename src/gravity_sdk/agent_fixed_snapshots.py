"""Natural-language recognizers for fixed Analysis/App snapshot products."""

from __future__ import annotations

import re


_EXACT = {
    "analysis_context": frozenset({
        "analysis context", "analysis metadata", "analysis vocabulary",
        "分析上下文", "分析元数据",
    }),
    "app_snapshot": frozenset({
        "app snapshot", "app snapshots", "application snapshot", "app governance",
        "应用快照", "应用治理",
    }),
    "attribution_snapshot": frozenset({
        "attribution snapshot", "attribution configuration",
        "归因快照", "归因配置",
    }),
}


def fixed_snapshot_query(name: str, query: str) -> bool:
    selected = " ".join(query.strip().casefold().split())
    if selected in _EXACT.get(name, ()):
        return True
    if name == "analysis_context":
        return _analysis_context(selected)
    if name == "app_snapshot":
        return _app_snapshot(selected)
    if name == "attribution_snapshot":
        return _attribution_snapshot(selected)
    return False


def _analysis_context(selected: str) -> bool:
    words = frozenset(re.findall(r"[a-z0-9_]+", selected))
    english_groups = (
        {"event", "events"}, {"property", "properties", "attributes"},
        {"metric", "metrics"}, {"template", "templates"},
    )
    english = (
        sum(bool(words & group) for group in english_groups) >= 3
        and bool(words & {"available", "building", "construct", "give", "new"})
        and bool(words & {"analysis", "analytics", "app"})
    )
    chinese_groups = ("事件", "属性", "指标", "模板")
    chinese = (
        sum(term in selected for term in chinese_groups) >= 3
        and "分析" in selected
        and any(term in selected for term in ("可用", "搭", "构造", "一次", "给我"))
    )
    return english or chinese


def _app_snapshot(selected: str) -> bool:
    words = frozenset(re.findall(r"[a-z0-9_]+", selected))
    english_groups = (
        {"capacity"}, {"role", "roles"}, {"menu", "menus"},
        {"realtime", "real", "governance"},
    )
    english = "app" in words and sum(
        bool(words & group) for group in english_groups
    ) >= 3
    chinese_groups = ("容量", "角色", "菜单", "实时事件", "治理")
    chinese = (
        ("app" in words or "应用" in selected)
        and sum(term in selected for term in chinese_groups) >= 3
    )
    return english or chinese


def _attribution_snapshot(selected: str) -> bool:
    words = frozenset(re.findall(r"[a-z0-9_]+", selected))
    english_groups = (
        {"rule", "rules", "configuration", "configured"},
        {"mapping", "mappings"}, {"lookback", "window", "settings"},
    )
    english = "attribution" in words and sum(
        bool(words & group) for group in english_groups
    ) >= 2
    chinese_groups = ("归因规则", "归因配置", "字段映射", "映射", "回溯", "窗口")
    chinese = "归因" in selected and sum(
        term in selected for term in chinese_groups
    ) >= 2
    return english or chinese


__all__ = ["fixed_snapshot_query"]
