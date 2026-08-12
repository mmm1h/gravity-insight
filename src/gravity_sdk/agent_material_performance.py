"""Strict, value-free Agent handoff for Material Performance v1."""

from __future__ import annotations

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
_ENGLISH_ACTIONS = frozenset({"performance", "report"})
_ENGLISH_BLOCKED = frozenset(
    {
        "export", "download", "library", "catalog", "album", "tag", "tags",
        "review", "reviews", "favorite", "favorites", "favourite", "favourites",
        "recycle", "upload", "template", "dashboard", "promotion", "campaign",
        "business", "pulse", "multidim", "create", "update", "delete",
        "rank", "ranking", "rankings", "top", "best", "winner",
        "not", "no", "avoid", "without",
    }
)
_CHINESE_ACTIONS = ("表现", "效果", "报表")
_CHINESE_BLOCKED = (
    "导出", "下载", "素材库", "相册", "标签", "审核", "收藏", "回收", "上传",
    "模板", "看板", "推广", "经营", "业务脉搏", "多维", "创建", "更新", "删除",
    "排名", "排行", "最佳", "最好", "不要", "无需",
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
    if words & _ENGLISH_BLOCKED:
        return False
    if any(term in compact for term in _CHINESE_BLOCKED):
        return False
    if selected in _EXACT:
        return True
    if selected.isascii():
        if " " not in selected and "." in selected:
            return False
        return (
            bool(words & {"material", "materials"})
            and bool(words & _ENGLISH_ACTIONS)
        )
    return (
        "素材" in compact
        and any(term in compact for term in _CHINESE_ACTIONS)
    )


def material_performance_plan_request(card: Mapping[str, Any]) -> dict[str, Any]:
    """Return type-correct literal slots without selecting business values."""

    return {
        "name": MATERIAL_PERFORMANCE_NAME,
        "apps": card.get("apps", ["<workspace-app-alias-or-positive-id>"]),
        "start": card.get("start", "<start:YYYY-MM-DD>"),
        "end": card.get("end", "<end:YYYY-MM-DD>"),
        "platforms": card.get("platforms", list(DEFAULT_PLATFORMS)),
    }


def material_performance_input_template() -> dict[str, Any]:
    return material_performance_plan_request({})


__all__ = [
    "MATERIAL_PERFORMANCE_CAPABILITY",
    "MATERIAL_PERFORMANCE_NAME",
    "material_performance_input_template",
    "material_performance_plan_request",
    "material_performance_query",
]
