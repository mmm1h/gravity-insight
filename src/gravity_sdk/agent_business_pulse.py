"""Strict, value-free Agent handoff for the governed Business Pulse."""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping
from typing import Any

from .business_pulse import DEFAULT_PLATFORMS


BUSINESS_PULSE_NAME = "business_pulse"
BUSINESS_PULSE_SELECTOR = f"composite:{BUSINESS_PULSE_NAME}"
BUSINESS_PULSE_REQUIRED_INPUTS = ("apps", "start", "end")

_ASCII_WORD = re.compile(r"[a-z0-9_]+", re.IGNORECASE)
_EXACT_INTENTS = frozenset(
    {
        BUSINESS_PULSE_NAME,
        BUSINESS_PULSE_SELECTOR,
        "business pulse",
        "operating pulse",
        "经营脉搏",
        "业务脉搏",
    }
)
_ENGLISH_SUBJECTS = frozenset(
    {
        "business",
        "operating",
        "operational",
        "operation",
        "operations",
    }
)
_ENGLISH_OVERVIEW = frozenset({"overview", "summary"})
_ENGLISH_TRENDS = frozenset({"trend", "trends"})
_ENGLISH_BLOCKED = frozenset(
    {
        "attribution",
        "audience",
        "cohort",
        "config",
        "configuration",
        "create",
        "dashboard",
        "delete",
        "dimension",
        "dimensions",
        "event",
        "export",
        "favorite",
        "favorites",
        "favourite",
        "favourites",
        "funnel",
        "journey",
        "layout",
        "layouts",
        "member",
        "members",
        "multidim",
        "multidimensional",
        "permission",
        "permissions",
        "property",
        "retention",
        "saved",
        "scatter",
        "segment",
        "template",
        "templates",
        "update",
        "user",
        "users",
    }
)
_CHINESE_SUBJECTS = ("经营", "业务")
_CHINESE_PULSE = ("脉搏", "脉动")
_CHINESE_OVERVIEW = ("概览", "概况", "总览")
_CHINESE_TRENDS = ("趋势", "走势")
_CHINESE_BLOCKED = (
    "归因",
    "分群",
    "人群",
    "配置",
    "创建",
    "看板",
    "删除",
    "多维",
    "事件",
    "导出",
    "收藏",
    "漏斗",
    "旅程",
    "布局",
    "成员",
    "权限",
    "留存",
    "保存分析",
    "属性分析",
    "分布分析",
    "模板",
    "更新",
    "单用户",
    "attribution",
    "dashboard",
    "export",
    "multidim",
    "segment",
    "template",
)


BUSINESS_PULSE_CAPABILITY: Mapping[str, Any] = {
    "name": BUSINESS_PULSE_NAME,
    "domain": "report",
    "aliases": (
        "business pulse",
        "operating pulse",
        "business overview and trends",
        "经营脉搏",
        "业务脉搏",
        "经营概览和趋势",
    ),
    "description": (
        "并发汇总多个 App 在指定时间窗内的固定经营概览、趋势和可复核来源；"
        "调用方显式填写 App、日期、平台和小时开关。"
    ),
    "required_inputs": BUSINESS_PULSE_REQUIRED_INPUTS,
    "input_schema": {
        "apps": {
            "type": "array",
            "item_type": "string|integer",
            "required": True,
            "nullable": False,
            "min_items": 1,
            "max_items": 100,
        },
        "start": {
            "type": "string",
            "format": "date",
            "required": True,
            "nullable": False,
        },
        "end": {
            "type": "string",
            "format": "date",
            "required": True,
            "nullable": False,
        },
        "platforms": {
            "type": "array",
            "item_type": "string",
            "enum": list(DEFAULT_PLATFORMS),
            "required": False,
            "nullable": False,
            "default": list(DEFAULT_PLATFORMS),
        },
        "include_hourly": {
            "type": "boolean",
            "required": False,
            "nullable": False,
            "default": False,
        },
    },
}


def business_pulse_query(query: str) -> bool:
    """Recognize only explicit Pulse intent and reject adjacent products."""

    selected = " ".join(query.strip().casefold().split())
    if selected in _EXACT_INTENTS:
        return True
    if not selected:
        return False
    if selected.isascii():
        return _english_query(selected)
    return _chinese_query("".join(selected.split()))


def _english_query(selected: str) -> bool:
    words = frozenset(_ASCII_WORD.findall(selected.replace("-", " ")))
    if words & _ENGLISH_BLOCKED or not words & _ENGLISH_SUBJECTS:
        return False
    return "pulse" in words or bool(
        words & _ENGLISH_OVERVIEW and words & _ENGLISH_TRENDS
    )


def _chinese_query(selected: str) -> bool:
    if any(term in selected for term in _CHINESE_BLOCKED):
        return False
    subject = any(term in selected for term in _CHINESE_SUBJECTS)
    pulse = any(term in selected for term in _CHINESE_PULSE)
    overview = any(term in selected for term in _CHINESE_OVERVIEW)
    trends = any(term in selected for term in _CHINESE_TRENDS)
    return subject and (pulse or overview and trends)


def business_pulse_input_template() -> dict[str, Any]:
    """Return neutral slots and defaults without inferring business values."""

    return {
        "apps": ["<workspace-app-alias-or-positive-id>"],
        "start": "<start:YYYY-MM-DD>",
        "end": "<end:YYYY-MM-DD>",
        "platforms": list(DEFAULT_PLATFORMS),
        "include_hourly": False,
    }


def business_pulse_plan_request(card: Mapping[str, Any]) -> dict[str, Any]:
    """Build a complete, mechanically fillable Plan request."""

    template = business_pulse_input_template()
    return {
        "name": BUSINESS_PULSE_NAME,
        "apps": copy.deepcopy(card.get("apps", template["apps"])),
        "start": card.get("start", template["start"]),
        "end": card.get("end", template["end"]),
        "platforms": copy.deepcopy(card.get("platforms", template["platforms"])),
        "include_hourly": card.get("include_hourly", False),
    }


__all__ = [
    "BUSINESS_PULSE_CAPABILITY",
    "BUSINESS_PULSE_NAME",
    "BUSINESS_PULSE_REQUIRED_INPUTS",
    "BUSINESS_PULSE_SELECTOR",
    "business_pulse_input_template",
    "business_pulse_plan_request",
    "business_pulse_query",
]
