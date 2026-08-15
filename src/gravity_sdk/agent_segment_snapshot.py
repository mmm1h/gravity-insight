"""Strict Agent discovery for the fixed Segment Snapshot composite."""

from __future__ import annotations

from collections.abc import Mapping
import re
from typing import Any


SEGMENT_SNAPSHOT_NAME = "segment_snapshot"
SEGMENT_SNAPSHOT_SELECTOR = f"composite:{SEGMENT_SNAPSHOT_NAME}"

_EXACT_SELECTORS = frozenset(
    {SEGMENT_SNAPSHOT_NAME, SEGMENT_SNAPSHOT_SELECTOR}
)
_ASCII_WORD = re.compile(r"[a-z0-9_]+", re.IGNORECASE)
_ISO_DATE = re.compile(r"(?<!\d)\d{4}-\d{2}-\d{2}(?!\d)")
_ENGLISH_SUBJECTS = frozenset({"segment", "audience", "cohort"})
_ENGLISH_ACTIONS = frozenset({
    "snapshot", "inspect", "inspection", "check", "audit", "show", "view",
})
_ENGLISH_DETAILS = frozenset({"detail", "details"})
_ENGLISH_HISTORY = frozenset({"history", "historical", "version", "versions"})
_ENGLISH_DAILY = frozenset({"daily", "day", "date", "yesterday"})
_ENGLISH_RESULTS = frozenset({
    "result", "results", "calculation", "calculations", "count", "aggregate",
})
_ENGLISH_BLOCKED = frozenset(
    {"rule", "rules", "condition", "conditions", "member", "members", "export",
     "create", "update", "delete"}
)
_ENGLISH_BLOCKED_PHRASES = (
    "user list", "users list", "list user", "user-level", "user level"
)
_CHINESE_BLOCKED = ("规则", "条件", "成员", "用户列表", "导出", "创建", "更新", "删除")


SEGMENT_SNAPSHOT_CAPABILITY: Mapping[str, Any] = {
    "name": SEGMENT_SNAPSHOT_NAME,
    "domain": "analysis",
    "accepted_domains": ("analysis", "segment"),
    "aliases": (
        "segment snapshot details history daily result",
        "inspect segment details history and daily result",
        "分群快照详情历史单日结果",
        "检查分群详情历史和单日计算结果",
    ),
    "description": (
        "按精确 ID 或精确名称解析一个分群，并发读取详情、历史版本和指定日期的"
        "单日计算结果；不读取成员或规则定义。"
    ),
    "required_inputs": ("app", "ref", "date"),
    "input_schema": {
        "app": {"type": "string|integer", "required": True, "nullable": False},
        "ref": {
            "type": "string|integer", "required": True, "nullable": False,
            "description": "Exact segment id or exact segment name.",
        },
        "date": {
            "type": "string", "format": "date", "required": True, "nullable": False,
            "description": "One YYYY-MM-DD calculation date.",
        },
    },
}


def segment_snapshot_query(query: str) -> bool:
    """Recognize only a complete snapshot intent; broad segment text fails closed."""

    selected = query.strip().casefold()
    if selected in _EXACT_SELECTORS:
        return True
    if selected.isascii():
        return _english_snapshot_query(selected)
    return _chinese_snapshot_query(selected)


def segment_snapshot_intent(query: str) -> bool:
    """Return positive complete-snapshot evidence without conflict exclusions."""

    selected = query.strip().casefold()
    if selected in _EXACT_SELECTORS:
        return True
    if selected.isascii():
        return _english_snapshot_shape(selected)
    return _chinese_snapshot_shape("".join(selected.split()))


def _english_snapshot_query(selected: str) -> bool:
    words = frozenset(_ASCII_WORD.findall(selected))
    return (
        not (words & _ENGLISH_BLOCKED)
        and not any(term in selected for term in _ENGLISH_BLOCKED_PHRASES)
        and _english_snapshot_shape(selected)
    )


def _chinese_snapshot_query(selected: str) -> bool:
    compact = "".join(selected.split())
    return (
        not any(term in compact for term in _CHINESE_BLOCKED)
        and _chinese_snapshot_shape(compact)
    )


def _english_snapshot_shape(selected: str) -> bool:
    words = frozenset(_ASCII_WORD.findall(selected))
    groups = (
        _ENGLISH_SUBJECTS, _ENGLISH_ACTIONS, _ENGLISH_DETAILS,
        _ENGLISH_HISTORY, _ENGLISH_RESULTS,
    )
    return all(words & group for group in groups) and (
        bool(words & _ENGLISH_DAILY) or _ISO_DATE.search(selected) is not None
    )


def _chinese_snapshot_shape(compact: str) -> bool:
    subjects = ("分群", "人群", "受众")
    actions = ("快照", "检查", "查看")
    history = ("历史", "历史版本", "版本", "版本记录")
    results = (
        "单日结果", "当日结果", "单日计算结果", "聚合人数结果", "人数结果",
    )
    return (
        any(term in compact for term in subjects)
        and any(term in compact for term in actions)
        and "详情" in compact
        and any(term in compact for term in history)
        and (
            any(term in compact for term in results)
            or "昨天" in compact
            or _ISO_DATE.search(compact) is not None
        )
    )


def segment_snapshot_plan_request(card: Mapping[str, Any]) -> dict[str, Any]:
    """Return an explicit copyable request without guessing any input value."""

    return {
        "name": SEGMENT_SNAPSHOT_NAME,
        "app": card.get("app", "<workspace-app-alias-or-positive-id>"),
        "ref": card.get("ref", "<segment-id-or-exact-name>"),
        "date": card.get("date", "<date:YYYY-MM-DD>"),
    }


__all__ = [
    "SEGMENT_SNAPSHOT_CAPABILITY",
    "SEGMENT_SNAPSHOT_NAME",
    "segment_snapshot_plan_request",
    "segment_snapshot_intent",
    "segment_snapshot_query",
]
