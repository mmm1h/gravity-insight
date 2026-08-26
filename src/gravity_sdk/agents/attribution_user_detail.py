"""Strict Agent discovery and Plan handoff for F40 attribution detail."""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping
from typing import Any

from .intent_text import affirmative_intent_text


ATTRIBUTION_USER_DETAIL_NAME = "attribution_user_detail"
ATTRIBUTION_USER_DETAIL_SELECTOR = f"composite:{ATTRIBUTION_USER_DETAIL_NAME}"
ATTRIBUTION_USER_DETAIL_REQUIRED_INPUTS = ("app", "device_id")
_EXACT = frozenset(
    {
        ATTRIBUTION_USER_DETAIL_NAME,
        ATTRIBUTION_USER_DETAIL_SELECTOR,
        "single user attribution detail",
        "user attribution detail",
        "user attribution source",
        "单用户归因明细",
        "用户归因明细",
        "用户归因来源",
    }
)
_BLOCKED = (
    "aggregate", "performance", "summary", "configuration", "mapping",
    "汇总", "表现", "聚合", "配置", "映射", "回溯设置",
)


ATTRIBUTION_USER_DETAIL_CAPABILITY: Mapping[str, Any] = {
    "name": ATTRIBUTION_USER_DETAIL_NAME,
    "domain": "attribution",
    "aliases": (
        "read one registered testing device's attribution detail",
        "drill into one caller-selected user's attribution source",
        "读取一个已登记测试设备的归因明细",
        "下钻一个调用方选定用户的归因来源",
    ),
    "description": (
        "按显式 App 与测试设备目录内部行 ID 读取单用户归因详情；返回已登记的 "
        "device_white 以及 attribution/postback/pay 容器，后续出现未登记 item 字段时失败关闭。"
    ),
    "boundaries": (
        "只读单用户归因详情，不返回四组归因表现面板。",
        "device_id 必须来自测试设备目录内部行，不是原始设备标识。",
    ),
    "required_inputs": ATTRIBUTION_USER_DETAIL_REQUIRED_INPUTS,
    "input_schema": {
        "app": {
            "type": "string|integer",
            "required": True,
            "nullable": False,
            "description": "Workspace App alias or positive App id.",
        },
        "device_id": {
            "type": "integer",
            "required": True,
            "nullable": False,
            "minimum": 1,
            "sensitive": True,
            "description": (
                "Internal row id selected from app.testing_tool.list; not a raw device identifier."
            ),
        },
    },
    "plan_node_limits": {"max_pages": 1, "max_items": 1000},
    "sensitive_query": True,
}


def attribution_user_detail_query(query: str) -> bool:
    selected = affirmative_intent_text(query)
    if selected in _EXACT:
        return True
    if any(term in selected for term in _BLOCKED):
        return False
    words = frozenset(re.findall(r"[a-z0-9_]+", selected))
    english = (
        "attribution" in words
        and bool(words & {"user", "users", "device"})
        and bool(words & {"detail", "details", "drill", "source"})
    )
    chinese = (
        ("用户" in selected or "设备" in selected)
        and "归因" in selected
        and any(term in selected for term in ("明细", "来源", "下钻", "回传"))
    )
    return english or chinese


def attribution_user_detail_input_template() -> dict[str, Any]:
    return {
        "app": "<workspace-app-alias-or-positive-id>",
        "device_id": "<testing-device-row-id:positive-integer>",
    }


def attribution_user_detail_plan_request(
    card: Mapping[str, Any],
) -> dict[str, Any]:
    template = attribution_user_detail_input_template()
    return {
        "name": ATTRIBUTION_USER_DETAIL_NAME,
        **{
            key: copy.deepcopy(card.get(key, value))
            for key, value in template.items()
        },
    }


__all__ = [
    "ATTRIBUTION_USER_DETAIL_CAPABILITY",
    "ATTRIBUTION_USER_DETAIL_NAME",
    "ATTRIBUTION_USER_DETAIL_REQUIRED_INPUTS",
    "ATTRIBUTION_USER_DETAIL_SELECTOR",
    "attribution_user_detail_input_template",
    "attribution_user_detail_plan_request",
    "attribution_user_detail_query",
]
