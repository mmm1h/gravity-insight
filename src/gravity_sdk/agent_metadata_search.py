"""Class-level Agent handoff for the complete offline Analysis catalog."""

from __future__ import annotations

import re
from typing import Any

from .agent_intent_text import affirmative_intent_text


SELECTOR = "metadata:search"


def metadata_search_capability_cards(
    query: str, *, domain: str | None, platform: str | None
) -> list[dict[str, Any]]:
    from .agent_metadata_onboarding import metadata_onboarding_capability_cards

    onboarding = metadata_onboarding_capability_cards(
        query, domain=domain, platform=platform
    )
    if onboarding:
        return onboarding
    if platform is not None or domain not in {None, "analysis", "metadata"}:
        return []
    if not metadata_search_intent(query):
        return []
    return [_card(query)]


def metadata_search_capability_inventory() -> tuple[dict[str, Any], ...]:
    """Materialize the canonical class-level metadata handoff."""

    return tuple(
        metadata_search_capability_cards(SELECTOR, domain=None, platform=None)
    )


def metadata_search_intent(query: str) -> bool:
    selected = affirmative_intent_text(query)
    words = frozenset(re.findall(r"[a-z0-9_]+", selected))
    english_groups = (
        {"event", "events"}, {"property", "properties", "attributes"},
        {"metric", "metrics"}, {"template", "templates"},
    )
    english = (
        sum(bool(words & group) for group in english_groups) >= 3
        and bool(words & {"find", "search", "available", "catalog"})
        and bool(words & {"local", "offline", "catalog"})
    )
    chinese_groups = ("事件", "属性", "指标", "模板")
    chinese = (
        sum(term in selected for term in chinese_groups) >= 3
        and any(term in selected for term in ("找", "查", "目录", "有哪些"))
        and any(term in selected for term in ("本地", "离线", "不联网", "目录"))
    )
    class_level = (
        bool(words & {"metadata"})
        and bool(words & {"discover", "find", "name", "names", "search"})
    ) or (
        "元数据" in selected and any(term in selected for term in ("发现", "名称", "搜索", "查找"))
    )
    return english or chinese or class_level


def _card(query: str) -> dict[str, Any]:
    return {
        "kind": "metadata",
        "selector": SELECTOR,
        "metadata_kind": "all",
        "domain": "metadata",
        "description": (
            "离线搜索已同步的 App、事件、属性、指标和模板名称；目录缺失时先做"
            "完整原子同步，不从自然语言选择业务字段。"
        ),
        "scope": "app_and_workspace",
        "effect": "local_read",
        "executable": True,
        "plan_executable": True,
        "offline": True,
        "network_called": False,
        "required_inputs": ["query"],
        "missing_inputs": ["query"],
        "input_schema": {
            "query": {
                "type": "string", "required": True, "nullable": False,
                "description": "Caller-selected local catalog search term.",
            },
        },
        "input_template": {"query": "<local-metadata-search-term>"},
        "lookup_query": "<local-metadata-search-term>",
        "match": {
            "confidence": "strong", "coverage": 1.0,
            "matched_terms": ["offline analysis metadata catalog"],
            "missing_terms": [], "score": 100,
            "exact_selector": query.strip().casefold() == SELECTOR,
            "intent_only": query.strip().casefold() != SELECTOR,
        },
        "next": {
            "ready_without_input": False,
            "argv": ["gravity", "metadata", "search", "<search-term>"],
            "catalog_sync_argv": ["gravity", "metadata", "sync", "--all-apps"],
        },
        "next_action": (
            "Fill plan_node.request.query with one caller-selected term; if the local "
            "catalog is absent, run the catalog_sync_argv once and retry offline."
        ),
    }


__all__ = [
    "SELECTOR",
    "metadata_search_capability_cards",
    "metadata_search_capability_inventory",
    "metadata_search_intent",
]
