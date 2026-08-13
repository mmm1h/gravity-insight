"""Strict, value-free Agent handoff for Order Directory v1."""

from __future__ import annotations

from collections.abc import Mapping
import re
from typing import Any


ORDER_DIRECTORY_NAME = "order_directory"
ORDER_DIRECTORY_SELECTOR = f"composite:{ORDER_DIRECTORY_NAME}"
ORDER_DIRECTORY_RAW_SELECTORS = frozenset(
    {
        ".".join(("analysis", "order_detail", "list")),
        ".".join(("analysis", "order_split_detail", "list")),
    }
)
ORDER_DIRECTORY_REQUIRED_INPUTS = ("app", "date")
ORDER_DIRECTORY_SAFE_FIELDS = (
    "Amount",
    "BackAmount",
    "Status",
    "CreateTime",
)

_ASCII_WORD = re.compile(r"[a-z0-9_]+", re.IGNORECASE)
_COMPACT_SEPARATORS = re.compile(r"[\s_-]+")
_ENGLISH_NEGATION_PHRASE = re.compile(
    r"\b(?:don['’]?t|do\s+not|cannot|can['’]?t|can\s+not|"
    r"won['’]?t|will\s+not|should\s+not|must\s+not)\b"
)
_CHINESE_BIE_NEGATION = re.compile(
    r"(?:^|请|麻烦|[\s，,。；;！!])别(?:再)?"
    r"(?=$|[\s，,。；;！!]|查|看|读|跑|执行|获取|做|分析|输出|拉取|展示|列)"
)
_CHINESE_FEI_NEGATION = re.compile(
    r"(?:^|[\s，,。；;！!]|是)非订单(?:目录|明细|详情|列表|日报|报表|报告)"
)

_EXACT_INTENTS = frozenset(
    {
        ORDER_DIRECTORY_NAME,
        ORDER_DIRECTORY_SELECTOR,
        "order directory",
        "order detail",
        "order details",
        "order detail report",
        "order details report",
        "daily order directory",
        "daily order report",
        "list daily orders",
        "list order details",
        "ordinary order directory",
        "ordinary order details",
        "订单目录",
        "订单明细",
        "订单详情",
        "订单列表",
        "订单日报",
        "单日订单报表",
        "查看订单明细",
        "普通订单列表",
        "父订单详情",
    }
)
_ENGLISH_ORDER = frozenset({"order", "orders"})
_ENGLISH_DETAIL = frozenset({"detail", "details", "directory"})
_ENGLISH_LISTING = frozenset({"list", "listing", "report", "reports"})
_ENGLISH_DAILY = frozenset({"daily", "day"})
_ENGLISH_ORDINARY = frozenset({"ordinary", "parent"})
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
        "audience",
        "best",
        "business",
        "campaign",
        "clientid",
        "client_id",
        "cohort",
        "condition",
        "conditions",
        "create",
        "creative",
        "dashboard",
        "delete",
        "download",
        "edit",
        "export",
        "favorite",
        "favourite",
        "field",
        "fields",
        "filter",
        "filters",
        "history",
        "income",
        "insert",
        "journey",
        "layout",
        "material",
        "materials",
        "monetization",
        "month",
        "monthly",
        "multidim",
        "multidimensional",
        "mutate",
        "net",
        "optimization",
        "optimize",
        "operating",
        "operational",
        "operations",
        "paid",
        "permission",
        "permissions",
        "profit",
        "promotion",
        "pulse",
        "publish",
        "rank",
        "ranking",
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
        "sort",
        "sorting",
        "split",
        "stored",
        "strategy",
        "success",
        "successful",
        "succeeded",
        "template",
        "trace",
        "traceid",
        "trace_id",
        "ui",
        "update",
        "upload",
        "user",
        "week",
        "weekly",
        "where",
        "window",
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
    "traceid",
    "clientid",
    "拆单",
    "订单拆分",
    "追踪",
    "追溯",
    "链路",
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
    "保存",
    "已存",
    "退款",
    "退费",
    "净收入",
    "净营收",
    "利润",
    "支付成功",
    "成功订单",
    "订单成功",
    "是否成功",
    "归因",
    "经营",
    "业务",
    "脉搏",
    "脉动",
    "用户旅程",
    "单用户",
    "用户",
    "变现",
    "多维",
    "多个维度",
    "交叉维度",
    "维度交叉",
    "推广",
    "投放",
    "素材",
    "创意",
    "广告",
    "模板",
    "看板",
    "收藏",
    "权限",
    "页面",
    "界面",
    "布局",
    "分群",
    "人群",
    "受众",
    "原始",
    "筛选",
    "过滤",
    "条件",
    "排序",
    "字段",
    "跨日",
    "日期范围",
    "时间范围",
    "时间窗",
    "周报",
    "月报",
    "历史订单",
    "策略",
    "优化",
    "建议",
    "推荐",
    "排名",
    "排行",
)
_CHINESE_BLOCKING_TERMS = (*_CHINESE_NEGATIONS, *_CHINESE_BLOCKED)


