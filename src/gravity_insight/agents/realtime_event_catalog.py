"""Agent discovery and Plan handoff for the realtime-event catalog."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from .intent_text import affirmative_intent_text
from ..realtime_event_diagnostics import FILTER_FIELDS, realtime_property_fields_schema, realtime_property_filter_schema


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
        "读取一个 App 显式短窗口的实时事件与 SDK/版本诊断；"
        "普通筛选按 AND，默认 event_type=profile；无可证明分页。"
    ),
    "boundaries": (
        "单次最多1000行、窗口最多24小时，内容完整性unknown；空结果不证明未上报。",
        "默认 filters.event_type=profile，不是全量事件查询。",
        "属性只允许元数据与隐私校验后的显式标量选择；不自动开启采集。",
    ),
    "required_inputs": ("app", "start", "end"),
    "input_schema": {
        "app": {"type": "string|integer", "required": True, "nullable": False},
        "start": {"type": "string", "required": True, "nullable": False},
        "end": {"type": "string", "required": True, "nullable": False},
        "event_type": {"type": "string", "required": False, "nullable": False},
        **{key: {"type": "string", "required": False, "nullable": False} for key in FILTER_FIELDS if key != "properties"},
        "properties": {"type": "array", "required": False, "nullable": False,
                       "machine_schema": realtime_property_filter_schema(),
                       "description": "至多一个 field/datatype/operator=EQUALS/values=[单值] 对象；datatype 必须等于元数据，LIST/DICT 比较未验证。"},
        "property_fields": {"type": "array", "required": False, "nullable": False,
                            "machine_schema": realtime_property_fields_schema(),
                            "description": "至多20个显式、安全的标量属性元数据英文名；不会返回raw_properties整体。"},
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
    for name in ("event_type", *FILTER_FIELDS, "property_fields"):
        if name in card and card[name] is not None:
            request[name] = card[name]
    return request


__all__ = [
    "REALTIME_EVENT_CATALOG_CAPABILITY",
    "REALTIME_EVENT_CATALOG_NAME",
    "REALTIME_EVENT_CATALOG_SELECTOR",
    "realtime_event_catalog_intent",
    "realtime_event_catalog_plan_request",
    "realtime_event_catalog_query",
]
