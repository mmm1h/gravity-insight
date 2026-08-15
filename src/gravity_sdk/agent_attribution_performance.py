"""Strict, value-free Agent handoff for Attribution Performance v1."""

from __future__ import annotations

import copy
from collections.abc import Mapping
import re
from typing import Any

from .agent_intent_text import affirmative_intent_text


ATTRIBUTION_PERFORMANCE_NAME = "attribution_performance"
ATTRIBUTION_PERFORMANCE_SELECTOR = f"composite:{ATTRIBUTION_PERFORMANCE_NAME}"
ATTRIBUTION_PERFORMANCE_REQUIRED_INPUTS = ("app", "start", "end")

_EXACT = frozenset(
    {
        ATTRIBUTION_PERFORMANCE_NAME,
        ATTRIBUTION_PERFORMANCE_SELECTOR,
        "attribution performance",
        "attribution aggregate",
        "attribution summary",
        "归因表现",
        "归因聚合",
        "归因汇总",
    }
)
_BLOCKED = (
    "configuration", "config", "mapping", "lookback", "rule", "setting",
    "single user", "user detail", "device", "export", "write", "update",
    "配置", "映射", "回溯", "规则", "设置", "窗口", "单用户", "用户明细",
    "设备", "导出", "写入", "更新",
)


ATTRIBUTION_PERFORMANCE_CAPABILITY: Mapping[str, Any] = {
    "name": ATTRIBUTION_PERFORMANCE_NAME,
    "domain": "attribution",
    "aliases": (
        "read governed attribution performance",
        "read attribution aggregate results",
        "读取受治理的归因表现",
        "汇总归因新增、激活和付费结果",
    ),
    "description": (
        "按显式 App 和日期读取前端四组归因表现面板，覆盖归因新增、激活、"
        "注册、付费、曝光和点击；不返回单用户明细。"
    ),
    "required_inputs": ATTRIBUTION_PERFORMANCE_REQUIRED_INPUTS,
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
    },
    "plan_node_limits": {"max_pages": 1, "max_items": 100_000},
}


def attribution_performance_query(query: str) -> bool:
    """Recognize aggregate attribution reads while rejecting config/detail intents."""

    selected = affirmative_intent_text(query)
    if selected in _EXACT:
        return True
    return attribution_performance_intent(query) and not any(
        term in selected for term in _BLOCKED
    )


def attribution_performance_intent(query: str) -> bool:
    """Return positive attribution-performance evidence for conflict routing."""

    selected = affirmative_intent_text(query)
    if selected in _EXACT:
        return True
    words = frozenset(re.findall(r"[a-z0-9_]+", selected))
    english = bool(words & {"attribution", "attributed"}) and bool(
        words & {"aggregate", "aggregated", "performance", "summary", "report"}
    )
    chinese = "归因" in selected and any(
        term in selected for term in ("汇总", "表现", "聚合", "新增", "激活", "付费")
    )
    return english or chinese


def attribution_performance_input_template() -> dict[str, Any]:
    return {
        "app": "<workspace-app-alias-or-positive-id>",
        "start": "<start:YYYY-MM-DD>",
        "end": "<end:YYYY-MM-DD>",
    }


def attribution_performance_plan_request(
    card: Mapping[str, Any],
) -> dict[str, Any]:
    template = attribution_performance_input_template()
    return {
        "name": ATTRIBUTION_PERFORMANCE_NAME,
        **{
            key: copy.deepcopy(card.get(key, value))
            for key, value in template.items()
        },
    }


__all__ = [
    "ATTRIBUTION_PERFORMANCE_CAPABILITY",
    "ATTRIBUTION_PERFORMANCE_NAME",
    "ATTRIBUTION_PERFORMANCE_REQUIRED_INPUTS",
    "attribution_performance_input_template",
    "attribution_performance_intent",
    "attribution_performance_plan_request",
    "attribution_performance_query",
]
