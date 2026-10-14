"""Class-level Agent handoff for the complete offline Analysis catalog."""

from __future__ import annotations

import re
from typing import Any

from .intent_text import affirmative_intent_text


SELECTOR = "metadata:search"
MATERIAL_METRIC_SELECTOR = "metadata:material_metric"


def metadata_search_capability_cards(
    query: str, *, domain: str | None, platform: str | None
) -> list[dict[str, Any]]:
    from .metadata_onboarding import metadata_onboarding_capability_cards

    onboarding = metadata_onboarding_capability_cards(
        query, domain=domain, platform=platform
    )
    if onboarding:
        return onboarding
    if material_metric_search_intent(query):
        return [_material_metric_card(query, platform)]
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


def material_metric_search_intent(query: str) -> bool:
    selected = affirmative_intent_text(query)
    words = frozenset(re.findall(r"[a-z0-9_]+", selected))
    return bool(
        words & {"material", "materials", "creative", "creatives"}
        and words & {"metric", "metrics", "field", "fields", "catalog", "search"}
    ) or ("素材" in selected and "指标" in selected)


def _material_metric_card(query: str, platform: str | None) -> dict[str, Any]:
    from ..material_metrics import CATALOG_PLATFORMS

    selected_platform = platform if platform in CATALOG_PLATFORMS else None
    missing = ["query"] + ([] if selected_platform else ["platform"])
    template = {
        "query": "<material-metric-search-term>",
        "platform": selected_platform or "<aggregate|bytedance|tencent|kuaishou|gravity>",
    }
    argv = [
        "gravity", "metadata", "vocabulary", template["query"],
        "--kind", "material_metric", "--platform", template["platform"],
    ]
    return {
        "kind": "metadata",
        "selector": MATERIAL_METRIC_SELECTOR,
        "metadata_kind": "material_metric",
        "domain": "material",
        "platform": selected_platform,
        "description": "离线搜索版本化素材报表指标，并返回指标命名空间和查询字段片段。",
        "boundaries": (
            "媒体指标写入 metrics_list；引力指标只写入 gravity_metrics_list。",
            "目录发现不执行素材报表。",
        ),
        "scope": "runtime",
        "effect": "local_read",
        "executable": True,
        "plan_executable": True,
        "offline": True,
        "network_called": False,
        "required_inputs": ["query", "platform"],
        "missing_inputs": missing,
        "input_schema": {
            "query": {"type": "string", "required": True, "nullable": False},
            "platform": {
                "type": "string", "required": True, "nullable": False,
                "enum": list(CATALOG_PLATFORMS),
            },
        },
        "input_template": template,
        "lookup_query": template["query"],
        "match": {
            "confidence": "strong", "coverage": 1.0,
            "matched_terms": ["material metric catalog"], "missing_terms": [],
            "score": 100,
            "exact_selector": query.strip().casefold() == MATERIAL_METRIC_SELECTOR,
            "intent_only": query.strip().casefold() != MATERIAL_METRIC_SELECTOR,
        },
        "next": {"ready_without_input": not missing, "argv": argv},
        "next_action": "Fill query and platform, then copy the returned request_fragment into the material report request.",
    }


def _card(query: str) -> dict[str, Any]:
    return {
        "kind": "metadata",
        "selector": SELECTOR,
        "metadata_kind": "all",
        "domain": "metadata",
        "description": (
            "离线搜索已同步的 App、事件、属性、指标和模板名称，以及 Runtime "
            "内置用户报表字段；在线目录缺失时先做完整原子同步。"
        ),
        "boundaries": (
            "目录缺失时先做完整原子同步，不从自然语言选择业务字段。",
            "不执行分析查询。",
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
    "MATERIAL_METRIC_SELECTOR",
    "material_metric_search_intent",
    "metadata_search_capability_cards",
    "metadata_search_capability_inventory",
    "metadata_search_intent",
]