ORDER_DIRECTORY_CAPABILITY: Mapping[str, Any] = {
    "name": ORDER_DIRECTORY_NAME,
    "domain": "analysis",
    "aliases": (
        "read one complete daily order directory",
        "list ordinary order detail for one explicit day",
        "读取一个显式单日的完整普通订单目录",
        "列出单日普通订单的无标识物理明细",
    ),
    "description": (
        "按显式 App 和单日完整读取普通订单目录；每行只保留 "
        "Amount/BackAmount/Status/CreateTime，不返回任何订单或用户标识，"
        "不解释退款、净收入或支付成功。"
    ),
    "required_inputs": ORDER_DIRECTORY_REQUIRED_INPUTS,
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
            "description": "One explicit YYYY-MM-DD order-directory window.",
        },
    },
    "plan_node_limits": {"max_pages": 1_000, "max_items": 100_000},
    "sensitive_query": True,
}


def order_directory_query(query: str) -> bool:
    """Recognize one explicit read while rejecting every adjacent product."""

    selected = _normalize(query)
    if selected in _EXACT_INTENTS:
        return True
    return _claims_product(selected) and not _blocked(selected)


def order_directory_intent(query: str) -> bool:
    """Return positive Directory evidence without applying conflict policy."""

    selected = _normalize(query)
    words = frozenset(_ASCII_WORD.findall(selected))
    return (
        selected in _EXACT_INTENTS
        or bool(words & _ENGLISH_ORDER and "directory" in words)
        or "订单目录" in _compact(selected)
    )


def order_directory_blocks_operation_fallback(query: str) -> bool:
    """Claim product-shaped conflicts before generic operation discovery."""

    selected = _normalize(query)
    if selected in ORDER_DIRECTORY_RAW_SELECTORS:
        return False
    return selected in _EXACT_INTENTS or _claims_product(selected)


def order_directory_adjacent_intent(query: str) -> bool:
    """Identify Directory wording reused by adjacent product recognizers."""

    selected = _normalize(query)
    words = frozenset(_ASCII_WORD.findall(selected))
    compact = _compact(selected)
    return bool(
        words & _ENGLISH_ORDER and words & _ENGLISH_DETAIL
    ) or _contains_any(
        compact, ("订单目录", "订单明细", "订单详情", "订单列表")
    )


def order_directory_input_template() -> dict[str, str]:
    """Return literal slots without selecting an App or date."""

    return {
        "app": "<workspace-app-alias-or-positive-id>",
        "date": "<date:YYYY-MM-DD>",
    }


def order_directory_safe_query(query: str) -> str:
    """Replace product-shaped language before Agent output can echo values."""

    return (
        ORDER_DIRECTORY_NAME
        if order_directory_blocks_operation_fallback(query)
        else query
    )


