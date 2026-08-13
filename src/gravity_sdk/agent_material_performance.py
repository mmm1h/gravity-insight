"""Strict, value-free Agent handoff for Material Performance v1."""

from __future__ import annotations

import copy
from collections.abc import Mapping
import re
from typing import Any

from .material_performance import DEFAULT_PLATFORMS


MATERIAL_PERFORMANCE_NAME = "material_performance"
MATERIAL_PERFORMANCE_SELECTOR = f"composite:{MATERIAL_PERFORMANCE_NAME}"
_EXACT = frozenset(
    {
        MATERIAL_PERFORMANCE_NAME,
        MATERIAL_PERFORMANCE_SELECTOR,
        "material performance",
        "material report",
        "cross platform material report",
        "素材表现",
        "素材报表",
        "素材效果报表",
        "跨平台素材报表",
    }
)
_ASCII_WORD = re.compile(r"[a-z0-9_]+", re.IGNORECASE)
_ENGLISH_NEGATION_PHRASE = re.compile(r"\b(?:don['’]?t|do\s+not)\b")
_ENGLISH_ACTIONS = frozenset({"performance", "report"})
_ENGLISH_BLOCKED = frozenset(
    {
        "export", "download", "library", "catalog", "album", "tag", "tags",
        "review", "reviews", "favorite", "favorites", "favourite", "favourites",
        "recycle", "upload", "template", "dashboard", "promotion", "campaign",
        "business", "pulse", "multidim", "create", "update", "delete",
        "rank", "ranking", "rankings", "top", "best", "winner",
        "not", "no", "avoid", "exclude", "never", "skip", "without", "saved",
    }
)
_CHINESE_ACTIONS = ("表现", "效果", "报表")
_CHINESE_ORDER_DIRECTORY = ("订单目录", "订单明细", "订单详情", "订单列表")
_CHINESE_BLOCKED = (
    "导出", "下载", "素材库", "相册", "标签", "审核", "收藏", "回收", "上传",
    "模板", "看板", "推广", "经营", "业务脉搏", "多维", "创建", "更新", "删除",
    "排名", "排行", "最佳", "最好", "不要", "无需", "无须", "不需要", "不必",
    "不做", "不用",
    "避免", "非素材", "保存", "已存", "脉搏", "脉动",
)
_CHINESE_BIE_NEGATION = re.compile(
    r"(?:^|请|麻烦|[\s，,。；;！!])别(?:再)?"
    r"(?=查|看|跑|执行|获取|做|查询|输出|拉取|给|展示)"
)


MATERIAL_PERFORMANCE_CAPABILITY: Mapping[str, Any] = {
    "name": MATERIAL_PERFORMANCE_NAME,
    "domain": "material",
    "accepted_domains": ("material", "report"),
    "aliases": (
        "read governed material performance across supported platforms",
        "run a cross-platform material report",
        "读取受治理的四平台素材表现",
        "执行跨平台素材效果报表",
    ),
    "description": (
        "按显式 App、日期和平台并发读取稳定素材表现行；保留各平台物理指标，"
        "不做跨平台归一、排名或业务结论。"
    ),
    "required_inputs": ("apps", "start", "end"),
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
            "type": "string", "format": "date", "required": True,
            "nullable": False,
        },
        "end": {
            "type": "string", "format": "date", "required": True,
            "nullable": False,
        },
        "platforms": {
            "type": "array",
            "item_type": "string",
            "required": False,
            "nullable": False,
            "enum": list(DEFAULT_PLATFORMS),
            "default": list(DEFAULT_PLATFORMS),
        },
    },
}


def material_performance_query(query: str) -> bool:
    """Recognize aggregate material reporting and reject adjacent products."""

    selected = " ".join(query.strip().casefold().split())
    words = frozenset(_ASCII_WORD.findall(selected))
    compact = "".join(selected.split())
    if _blocked_query(selected, words, compact):
        return False
    if selected in _EXACT:
        return True
    if selected.isascii() and " " not in selected and "." in selected:
        return False
    if words & {"material", "materials"} and words & _ENGLISH_ACTIONS:
        return True
    if selected.isascii():
        return False
    return (
        "素材" in compact
        and any(term in compact for term in _CHINESE_ACTIONS)
    )


def _blocked_query(
    selected: str, words: frozenset[str], compact: str
) -> bool:
    return bool(
        words & _ENGLISH_BLOCKED
        or _ENGLISH_NEGATION_PHRASE.search(selected)
        or _order_directory_conflict(words, compact)
        or any(term in compact for term in _CHINESE_BLOCKED)
        or _CHINESE_BIE_NEGATION.search(selected)
    )


def _order_directory_conflict(words: frozenset[str], compact: str) -> bool:
    return bool(
        words & {"order", "orders"}
        and words & {"directory", "detail", "details"}
    ) or any(term in compact for term in _CHINESE_ORDER_DIRECTORY)


def material_performance_plan_request(card: Mapping[str, Any]) -> dict[str, Any]:
    """Return type-correct literal slots without selecting business values."""

    template = material_performance_input_template()
    return {"name": MATERIAL_PERFORMANCE_NAME, **{
        key: copy.deepcopy(card.get(key, value)) for key, value in template.items()
    }}


def material_performance_input_template() -> dict[str, Any]:
    return {
        "apps": ["<workspace-app-alias-or-positive-id>"],
        "start": "<start:YYYY-MM-DD>",
        "end": "<end:YYYY-MM-DD>",
        "platforms": list(DEFAULT_PLATFORMS),
    }


__all__ = [
    "MATERIAL_PERFORMANCE_CAPABILITY",
    "MATERIAL_PERFORMANCE_NAME",
    "material_performance_input_template",
    "material_performance_plan_request",
    "material_performance_query",
]
