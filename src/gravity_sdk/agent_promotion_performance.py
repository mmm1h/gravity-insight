"""Strict, value-free Agent handoff for Promotion Performance v1."""

from __future__ import annotations

import copy
from collections.abc import Mapping
import re
from typing import Any

from .agent_intent_text import affirmative_intent_text

from .domains import PROMOTION_PLATFORMS


PROMOTION_PERFORMANCE_NAME = "promotion_performance"
PROMOTION_PERFORMANCE_SELECTOR = f"composite:{PROMOTION_PERFORMANCE_NAME}"
PROMOTION_PERFORMANCE_REQUIRED_INPUTS = (
    "app",
    "start",
    "end",
    "platforms",
    "metrics",
)
PROMOTION_PERFORMANCE_PLATFORMS = tuple(
    platform
    for platform in sorted(PROMOTION_PLATFORMS)
    if platform not in {"bing", "taptap", "wechat_video", "xiaohongshu"}
)

_ASCII_WORD = re.compile(r"[a-z0-9_]+", re.IGNORECASE)
_COMPACT_SEPARATORS = re.compile(r"[\s_-]+")
_ENGLISH_NEGATION_PHRASE = re.compile(
    r"\b(?:don['’]?t|do\s+not|cannot|can['’]?t|can\s+not|won['’]?t|will\s+not)\b"
)
_EXACT_INTENTS = frozenset(
    {
        PROMOTION_PERFORMANCE_NAME,
        PROMOTION_PERFORMANCE_SELECTOR,
        "promotion performance",
        "promotion report",
        "cross platform promotion performance",
        "cross platform promotion report",
        "advertising performance",
        "推广表现",
        "推广报表",
        "跨平台推广表现",
        "跨平台推广报表",
        "跨平台投放报表",
    }
)
_ENGLISH_SUBJECTS = frozenset(
    {"ad", "ads", "advertising", "promotion", "promotions"}
)
_ENGLISH_ACTIONS = frozenset({"performance", "report", "reporting"})
_ENGLISH_METRICS = frozenset({
    "spend", "cost", "click", "clicks", "conversion", "conversions",
    "impression", "impressions",
})
_ENGLISH_READ_ONLY_VERBS = frozenset({"query"})
_ENGLISH_NEGATIONS = frozenset(
    {"avoid", "cannot", "exclude", "never", "no", "not", "skip", "without"}
)
_ENGLISH_BLOCKED = frozenset(
    {
        "account", "accounts", "advertiser", "adviser", "advice", "attribution",
        "audience", "best", "business", "campaign", "catalog", "create",
        "creative", "dashboard", "delete", "directory", "download", "edit",
        "export", "hierarchy", "journey", "level", "material", "materials",
        "multidim", "multidimensional", "mutate", "optimization", "optimize",
        "permission", "permissions", "plan", "planning", "publish", "published",
        "publishing", "pulse", "query", "rank", "ranking", "remove", "removed",
        "removing", "insert", "inserted", "inserting",
        "raw", "recommend", "recommendation", "saved", "segment", "snapshot",
        "strategy", "template", "update", "upload", "user", "write",
    }
)
_HETEROGENEOUS_ENGLISH = (
    "bing",
    "red book",
    "rednote",
    "taptap",
    "video account",
    "wechat video",
    "wechat_video",
    "xiaohongshu",
)
_CHINESE_SUBJECTS = ("推广", "投放")
_CHINESE_ACTIONS = ("表现", "效果", "报表", "报告")
_CHINESE_METRICS = ("消耗", "花费", "点击", "转化", "曝光")
_CHINESE_READ_ONLY_VERBS = ("查询",)
_CHINESE_NEGATIONS = (
    "不要", "无需", "无须", "不需要", "不必", "不做", "不用", "避免", "排除",
    "不是", "并非", "非推广", "非投放", "不想看", "不想要", "拒绝", "不看", "不查",
    "不查询",
)
_CHINESE_BLOCKED = (
    "账户", "账号", "广告主", "归因", "人群", "受众", "最佳", "最好", "经营",
    "业务脉搏", "活动", "系列", "目录", "创建", "素材", "看板", "删除", "下载",
    "导出", "层级", "旅程", "多维", "修改", "优化", "权限", "脉搏", "查询",
    "排行", "排名", "原始", "建议", "推荐", "方案", "保存分析", "保存", "已存",
    "分群", "快照", "策略", "模板", "更新", "上传", "发布", "移除", "插入",
    "单用户", "写入",
)
_HETEROGENEOUS_CHINESE = ("必应", "小红书", "微信视频号", "视频号")
_HETEROGENEOUS_COMPACT = tuple(
    _COMPACT_SEPARATORS.sub("", term.casefold())
    for term in (*_HETEROGENEOUS_ENGLISH, *_HETEROGENEOUS_CHINESE)
)
_CHINESE_BLOCKING_TERMS = tuple(
    term
    for term in (*_CHINESE_BLOCKED, *_CHINESE_NEGATIONS)
    if term not in _CHINESE_READ_ONLY_VERBS
)
_CHINESE_BIE_NEGATION = re.compile(
    r"(?:^|请|麻烦|[\s，,。；;！!])别(?:再)?"
    r"(?=$|[\s，,。；;！!]|查|看|跑|执行|生成|获取|做|分析|汇总|查询|输出|拉取|给|展示)"
)


