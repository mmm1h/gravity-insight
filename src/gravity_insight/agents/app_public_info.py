"""Canonical Agent product card for caller-bound public App metadata."""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping
from typing import Any

from .intent_text import affirmative_intent_text


APP_PUBLIC_INFO_SELECTOR = ".".join(("app", "app_info", "get"))
APP_PUBLIC_INFO_INPUT_TEMPLATE: Mapping[str, str] = {
    "url": "<app-store-or-google-play-url>",
}


def app_public_info_input_template() -> dict[str, str]:
    """Return a fresh raw-operation input object for caller completion."""

    return dict(APP_PUBLIC_INFO_INPUT_TEMPLATE)


APP_PUBLIC_INFO_CAPABILITY: Mapping[str, Any] = {
    "kind": "operation",
    "selector": APP_PUBLIC_INFO_SELECTOR,
    "operation_id": APP_PUBLIC_INFO_SELECTOR,
    "domain": "app",
    "description": (
        "读取调用方提供的 App Store 或 Google Play 公开下载链接，返回已登记的公开 App 信息；"
        "覆盖 OneLink 与公开信息绑定；当前账号 OneLink 目录明确为空，"
        "本产品不把空 OneLink 样本伪装成绑定。"
    ),
    "boundaries": (
        "当前账号 OneLink 目录明确为空，本产品不把空 OneLink 样本伪装成绑定。",
        "不读取账号可读 App 项目清单。",
    ),
    "effect": "read",
    "executable": True,
    "plan_executable": True,
    "natural_language_auto_execute": False,
    "input_schema": {
        "url": {
            "type": "string",
            "required": True,
            "description": "Caller-supplied public App Store or Google Play URL.",
            "max_length": 4096,
        }
    },
    "required_inputs": ("url",),
    "missing_inputs": ["url"],
    "input_template": app_public_info_input_template(),
    "match": {
        "confidence": "strong",
        "coverage": 1.0,
        "matched_terms": ["public app-store information"],
        "missing_terms": [],
        "score": 100,
        "exact_selector": True,
    },
    "next": {
        "ready_without_input": False,
        "argv": ["gravity", "run", APP_PUBLIC_INFO_SELECTOR, "--input", "<json-object-or-file>"],
        "call_count_after_discovery": 1,
    },
}


def app_public_info_capability_inventory() -> tuple[dict[str, Any], ...]:
    """Return the single canonical card backed by the stable operation."""

    return (copy.deepcopy(dict(APP_PUBLIC_INFO_CAPABILITY)),)


def is_authoritative_app_public_info_card(card: Mapping[str, Any]) -> bool:
    """Identify the owner card so generic operation search cannot replace it."""

    return (
        card.get("kind") == "operation"
        and card.get("selector") == APP_PUBLIC_INFO_SELECTOR
    )


def app_public_info_query(query: str) -> bool:
    """Recognize store-public / OneLink binding reads, not App governance."""

    selected = affirmative_intent_text(query)
    if selected in {APP_PUBLIC_INFO_SELECTOR, "app public info"}:
        return True
    words = frozenset(re.findall(r"[a-z0-9_]+", selected))
    english = (
        bool(words & {"onelink", "store"})
        or bool(words & {"public"}) and bool(words & {"info", "information", "binding"})
    ) and bool(words & {"app", "apps", "application"})
    chinese = any(term in selected for term in ("onelink", "公开信息")) and (
        "app" in words or "应用" in selected
    )
    return english or chinese


def app_public_info_capability_cards(
    query: str, *, domain: str | None = None, platform: str | None = None
) -> list[dict[str, Any]]:
    if platform is not None or domain not in {None, "app"}:
        return []
    exact = query.strip().casefold() == APP_PUBLIC_INFO_SELECTOR
    if not exact and not app_public_info_query(query):
        return []
    return [copy.deepcopy(dict(APP_PUBLIC_INFO_CAPABILITY))]


__all__ = [
    "APP_PUBLIC_INFO_CAPABILITY",
    "APP_PUBLIC_INFO_INPUT_TEMPLATE",
    "APP_PUBLIC_INFO_SELECTOR",
    "app_public_info_capability_cards",
    "app_public_info_capability_inventory",
    "app_public_info_input_template",
    "app_public_info_query",
    "is_authoritative_app_public_info_card",
]
