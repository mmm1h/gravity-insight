"""Strict, value-free Agent handoff for Order Split Trace v1."""

from __future__ import annotations

from collections.abc import Mapping
import re
from typing import Any

from .agent_intent_text import affirmative_intent_text


ORDER_SPLIT_TRACE_NAME = "order_split_trace"
ORDER_SPLIT_TRACE_SELECTOR = f"composite:{ORDER_SPLIT_TRACE_NAME}"
ORDER_SPLIT_TRACE_RAW_SELECTOR = ".".join(
    ("analysis", "order_split_detail", "list")
)
ORDER_SPLIT_TRACE_REQUIRED_INPUTS = ("app", "date", "trace_id")

_ASCII_WORD = re.compile(r"[a-z0-9_]+", re.IGNORECASE)
_COMPACT_SEPARATORS = re.compile(r"[\s_-]+")
_ENGLISH_NEGATION_PHRASE = re.compile(
    r"\b(?:don['’]?t|do\s+not|cannot|can['’]?t|can\s+not|"
    r"won['’]?t|will\s+not|should\s+not|must\s+not)\b"
)
_CHINESE_BIE_NEGATION = re.compile(
    r"(?:^|请|麻烦|[\s，,。；;！!])别(?:再)?"
    r"(?=$|[\s，,。；;！!]|查|看|读|跑|执行|获取|做|分析|输出|拉取|展示|拆|追)"
)

_EXACT_INTENTS = frozenset(
    {
        ORDER_SPLIT_TRACE_NAME,
        ORDER_SPLIT_TRACE_SELECTOR,
        "order split trace",
        "split order trace",
        "order split detail by trace id",
        "order split details by trace id",
        "split order detail by trace id",
        "split order details by trace id",
        "拆单追踪",
        "拆单追溯",
        "按traceid查拆单明细",
        "按trace id查拆单明细",
        "用traceid查拆单明细",
        "用trace id查拆单明细",
    }
)
_ENGLISH_ORDER = frozenset({"order", "orders"})
_ENGLISH_SPLIT = frozenset({"split", "splits"})
_ENGLISH_TRACE = frozenset({"trace", "traceid", "trace_id"})
_ENGLISH_NEGATIONS = frozenset(
    {
        "avoid",
        "cannot",
        "exclude",
        "never",
        "no",
        "not",
        "skip",
        "without",
    }
)
_ENGLISH_BLOCKED = frozenset(
    {
        "ad",
        "ads",
        "advertising",
        "advice",
        "attribution",
        "best",
        "campaign",
        "catalog",
        "create",
        "creative",
        "dashboard",
        "delete",
        "directory",
        "download",
        "edit",
        "export",
        "favorite",
        "favourite",
        "income",
        "insert",
        "journey",
        "layout",
        "material",
        "materials",
        "monetization",
        "mutate",
        "net",
        "optimization",
        "optimize",
        "permission",
        "permissions",
        "profit",
        "promotion",
        "publish",
        "raw",
        "recommend",
        "recommendation",
        "refund",
        "refunded",
        "refunds",
        "remove",
        "revenue",
        "save",
        "saved",
        "segment",
        "segments",
        "snapshot",
        "stored",
        "strategy",
        "template",
        "ui",
        "update",
        "upload",
        "user",
        "audience",
        "cohort",
        "write",
    }
)
_CHINESE_NEGATIONS = (
    "不要",
    "无需",
    "无须",
    "不需要",
    "不必",
    "不做",
    "不用",
    "避免",
    "排除",
    "不是",
    "并非",
    "不想看",
    "不想要",
    "拒绝",
    "不看",
    "不查",
    "不查询",
)
_CHINESE_BLOCKED = (
    "归因",
    "保存",
    "已存",
    "分群",
    "人群",
    "受众",
    "用户旅程",
    "单用户",
    "用户",
    "订单目录",
    "订单列表",
    "普通订单",
    "变现",
    "推广",
    "投放",
    "素材",
    "创意",
    "模板",
    "看板",
    "页面",
    "界面",
    "权限",
    "布局",
    "收藏",
    "导出",
    "下载",
    "写入",
    "写",
    "修改",
    "更新",
    "创建",
    "删除",
    "上传",
    "发布",
    "插入",
    "移除",
    "退款",
    "退费",
    "净收入",
    "净营收",
    "利润",
    "策略",
    "优化",
    "建议",
    "推荐",
    "原始",
    "快照",
)
_CHINESE_TRACE = ("追踪", "追溯", "链路")
_CHINESE_DETAIL = ("明细", "详情")
_CHINESE_BLOCKING_TERMS = (*_CHINESE_NEGATIONS, *_CHINESE_BLOCKED)