PROMOTION_PERFORMANCE_CAPABILITY: Mapping[str, Any] = {
    "name": PROMOTION_PERFORMANCE_NAME,
    "domain": "promotion",
    "accepted_domains": ("promotion", "report"),
    "aliases": (
        "read governed promotion performance across supported platforms",
        "run a cross-platform promotion report with physical metrics",
        "读取受治理的跨平台推广表现",
        "按显式物理指标执行跨平台投放报表",
    ),
    "description": (
        "按显式 App、日期、平台和物理指标读取 21 个同构平台的推广表现；"
        "保留平台原生字段，不做跨平台归一、排名、策略或业务结论。"
    ),
    "required_inputs": PROMOTION_PERFORMANCE_REQUIRED_INPUTS,
    "input_schema": {
        "app": {
            "type": "string|integer",
            "required": True,
            "nullable": False,
            "description": "Workspace App alias or positive App id.",
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
            "required": True,
            "nullable": False,
            "min_items": 1,
            "max_items": len(PROMOTION_PERFORMANCE_PLATFORMS),
            "unique_items": True,
            "enum": list(PROMOTION_PERFORMANCE_PLATFORMS),
        },
        "metrics": {
            "type": "array",
            "item_type": "string",
            "required": True,
            "nullable": False,
            "min_items": 1,
            "max_items": 500,
            "unique_items": True,
            "item_max_length": 128,
            "item_pattern": r"^[A-Za-z_][A-Za-z0-9_.-]{0,127}$",
            "description": "Upstream physical metric names, selected per platform.",
        },
    },
    "plan_node_limits": {"max_pages": 5, "max_items": 200},
}


def promotion_performance_query(query: str) -> bool:
    """Recognize explicit performance reads and reject adjacent products."""

    selected = affirmative_intent_text(query)
    if selected in _EXACT_INTENTS:
        return True
    if _product_level_performance(selected):
        return True
    return _claims_product(selected) and not _blocked(selected)


def promotion_performance_intent(query: str) -> bool:
    """Return positive promotion evidence without applying conflict policy."""

    from .agent_bilibili_account_performance import (
        bilibili_account_performance_intent,
    )

    selected = affirmative_intent_text(query)
    words = frozenset(_ASCII_WORD.findall(selected.replace("-", " ")))
    compact = _compact(selected)
    if (
        words & {"creative", "creatives", "material", "materials"}
        and not words & {"campaign", "promotion", "promotions"}
    ):
        return False
    if _material_specific_query(compact):
        return False
    if bilibili_account_performance_intent(query):
        return False
    return selected in _EXACT_INTENTS or _claims_product(selected)


def promotion_performance_blocks_operation_fallback(query: str) -> bool:
    """Claim explicit product-shaped requests even when policy blocks the card.

    A rejected export, write, strategy, raw snapshot, or heterogeneous-platform
    request must become a capability gap.  Treating it as a generic Promotion
    search would otherwise surface a lower-level operation with different
    semantics.
    """

    selected = _normalize(query)
    return selected in _EXACT_INTENTS or _claims_product(selected)


def promotion_performance_input_template() -> dict[str, Any]:
    """Return literal slots without choosing any business value."""

    return {
        "app": "<workspace-app-alias-or-positive-id>",
        "start": "<start:YYYY-MM-DD>",
        "end": "<end:YYYY-MM-DD>",
        "platforms": ["<supported-promotion-platform>"],
        "metrics": ["<physical-metric-name>"],
    }


def promotion_performance_plan_request(card: Mapping[str, Any]) -> dict[str, Any]:
    """Build a complete, mechanically fillable Plan request."""

    template = promotion_performance_input_template()
    return {
        "name": PROMOTION_PERFORMANCE_NAME,
        **{
            key: copy.deepcopy(card.get(key, value))
            for key, value in template.items()
        },
    }


def _normalize(query: str) -> str:
    return " ".join(str(query or "").strip().casefold().split())


