"""Agent discovery and Plan handoff for Analysis default values."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from .agent_intent_text import affirmative_intent_text


ANALYSIS_DEFAULT_DICTIONARY_NAME = "analysis_default_dictionary"
ANALYSIS_DEFAULT_DICTIONARY_SELECTOR = f"composite:{ANALYSIS_DEFAULT_DICTIONARY_NAME}"
_EXACT = frozenset(
    {
        ANALYSIS_DEFAULT_DICTIONARY_NAME,
        ANALYSIS_DEFAULT_DICTIONARY_SELECTOR,
        "analysis default dictionary",
        "analysis default values",
        "分析默认值字典",
        "默认值字典",
    }
)


ANALYSIS_DEFAULT_DICTIONARY_CAPABILITY: Mapping[str, Any] = {
    "name": ANALYSIS_DEFAULT_DICTIONARY_NAME,
    "domain": "analysis",
    "aliases": tuple(sorted(_EXACT - {ANALYSIS_DEFAULT_DICTIONARY_NAME})),
    "description": (
        "读取一个 App 的 Analysis SDK 默认值字典；只交付已登记的 api 与 "
        "cocoscreator 字符串数组，新增字典键失败关闭。"
    ),
    "boundaries": (
        "只交付已登记的 api 与 cocoscreator 字符串数组，新增字典键失败关闭。",
    ),
    "required_inputs": ("app",),
    "input_schema": {
        "app": {
            "type": "string|integer",
            "required": True,
            "nullable": False,
        }
    },
}


def analysis_default_dictionary_query(query: str) -> bool:
    selected = affirmative_intent_text(query)
    if selected in _EXACT:
        return True
    words = frozenset(re.findall(r"[a-z0-9_]+", selected))
    english = (
        "analysis" in words
        and "default" in words
        and bool(words & {"dictionary", "value", "values"})
    )
    return english or "默认值字典" in selected or (
        "分析" in selected and "默认值" in selected
    ) or (
        "分析" in selected and "字典" in selected
        and any(term in selected for term in ("默认", "缺省"))
    )


def analysis_default_dictionary_intent(query: str) -> bool:
    return analysis_default_dictionary_query(query)


def analysis_default_dictionary_plan_request(
    card: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "name": ANALYSIS_DEFAULT_DICTIONARY_NAME,
        "app": card.get("app", "<workspace-app-alias-or-positive-id>"),
    }


__all__ = [
    "ANALYSIS_DEFAULT_DICTIONARY_CAPABILITY",
    "ANALYSIS_DEFAULT_DICTIONARY_NAME",
    "ANALYSIS_DEFAULT_DICTIONARY_SELECTOR",
    "analysis_default_dictionary_intent",
    "analysis_default_dictionary_plan_request",
    "analysis_default_dictionary_query",
]
