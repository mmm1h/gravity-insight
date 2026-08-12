"""Strict, value-free Agent handoff for Saved Analysis replay."""

from __future__ import annotations

from collections.abc import Mapping
import re
from typing import Any


SAVED_ANALYSIS_NAME = "saved_analysis"
SAVED_ANALYSIS_SELECTOR = f"composite:{SAVED_ANALYSIS_NAME}"

_EXACT_SELECTORS = frozenset(
    {
        SAVED_ANALYSIS_NAME,
        SAVED_ANALYSIS_SELECTOR,
        "saved analysis",
        "saved report",
        "保存分析",
        "已存分析",
    }
)
_ASCII_WORD = re.compile(r"[a-z0-9_]+", re.IGNORECASE)
_ENGLISH_ACTIONS = frozenset(
    {
        "run",
        "rerun",
        "replay",
        "execute",
        "prepare",
        "inspect",
        "check",
        "get",
        "view",
        "analyze",
        "analyse",
    }
)
_ENGLISH_SUBJECTS = frozenset({"analysis", "report", "chart"})
_ENGLISH_BLOCKED = frozenset(
    {
        "create",
        "delete",
        "update",
        "template",
        "layout",
        "favourite",
        "favorite",
        "permission",
        "permissions",
        "member",
        "members",
    }
)
_CHINESE_ACTIONS = (
    "运行",
    "执行",
    "重放",
    "重跑",
    "准备",
    "检查",
    "查看",
    "获取",
    "分析",
)
_CHINESE_SUBJECTS = ("分析", "报表", "报告", "图表")
_CHINESE_BLOCKED = (
    "创建",
    "删除",
    "更新",
    "模板",
    "布局",
    "收藏",
    "权限",
    "成员",
)


SAVED_ANALYSIS_CAPABILITY: Mapping[str, Any] = {
    "name": SAVED_ANALYSIS_NAME,
    "domain": "analysis",
    "accepted_domains": ("analysis", "report"),
    "aliases": (
        "run saved analysis by exact reference",
        "replay saved report by exact reference",
        "prepare saved analysis web artifact",
        "按精确引用运行保存分析",
        "按精确引用重放已保存报表",
        "准备保存分析 Web artifact",
    ),
    "description": (
        "按稳定 ID 或精确名称解析保存分析，严格复用已证明的 event、funnel、"
        "retention、property、scatter 编译器，并在显式日期窗内准备或运行；"
        "不解释模板、布局、收藏或权限。"
    ),
    "required_inputs": ("app", "ref", "start", "end"),
    "input_schema": {
        "app": {
            "type": "string|integer",
            "required": True,
            "nullable": False,
            "description": "Workspace App alias or positive App id.",
        },
        "ref": {
            "type": "string|integer",
            "required": True,
            "nullable": False,
            "description": "Stable saved-analysis id or exact name.",
        },
        "start": {
            "type": "string",
            "format": "date",
            "required": True,
            "nullable": False,
            "description": "Inclusive YYYY-MM-DD replay start.",
        },
        "end": {
            "type": "string",
            "format": "date",
            "required": True,
            "nullable": False,
            "description": "Inclusive YYYY-MM-DD replay end, at most 90 days from start.",
        },
        "mode": {
            "type": "string",
            "required": False,
            "enum": ["prepare", "run"],
            "default": "run",
        },
    },
}


def saved_analysis_query(query: str) -> bool:
    """Recognize explicit replay/inspection intent and reject Web UI concepts."""

    selected = " ".join(query.strip().casefold().split())
    if selected in _EXACT_SELECTORS:
        return True
    if selected.isascii():
        words = frozenset(_ASCII_WORD.findall(selected))
        return (
            "saved" in words
            and bool(words & _ENGLISH_SUBJECTS)
            and bool(words & _ENGLISH_ACTIONS)
            and not bool(words & _ENGLISH_BLOCKED)
        )
    compact = "".join(selected.split())
    return (
        any(marker in compact for marker in ("保存", "已存"))
        and any(subject in compact for subject in _CHINESE_SUBJECTS)
        and any(action in compact for action in _CHINESE_ACTIONS)
        and not any(term in compact for term in _CHINESE_BLOCKED)
    )


def saved_analysis_plan_request(card: Mapping[str, Any]) -> dict[str, Any]:
    """Build a non-executing Plan request whose literal slots are copyable."""

    return {
        "name": SAVED_ANALYSIS_NAME,
        "app": card.get("app", "<workspace-app-alias-or-positive-id>"),
        "ref": card.get("ref", "<saved-analysis-id-or-exact-name>"),
        "start": card.get("start", "<start:YYYY-MM-DD>"),
        "end": card.get("end", "<end:YYYY-MM-DD>"),
        "mode": card.get("mode", "run"),
    }


__all__ = [
    "SAVED_ANALYSIS_CAPABILITY",
    "SAVED_ANALYSIS_NAME",
    "saved_analysis_plan_request",
    "saved_analysis_query",
]
