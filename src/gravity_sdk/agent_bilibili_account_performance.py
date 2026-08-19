"""Strict Agent handoff for Bilibili account performance."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any


BILIBILI_ACCOUNT_PERFORMANCE_NAME = "bilibili_account_performance"
BILIBILI_ACCOUNT_PERFORMANCE_SELECTOR = (
    f"composite:{BILIBILI_ACCOUNT_PERFORMANCE_NAME}"
)
BILIBILI_ACCOUNT_PERFORMANCE_REQUIRED_INPUTS = ("start", "end")

_EXACT = frozenset({
    BILIBILI_ACCOUNT_PERFORMANCE_NAME,
    BILIBILI_ACCOUNT_PERFORMANCE_SELECTOR,
    "bilibili account performance",
    "bilibili product performance",
    "b站账户投放表现",
    "b站产品投放表现",
    "哔哩哔哩账户投放表现",
})
_BLOCKED_ENGLISH = frozenset({
    "create", "delete", "download", "edit", "export", "optimize",
    "recommend", "strategy", "update", "upload", "write",
})
_BLOCKED_CHINESE = (
    "不要", "不看", "不查", "不查询", "导出", "下载", "创建", "删除",
    "修改", "优化", "建议", "策略", "更新", "上传", "写入",
)
_ACTION_ENGLISH = frozenset({
    "click", "clicks", "consume", "consumption", "cpc", "cpm", "ctr",
    "impression", "impressions", "performance", "report", "spend",
})
_SUBJECT_ENGLISH = frozenset({"account", "accounts", "advertiser", "product"})
_ACTION_CHINESE = (
    "表现", "效果", "报表", "曝光", "点击", "消耗", "花费", "ctr", "cpc", "cpm",
)
_SUBJECT_CHINESE = ("账户", "账号", "广告主", "产品")


BILIBILI_ACCOUNT_PERFORMANCE_CAPABILITY: Mapping[str, Any] = {
    "name": BILIBILI_ACCOUNT_PERFORMANCE_NAME,
    "domain": "promotion",
    "accepted_domains": ("promotion", "report"),
    "aliases": (
        "bilibili account performance",
        "bilibili product performance",
        "B站账户投放表现",
        "B站产品曝光点击与消耗",
    ),
    "description": (
        "按显式日期范围完整读取 B 站账户/产品的曝光、点击、CTR、CPC、CPM "
        "和资金消耗；不接收 App 或指标选择，已观察字段登记后全部暴露。"
    ),
    "boundaries": (
        "不接收 App 或指标选择，已观察字段登记后全部暴露。",
        "不用于跨平台推广表现。",
    ),
    "required_inputs": BILIBILI_ACCOUNT_PERFORMANCE_REQUIRED_INPUTS,
    "input_schema": {
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
    },
    "plan_node_limits": {"max_pages": 5, "max_items": 200},
}


def bilibili_account_performance_query(query: str) -> bool:
    """Recognize the specific read while excluding effects and advice."""

    selected = _normalize(query)
    if selected in _EXACT:
        return True
    return _claims_product(selected) and not _blocked(selected)


def bilibili_account_performance_product_query(name: str, query: str) -> bool:
    """Dispatch the adjacent strict product without adding spine branches."""

    return name == BILIBILI_ACCOUNT_PERFORMANCE_NAME and (
        bilibili_account_performance_query(query)
    )


def bilibili_account_performance_intent(query: str) -> bool:
    selected = _normalize(query)
    return selected in _EXACT or _claims_product(selected)


def bilibili_account_performance_blocks_operation_fallback(query: str) -> bool:
    return bilibili_account_performance_intent(query)


def bilibili_account_performance_input_template() -> dict[str, str]:
    return {
        "start": "<start:YYYY-MM-DD>",
        "end": "<end:YYYY-MM-DD>",
    }


def bilibili_account_performance_plan_request(
    card: Mapping[str, Any],
) -> dict[str, Any]:
    template = bilibili_account_performance_input_template()
    return {
        "name": BILIBILI_ACCOUNT_PERFORMANCE_NAME,
        **{key: card.get(key, value) for key, value in template.items()},
    }


def _claims_product(selected: str) -> bool:
    if not selected or selected.isascii() and " " not in selected and "." in selected:
        return False
    words = frozenset(re.findall(r"[a-z0-9_]+", selected))
    compact = re.sub(r"[\s_-]+", "", selected)
    platform = "bilibili" in words or "b station" in selected or any(
        term in compact for term in ("b站", "哔哩哔哩")
    )
    subject = bool(words & _SUBJECT_ENGLISH) or any(
        term in compact for term in _SUBJECT_CHINESE
    )
    action = bool(words & _ACTION_ENGLISH) or any(
        term in compact for term in _ACTION_CHINESE
    )
    return platform and subject and action


def _blocked(selected: str) -> bool:
    words = frozenset(re.findall(r"[a-z0-9_]+", selected))
    compact = re.sub(r"\s+", "", selected)
    return bool(words & _BLOCKED_ENGLISH) or any(
        term in compact for term in _BLOCKED_CHINESE
    )


def _normalize(query: str) -> str:
    return " ".join(str(query or "").strip().casefold().split())


__all__ = [
    "BILIBILI_ACCOUNT_PERFORMANCE_CAPABILITY",
    "BILIBILI_ACCOUNT_PERFORMANCE_NAME",
    "BILIBILI_ACCOUNT_PERFORMANCE_REQUIRED_INPUTS",
    "BILIBILI_ACCOUNT_PERFORMANCE_SELECTOR",
    "bilibili_account_performance_blocks_operation_fallback",
    "bilibili_account_performance_input_template",
    "bilibili_account_performance_intent",
    "bilibili_account_performance_plan_request",
    "bilibili_account_performance_product_query",
    "bilibili_account_performance_query",
]