def order_directory_plan_request(_card: Mapping[str, Any]) -> dict[str, Any]:
    """Build the complete value-free request copied into Plan v1."""

    return {"name": ORDER_DIRECTORY_NAME, **order_directory_input_template()}


def _normalize(query: str) -> str:
    return " ".join(str(query or "").strip().casefold().split())


def _compact(value: str) -> str:
    return _COMPACT_SEPARATORS.sub("", value.casefold())


def _claims_product(selected: str) -> bool:
    if not selected or selected in ORDER_DIRECTORY_RAW_SELECTORS:
        return False
    if _contains_raw_selector(selected):
        return True
    if selected.isascii() and " " not in selected and "." in selected:
        return False
    words = frozenset(_ASCII_WORD.findall(selected.replace("-", " ")))
    compact = _compact(selected)
    return _english_product_shape(words) or _chinese_product_shape(compact)


def _english_product_shape(words: frozenset[str]) -> bool:
    if not words & _ENGLISH_ORDER:
        return False
    return bool(
        words
        & (
            _ENGLISH_DETAIL
            | _ENGLISH_LISTING
            | _ENGLISH_BLOCKED
            | _ENGLISH_NEGATIONS
        )
    )


def _chinese_product_shape(compact: str) -> bool:
    if "订单" not in compact:
        return False
    return bool(
        _contains_any(
            compact,
            ("订单目录", "订单明细", "订单详情", "订单列表", "订单日报"),
        )
        or _contains_any(compact, ("报表", "报告"))
        or _contains_any(compact, _CHINESE_BLOCKING_TERMS)
    )


def _blocked(selected: str) -> bool:
    words = frozenset(_ASCII_WORD.findall(selected.replace("-", " ")))
    compact = _compact(selected)
    return bool(
        words & (_ENGLISH_BLOCKED | _ENGLISH_NEGATIONS)
        or _contains_any(compact, _CHINESE_BLOCKING_TERMS)
        or _ENGLISH_NEGATION_PHRASE.search(selected)
        or _CHINESE_BIE_NEGATION.search(selected)
        or _CHINESE_FEI_NEGATION.search(selected)
        or _contains_raw_selector(selected)
        or _explicit_english_range(words)
        or _ambiguous_report(selected, words, compact)
    )


def _explicit_english_range(words: frozenset[str]) -> bool:
    return "between" in words or {"from", "to"}.issubset(words)


def _contains_raw_selector(selected: str) -> bool:
    return any(selector in selected for selector in ORDER_DIRECTORY_RAW_SELECTORS)


def _ambiguous_report(
    selected: str, words: frozenset[str], compact: str
) -> bool:
    if selected in _EXACT_INTENTS:
        return False
    english = bool(
        words & _ENGLISH_ORDER
        and words & _ENGLISH_LISTING
        and not words & (_ENGLISH_DETAIL | _ENGLISH_DAILY | _ENGLISH_ORDINARY)
    )
    chinese = bool(
        "订单" in compact
        and _contains_any(compact, ("报表", "报告"))
        and not _contains_any(
            compact,
            ("单日", "每日", "日报", "目录", "明细", "详情", "列表"),
        )
    )
    return english or chinese


def _contains_any(value: str, terms: tuple[str, ...]) -> bool:
    return any(term in value for term in terms)


__all__ = [
    "ORDER_DIRECTORY_CAPABILITY",
    "ORDER_DIRECTORY_NAME",
    "ORDER_DIRECTORY_RAW_SELECTORS",
    "ORDER_DIRECTORY_REQUIRED_INPUTS",
    "ORDER_DIRECTORY_SAFE_FIELDS",
    "ORDER_DIRECTORY_SELECTOR",
    "order_directory_blocks_operation_fallback",
    "order_directory_input_template",
    "order_directory_adjacent_intent",
    "order_directory_intent",
    "order_directory_plan_request",
    "order_directory_query",
    "order_directory_safe_query",
]