def _claims_product(selected: str) -> bool:
    if not selected:
        return False
    if selected.isascii() and " " not in selected and "." in selected:
        return False
    words = frozenset(_ASCII_WORD.findall(selected.replace("-", " ")))
    compact = _compact(selected)
    if _material_specific_query(compact) or _media_report_directory_query(compact):
        return False
    subject, action, adjacent, heterogeneous = _intent_signals(words, compact)
    return bool(subject and (action or adjacent) or heterogeneous and action)


def _product_level_performance(selected: str) -> bool:
    words = frozenset(_ASCII_WORD.findall(selected.replace("-", " ")))
    compact = _compact(selected)
    if (
        _ENGLISH_NEGATION_PHRASE.search(selected)
        or _CHINESE_BIE_NEGATION.search(selected)
        or _contains_any(compact, _HETEROGENEOUS_COMPACT)
    ):
        return False
    english = (
        bool(words & _ENGLISH_SUBJECTS)
        and bool(words & {"campaign", "hierarchy", "level"})
        and bool(words & _ENGLISH_ACTIONS)
        and not bool(
            words
            & (_ENGLISH_BLOCKED | _ENGLISH_NEGATIONS)
            - _ENGLISH_READ_ONLY_VERBS
            - {"campaign", "hierarchy", "level"}
        )
    )
    chinese_blocked = tuple(
        term for term in _CHINESE_BLOCKING_TERMS
        if term not in {"活动", "系列", "层级"}
    )
    chinese = (
        _contains_any(compact, _CHINESE_SUBJECTS)
        and "层级" in compact
        and _contains_any(compact, _CHINESE_ACTIONS)
        and not _contains_any(compact, chinese_blocked)
    )
    return english or chinese


def _intent_signals(
    words: frozenset[str], compact: str
) -> tuple[bool, bool, bool, bool]:
    """Combine English and Chinese subjects/actions without inferring values."""

    metric_report = (
        len(words & _ENGLISH_METRICS) >= 2
        or sum(term in compact for term in _CHINESE_METRICS) >= 2
    )
    subject = bool(words & _ENGLISH_SUBJECTS) or _contains_any(
        compact, _CHINESE_SUBJECTS
    ) or "巨量" in compact and metric_report
    action = bool(words & _ENGLISH_ACTIONS) or _contains_any(
        compact, _CHINESE_ACTIONS
    ) or metric_report
    adjacent = _has_blocked_term(words, compact)
    heterogeneous = _contains_any(compact, _HETEROGENEOUS_COMPACT)
    return subject, action, adjacent, heterogeneous


def _compact(value: str) -> str:
    """Normalize spacing variants used by platform aliases.

    Only spaces, hyphens, and underscores collapse; query meaning is untouched.
    """

    return _COMPACT_SEPARATORS.sub("", value.casefold())


def _contains_any(value: str, terms: tuple[str, ...]) -> bool:
    return any(term in value for term in terms)


def _material_specific_query(compact: str) -> bool:
    if not _contains_any(compact, ("素材", "创意")):
        return False
    return not _contains_any(
        compact, ("推广表现", "投放表现", "推广报表", "投放报表")
    )


def _media_report_directory_query(compact: str) -> bool:
    return "媒体" in compact and "报表" in compact and not _contains_any(
        compact, ("表现", "效果", "消耗", "点击", "转化")
    )


def _has_blocked_term(words: frozenset[str], compact: str) -> bool:
    english = words & (_ENGLISH_BLOCKED | _ENGLISH_NEGATIONS)
    return bool(english - _ENGLISH_READ_ONLY_VERBS) or _contains_any(
        compact, _CHINESE_BLOCKING_TERMS
    )


def _blocked(selected: str) -> bool:
    words = frozenset(_ASCII_WORD.findall(selected.replace("-", " ")))
    compact = _compact(selected)
    return bool(
        _has_blocked_term(words, compact)
        or _ENGLISH_NEGATION_PHRASE.search(selected)
        or _contains_any(compact, _HETEROGENEOUS_COMPACT)
        or _CHINESE_BIE_NEGATION.search(selected)
    )


__all__ = [
    "PROMOTION_PERFORMANCE_CAPABILITY",
    "PROMOTION_PERFORMANCE_NAME",
    "PROMOTION_PERFORMANCE_PLATFORMS",
    "PROMOTION_PERFORMANCE_REQUIRED_INPUTS",
    "PROMOTION_PERFORMANCE_SELECTOR",
    "promotion_performance_blocks_operation_fallback",
    "promotion_performance_input_template",
    "promotion_performance_intent",
    "promotion_performance_plan_request",
    "promotion_performance_query",
]