ORDER_SPLIT_TRACE_CAPABILITY: Mapping[str, Any] = {
    "name": ORDER_SPLIT_TRACE_NAME,
    "domain": "analysis",
    "aliases": (
        "read one split-order detail by an explicit TraceID",
        "inspect a bounded order-to-split trace",
        "按显式 TraceID 读取一次订单到拆单的明细",
        "有界追踪单日拆单明细",
    ),
    "description": (
        "按显式 App、单日和敏感 TraceID 完整扫描父订单并精确匹配一次拆单明细；"
        "不返回父子标识，不解释退款、净收入、归因或订单状态。"
    ),
    "boundaries": (
        "不返回父子标识，不解释退款、净收入、归因或订单状态。",
        "不列出单日普通订单目录。",
        "不从自然语言复制追踪标识。",
    ),
    "required_inputs": ORDER_SPLIT_TRACE_REQUIRED_INPUTS,
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
            "description": "One explicit YYYY-MM-DD parent-order window.",
        },
        "trace_id": {
            "type": "string",
            "required": True,
            "nullable": False,
            "sensitive": True,
            "min_length": 1,
            "max_length": 256,
            "description": "Explicit sensitive TraceID; never inferred from query text.",
        },
    },
    "plan_node_limits": {"max_pages": 1_000, "max_items": 100_000},
    "sensitive_query": True,
}


def order_split_trace_query(query: str) -> bool:
    """Recognize an explicit read while rejecting every adjacent product."""

    selected = affirmative_intent_text(query)
    if selected in _EXACT_INTENTS:
        return True
    return _claims_product(selected) and not _blocked(selected)


def order_split_trace_intent(query: str) -> bool:
    """Return positive split-trace evidence without applying conflict policy."""

    selected = affirmative_intent_text(query)
    return selected in _EXACT_INTENTS or _claims_product(selected)


def order_split_trace_blocks_operation_fallback(query: str) -> bool:
    """Claim product-shaped conflicts so they cannot become raw child cards."""

    selected = _normalize(query)
    if selected == ORDER_SPLIT_TRACE_RAW_SELECTOR:
        return False
    return selected in _EXACT_INTENTS or _claims_product(selected)


def order_split_trace_input_template() -> dict[str, str]:
    """Return fixed slots without copying a TraceID from natural language."""

    return {
        "app": "<workspace-app-alias-or-positive-id>",
        "date": "<date:YYYY-MM-DD>",
        "trace_id": "<explicit-sensitive-trace-id>",
    }


def order_split_trace_safe_query(query: str) -> str:
    """Replace product-shaped natural language before Agent output echoes it."""

    return (
        ORDER_SPLIT_TRACE_NAME
        if order_split_trace_blocks_operation_fallback(query)
        else query
    )


def order_split_trace_plan_request(_card: Mapping[str, Any]) -> dict[str, Any]:
    """Build a complete value-free request; callers replace every placeholder."""

    return {"name": ORDER_SPLIT_TRACE_NAME, **order_split_trace_input_template()}


def _normalize(query: str) -> str:
    return " ".join(str(query or "").strip().casefold().split())


def _compact(value: str) -> str:
    return _COMPACT_SEPARATORS.sub("", value.casefold())


def _claims_product(selected: str) -> bool:
    if not selected or selected == ORDER_SPLIT_TRACE_RAW_SELECTOR:
        return False
    if selected.isascii() and " " not in selected and "." in selected:
        return False
    words = frozenset(_ASCII_WORD.findall(selected.replace("-", " ")))
    compact = _compact(selected)
    order_split = bool(words & _ENGLISH_ORDER and words & _ENGLISH_SPLIT)
    split_trace = bool(words & _ENGLISH_TRACE) or _contains_any(
        compact, _CHINESE_TRACE
    )
    chinese_split = _chinese_split_intent(compact)
    chinese_detail = _contains_any(compact, _CHINESE_DETAIL)
    explicit_trace_id = "traceid" in compact
    return bool(
        order_split and split_trace
        or chinese_split and split_trace
        or chinese_split and chinese_detail and explicit_trace_id
    )


def _chinese_split_intent(compact: str) -> bool:
    return (
        "拆单" in compact
        or "订单拆分" in compact
        or re.search(r"拆成.{0,8}订单", compact) is not None
    )


def _blocked(selected: str) -> bool:
    words = frozenset(_ASCII_WORD.findall(selected.replace("-", " ")))
    compact = _compact(selected)
    return bool(
        words & (_ENGLISH_BLOCKED | _ENGLISH_NEGATIONS)
        or _contains_any(compact, _CHINESE_BLOCKING_TERMS)
        or _ENGLISH_NEGATION_PHRASE.search(selected)
        or _CHINESE_BIE_NEGATION.search(selected)
    )


def _contains_any(value: str, terms: tuple[str, ...]) -> bool:
    return any(term in value for term in terms)


__all__ = [
    "ORDER_SPLIT_TRACE_CAPABILITY",
    "ORDER_SPLIT_TRACE_NAME",
    "ORDER_SPLIT_TRACE_RAW_SELECTOR",
    "ORDER_SPLIT_TRACE_REQUIRED_INPUTS",
    "ORDER_SPLIT_TRACE_SELECTOR",
    "order_split_trace_blocks_operation_fallback",
    "order_split_trace_input_template",
    "order_split_trace_intent",
    "order_split_trace_plan_request",
    "order_split_trace_query",
    "order_split_trace_safe_query",
]
