"""Agent discovery and Plan handoff for the realtime-event catalog."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from .intent_text import affirmative_intent_text


REALTIME_EVENT_CATALOG_NAME = "realtime_event_catalog"
REALTIME_EVENT_CATALOG_SELECTOR = f"composite:{REALTIME_EVENT_CATALOG_NAME}"
_EXACT = frozenset(
    {
        REALTIME_EVENT_CATALOG_NAME,
        REALTIME_EVENT_CATALOG_SELECTOR,
        "realtime event catalog",
        "real time event catalog",
        "real-time event catalog",
        "查询实时事件目录",
        "实时事件目录",
    }
)


REALTIME_EVENT_CATALOG_CAPABILITY: Mapping[str, Any] = {
    "name": REALTIME_EVENT_CATALOG_NAME,
    "domain": "analysis",
    "aliases": tuple(sorted(_EXACT - {REALTIME_EVENT_CATALOG_NAME})),
    "description": (
        "读取一个 App 在显式时间窗内的实时事件目录第一页；"
        "默认 filters.event_type=profile。响应无 page_info。"
    ),
    "boundaries": (
        "只返回第一页；响应无 page_info。",
        "默认 filters.event_type=profile，不是全量事件查询。",
    ),
    "required_inputs": ("app", "start", "end"),
    "input_schema": {
        "app": {"type": "string|integer", "required": True, "nullable": False},
        "start": {"type": "string", "required": True, "nullable": False},
        "end": {"type": "string", "required": True, "nullable": False},
        "event_type": {"type": "string", "required": False, "nullable": False},
    },
}


def realtime_event_catalog_query(query: str) -> bool:
    selected = affirmative_intent_text(query)
    if selected in _EXACT:
        return True
    words = frozenset(re.findall(r"[a-z0-9_]+", selected))
    english = (
        "event" in words
        and "catalog" in words
        and (("real" in words and "time" in words) or "realtime" in words)
    )
    return english or "实时事件目录" in selected or (
        "实时" in selected
        and any(term in selected for term in ("目录", "上报"))
        and any(term in selected for term in ("目录", "项"))
    )


def realtime_event_catalog_intent(query: str) -> bool:
    return realtime_event_catalog_query(query)


def realtime_event_catalog_plan_request(card: Mapping[str, Any]) -> dict[str, Any]:
    request = {
        "name": REALTIME_EVENT_CATALOG_NAME,
        "app": card.get("app", "<workspace-app-alias-or-positive-id>"),
        "start": card.get("start", "<YYYY-MM-DD HH:MM:SS>"),
        "end": card.get("end", "<YYYY-MM-DD HH:MM:SS>"),
    }
    if card.get("event_type"):
        request["event_type"] = card["event_type"]
    return request


__all__ = [
    "REALTIME_EVENT_CATALOG_CAPABILITY",
    "REALTIME_EVENT_CATALOG_NAME",
    "REALTIME_EVENT_CATALOG_SELECTOR",
    "realtime_event_catalog_intent",
    "realtime_event_catalog_plan_request",
    "realtime_event_catalog_query",
]
