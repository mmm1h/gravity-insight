"""Monetization Agent product and fail-closed adjacent-intent guard."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from .monetization_detail import SAFE_ROW_FIELDS


MONETIZATION_DETAIL_RAW_SELECTOR = ".".join(
    ("analysis", "monetization_detail", "list")
)
MONETIZATION_EXPORT_RAW_SELECTOR = ".".join(
    ("export", "analysis", "monetization_detail", "start")
)
MONETIZATION_SAFE_QUERY = "monetization_detail"
MONETIZATION_GAP_REASON = (
    "the request is outside the complete single-day Monetization "
    "Detail product boundary; rerun `gravity agent \"monetization details\"` "
    "and fill app/date for detail, while aggregated monetization performance "
    "is not registered"
)
MONETIZATION_DETAIL_NAME = "monetization_detail"
MONETIZATION_DETAIL_SELECTOR = f"composite:{MONETIZATION_DETAIL_NAME}"
MONETIZATION_DETAIL_REQUIRED_INPUTS = ("app", "date")

_ASCII_WORD = re.compile(r"[a-z0-9]+", re.IGNORECASE)
_COMPACT_SEPARATORS = re.compile(r"[\s_-]+")
_NEAR_RAW_SELECTOR = re.compile(
    r"(?<![a-z0-9_])(?:analysis\.)?monetization_detail"
    r"(?:\.list)?(?![a-z0-9_])",
    re.IGNORECASE,
)
_ENGLISH_STRONG_SHAPES = frozenset({"detail", "details", "directory"})
_ENGLISH_ADJACENT_SHAPES = frozenset({"list", "rows"})
_CHINESE_SHAPES = (
    "变现明细",
    "变现目录",
    "变现列表",
    "变现表现",
    "广告变现明细",
)
_EXACT_PRODUCT_INTENTS = frozenset(
    {
        MONETIZATION_DETAIL_NAME,
        MONETIZATION_DETAIL_SELECTOR,
        "monetization detail",
        "monetization details",
        "monetization directory",
        "monetization rows",
        "monetization list",
        "变现明细",
        "变现目录",
        "变现列表",
        "广告变现明细",
        "无标识变现明细",
    }
)
_ENGLISH_BLOCKED = frozenset(
    {
        "adid", "advertiser", "aggregate", "attribution", "client_id", "clientid",
        "dashboard", "delete", "device", "download", "export", "field",
        "fields", "filter", "group", "grouping", "ltv", "placement",
        "profile", "raw", "report", "revenue", "roi", "sort", "summary",
        "total", "trace_id", "traceid", "update", "user", "user_id",
        "event_user_id", "device_id", "where", "write", "order", "orders",
        "material", "materials", "promotion", "multidim", "saved", "segment",
        "journey", "pulse",
    }
)
_ENGLISH_OPEN_DIMENSIONS = frozenset(
    {
        "adid", "advertiser", "attribution", "client_id", "clientid",
        "device", "device_id", "event_user_id", "field", "fields",
        "filter", "group", "grouping", "ltv", "placement", "profile",
        "sort", "trace_id", "traceid", "user", "user_id", "where",
    }
)
_ENGLISH_HARD_BLOCKED = _ENGLISH_BLOCKED - _ENGLISH_OPEN_DIMENSIONS
_ENGLISH_NEGATIONS = frozenset(
    {"avoid", "cannot", "exclude", "never", "no", "not", "skip", "without"}
)
_CHINESE_OPEN_DIMENSIONS = (
    "用户", "设备", "标识", "筛选", "过滤", "条件", "分组", "排序", "字段", "画像", "归因",
)
_CHINESE_BLOCKED = (
    "不要", "无需", "不需要", "拒绝", "导出", "下载", "写入", "修改",
    "删除", "用户", "设备", "标识", "筛选", "过滤", "条件", "分组", "订单",
    "排序", "字段", "画像", "跨日", "日期范围", "时间范围", "汇总",
    "聚合", "总计", "表现", "报告", "报表", "收入", "归因", "看板", "原始",
    "素材", "推广", "多维", "保存分析", "分群", "旅程", "脉搏",
)
_RANGE_PHRASE = re.compile(
    r"\b(?:from|between|range|weekly|monthly|week|month)\b|\bto\b",
    re.IGNORECASE,
)
_EXACT_EXPERT_SELECTORS = frozenset(
    {
        MONETIZATION_DETAIL_RAW_SELECTOR,
        MONETIZATION_EXPORT_RAW_SELECTOR,
    }
)


def monetization_guard_blocks_operation_fallback(query: str) -> bool:
    """Claim only explicit detail-shaped requests and near-raw selectors."""

    selected = _normalize(query)
    if _is_exact_expert_selector(selected):
        return False
    if selected in _EXACT_PRODUCT_INTENTS:
        return True
    if monetization_open_dimension_query(selected):
        return False
    if _contains_near_raw_selector(selected):
        return True
    words = tuple(_ASCII_WORD.findall(selected))
    compact = _COMPACT_SEPARATORS.sub("", selected)
    return _english_detail_shape(words) or _chinese_detail_shape(compact)


def monetization_open_dimension_query(query: str) -> bool:
    """Route field/filter/group detail intent to the raw operation catalog."""

    selected = _normalize(query)
    words = tuple(_ASCII_WORD.findall(selected))
    compact = _COMPACT_SEPARATORS.sub("", selected)
    shaped = _contains_near_raw_selector(selected) or _english_detail_shape(words) or _chinese_detail_shape(compact)
    return shaped and _open_dimension_query(selected) and not _hard_blocked_query(selected)


def monetization_detail_query(query: str) -> bool:
    """Recognize the approved product while rejecting adjacent semantics."""

    selected = _normalize(query)
    if selected in _EXACT_PRODUCT_INTENTS:
        return True
    if _contains_near_raw_selector(selected):
        return False
    return (
        monetization_guard_blocks_operation_fallback(selected)
        and not _blocked_product_query(selected)
    )


def monetization_detail_input_template() -> dict[str, str]:
    return {
        "app": "<workspace-app-alias-or-positive-id>",
        "date": "<date:YYYY-MM-DD>",
    }


def monetization_detail_plan_request(
    _card: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "name": MONETIZATION_DETAIL_NAME,
        **monetization_detail_input_template(),
    }


def monetization_guard_safe_query(query: str) -> str:
    """Replace a claimed query before suffix values reach Agent output."""

    return (
        MONETIZATION_SAFE_QUERY
        if monetization_guard_blocks_operation_fallback(query)
        else query
    )


def _normalize(query: str) -> str:
    return " ".join(str(query or "").strip().casefold().split())


def _is_exact_expert_selector(selected: str) -> bool:
    return selected in _EXACT_EXPERT_SELECTORS


def _contains_near_raw_selector(selected: str) -> bool:
    return bool(_NEAR_RAW_SELECTOR.search(selected))


def _blocked_product_query(selected: str) -> bool:
    words = frozenset(_ASCII_WORD.findall(selected.replace("-", " ")))
    compact = _COMPACT_SEPARATORS.sub("", selected)
    return bool(
        words & (_ENGLISH_BLOCKED | _ENGLISH_NEGATIONS)
        or _RANGE_PHRASE.search(selected)
        or any(term in compact for term in _CHINESE_BLOCKED)
    )


def _open_dimension_query(selected: str) -> bool:
    words = frozenset(_ASCII_WORD.findall(selected.replace("-", " ")))
    compact = _COMPACT_SEPARATORS.sub("", selected)
    return bool(
        words & _ENGLISH_OPEN_DIMENSIONS
        or any(term in compact for term in _CHINESE_OPEN_DIMENSIONS)
    )


def _hard_blocked_query(selected: str) -> bool:
    words = frozenset(_ASCII_WORD.findall(selected.replace("-", " ")))
    compact = _COMPACT_SEPARATORS.sub("", selected)
    hard_chinese = tuple(
        term for term in _CHINESE_BLOCKED if term not in _CHINESE_OPEN_DIMENSIONS
    )
    return bool(
        words & (_ENGLISH_HARD_BLOCKED | _ENGLISH_NEGATIONS)
        or _RANGE_PHRASE.search(selected)
        or any(term in compact for term in hard_chinese)
    )


def _english_detail_shape(words: tuple[str, ...]) -> bool:
    if "monetization" not in words:
        return False
    if _ENGLISH_STRONG_SHAPES.intersection(words):
        return True
    return any(
        left == "monetization" and right in _ENGLISH_ADJACENT_SHAPES
        for left, right in zip(words, words[1:])
    )


def _chinese_detail_shape(compact: str) -> bool:
    return any(shape in compact for shape in _CHINESE_SHAPES)


MONETIZATION_DETAIL_CAPABILITY: Mapping[str, Any] = {
    "name": MONETIZATION_DETAIL_NAME,
    "domain": "analysis",
    "aliases": (
        "read one complete daily monetization detail",
        "list contracted ad monetization rows for one explicit day",
        "读取一个显式单日的完整已登记变现明细",
    ),
    "description": (
        "按显式 App 和单日完整读取已登记变现明细；固定返回字段 "
        + "/".join(SAFE_ROW_FIELDS)
        + "；未登记字段 fail closed。带字段、筛选或分组的请求交给 raw capability discovery。"
    ),
    "required_inputs": MONETIZATION_DETAIL_REQUIRED_INPUTS,
    "input_schema": {
        "app": {
            "type": "string|integer",
            "required": True,
            "nullable": False,
            "description": "Workspace App alias or positive App id.",
        },
        "date": {
            "type": "string",
            "format": "date",
            "required": True,
            "nullable": False,
            "description": "One explicit YYYY-MM-DD monetization window.",
        },
    },
    "plan_node_limits": {"max_pages": 1_000, "max_items": 100_000},
    "sensitive_query": True,
}


__all__ = [
    "MONETIZATION_DETAIL_RAW_SELECTOR",
    "MONETIZATION_DETAIL_CAPABILITY",
    "MONETIZATION_DETAIL_NAME",
    "MONETIZATION_DETAIL_REQUIRED_INPUTS",
    "MONETIZATION_DETAIL_SELECTOR",
    "MONETIZATION_EXPORT_RAW_SELECTOR",
    "MONETIZATION_GAP_REASON",
    "MONETIZATION_SAFE_QUERY",
    "monetization_guard_blocks_operation_fallback",
    "monetization_guard_safe_query",
    "monetization_open_dimension_query",
    "monetization_detail_input_template",
    "monetization_detail_plan_request",
    "monetization_detail_query",
]
