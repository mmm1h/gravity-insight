"""Built-in Agent capabilities and deterministic query normalization.

This module contains only value-free product metadata.  Keeping composite
discovery beside the Agent protocol avoids making callers reverse-engineer
CLI subcommands or the Plan adapter allowlist.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
import re
from typing import Any

from .find import query_match
from .agent_business_pulse import BUSINESS_PULSE_CAPABILITY, BUSINESS_PULSE_NAME
from .agent_company_usage import COMPANY_USAGE_CAPABILITY, COMPANY_USAGE_NAME
from .agent_custom_audience import CUSTOM_AUDIENCE_CAPABILITY, CUSTOM_AUDIENCE_NAME
from .agent_bilibili_account_performance import (
    BILIBILI_ACCOUNT_PERFORMANCE_CAPABILITY,
    BILIBILI_ACCOUNT_PERFORMANCE_NAME,
)
from .agent_advertiser_profile import (
    ADVERTISER_PROFILE_CAPABILITY,
    ADVERTISER_PROFILE_NAME,
)
from .agent_dashboard import DASHBOARD_ANALYSIS_CAPABILITY
from .agent_multidim import MULTIDIM_CAPABILITY
from .agent_material_performance import MATERIAL_PERFORMANCE_CAPABILITY
from .agent_title_package import TITLE_PACKAGE_CAPABILITY, TITLE_PACKAGE_NAME
from .agent_order_directory import (
    ORDER_DIRECTORY_CAPABILITY,
    ORDER_DIRECTORY_NAME,
)
from .agent_order_trace import (
    ORDER_SPLIT_TRACE_CAPABILITY,
    ORDER_SPLIT_TRACE_NAME,
)
from .agent_promotion_performance import (
    PROMOTION_PERFORMANCE_CAPABILITY,
    PROMOTION_PERFORMANCE_NAME,
)
from .agent_saved_analysis import SAVED_ANALYSIS_CAPABILITY
from .template_replay_surface import ANALYSIS_TEMPLATE_CAPABILITY
from .agent_segment_snapshot import SEGMENT_SNAPSHOT_CAPABILITY
from .agent_segment_members import SEGMENT_MEMBERS_CAPABILITY
from .agent_monetization_guard import (
    MONETIZATION_DETAIL_CAPABILITY,
    MONETIZATION_DETAIL_NAME,
)


_ASCII_WORD = re.compile(r"[a-z0-9_]+", re.IGNORECASE)
AGENT_SCOPE = (
    "workspace_recipes_analysis_query_spec_segment_rule_spec_stable_insight_composites_"
    "sql_products_governed_exports_and_local_metadata"
)

_COMPOSITE_CAPABILITIES: tuple[Mapping[str, Any], ...] = (
    {
        "name": "analysis_context",
        "domain": "analysis",
        "aliases": (
            "analysis context",
            "analysis metadata",
            "analysis vocabulary",
            "分析上下文",
            "分析元数据",
        ),
        "description": (
            "并发读取事件、事件属性、用户属性、指标和报表模板的固定分析上下文。"
        ),
        "required_inputs": ("app",),
        "input_schema": {
            "app": {"type": "string", "required": True, "nullable": False},
        },
    },
    DASHBOARD_ANALYSIS_CAPABILITY,
    MONETIZATION_DETAIL_CAPABILITY,
    SEGMENT_SNAPSHOT_CAPABILITY,
    SEGMENT_MEMBERS_CAPABILITY,
    SAVED_ANALYSIS_CAPABILITY,
    ANALYSIS_TEMPLATE_CAPABILITY,
    {
        "name": "dashboard_snapshot",
        "domain": "analysis",
        "accepted_domains": ("analysis", "report"),
        "aliases": (
            "dashboard snapshot",
            "dashboard context",
            "dashboard control context",
            "dashboard details members filters",
            "analyze dashboard details members filters",
            "inspect dashboard members and saved filters",
            "show dashboard members and favourites",
            "get dashboard details members and default favourite",
            "看板快照",
            "看板详情成员筛选",
            "分析看板详情成员筛选",
            "请查看看板成员和筛选收藏",
            "帮我检查看板成员和筛选收藏",
            "帮我获取看板详情和默认收藏",
        ),
        "intent_terms": (
            "dashboard snapshot",
            "dashboard_snapshot",
            "dashboard context",
            "dashboard control context",
            "dashboard details",
            "dashboard member",
            "dashboard filter",
            "dashboard favourite",
            "dashboard favorite",
            "看板快照",
            "看板详情",
            "看板成员",
            "看板筛选",
            "看板收藏",
        ),
        "description": (
            "按精确 ID 或精确名称解析一个 Analysis 看板，并发读取详情、成员、"
            "空间成员、筛选收藏和默认收藏；只返回控制面快照，不执行图表。"
        ),
        "required_inputs": ("app", "ref"),
        "input_schema": {
            "app": {
                "type": "string|integer",
                "required": True,
                "nullable": False,
            },
            "ref": {
                "type": "string|integer",
                "required": True,
                "nullable": False,
                "description": "Exact dashboard id or exact dashboard name.",
            },
        },
    },
    {
        "name": "app_snapshot",
        "domain": "app",
        "aliases": (
            "app snapshot",
            "application snapshot",
            "app governance",
            "应用快照",
            "应用治理",
        ),
        "description": (
            "并发读取 App 详情、实时事件、容量、权限菜单、角色和模板的治理快照。"
        ),
        "required_inputs": ("app",),
        "input_schema": {
            "app": {"type": "string", "required": True, "nullable": False},
        },
    },
    {
        "name": "attribution_snapshot",
        "domain": "attribution",
        "aliases": (
            "attribution snapshot",
            "attribution configuration",
            "归因快照",
            "归因配置",
        ),
        "description": "并发读取已登记归因映射、回溯与采集配置的固定快照。",
        "required_inputs": ("app",),
        "input_schema": {
            "app": {"type": "string", "required": True, "nullable": False},
        },
    },
    MULTIDIM_CAPABILITY,
    MATERIAL_PERFORMANCE_CAPABILITY,
    TITLE_PACKAGE_CAPABILITY,
    ORDER_DIRECTORY_CAPABILITY,
    ORDER_SPLIT_TRACE_CAPABILITY,
    PROMOTION_PERFORMANCE_CAPABILITY,
    BUSINESS_PULSE_CAPABILITY,
    COMPANY_USAGE_CAPABILITY,
    CUSTOM_AUDIENCE_CAPABILITY,
    BILIBILI_ACCOUNT_PERFORMANCE_CAPABILITY,
    ADVERTISER_PROFILE_CAPABILITY,
)


def normalize_agent_query(query: str) -> str:
    """Normalize only safe English inflections; do not guess business meaning."""

    def singular(match: re.Match[str]) -> str:
        word = match.group(0)
        lowered = word.casefold()
        if len(lowered) > 4 and lowered.endswith("ies"):
            return lowered[:-3] + "y"
        if (
            len(lowered) > 3
            and lowered.endswith("s")
            and not lowered.endswith(("ss", "us", "is"))
        ):
            return lowered[:-1]
        return lowered

    return _ASCII_WORD.sub(singular, query.strip().casefold())


def agent_query_match(
    query: str, *values: object, score: int = 0
) -> dict[str, Any]:
    """Apply the shared matcher after bounded, deterministic normalization."""

    return query_match(normalize_agent_query(query), *values, score=score)


def operation_query_match(query: str, item: Mapping[str, Any]) -> dict[str, Any]:
    """Match one operation while making selector-shaped queries fail closed."""

    match = agent_query_match(
        query,
        item.get("operation_id"),
        item.get("domain"),
        item.get("resource"),
        item.get("action"),
        item.get("platform"),
        item.get("description"),
        score=int(item.get("score", 0)),
    )
    operation_id = str(item.get("operation_id", ""))
    normalized_query = query.strip().casefold()
    if operation_id.casefold() == normalized_query:
        return {
            **match,
            "confidence": "strong",
            "coverage": 1.0,
            "matched_terms": [normalized_query],
            "missing_terms": [],
            "exact_selector": True,
        }
    selector_shaped = bool(query.isascii() and " " not in query and "." in query)
    if selector_shaped:
        return {
            **match,
            "confidence": "partial",
            "coverage": 0.0,
            "matched_terms": [],
            "missing_terms": [normalized_query],
        }
    return match


def composite_capability_inventory() -> tuple[Mapping[str, Any], ...]:
    """Return the immutable, value-free built-in composite inventory."""

    return tuple(copy.deepcopy(item) for item in _COMPOSITE_CAPABILITIES)


def analysis_query_spec_cards(
    query: str, *, domain: str | None, platform: str | None
) -> list[dict[str, Any]]:
    """Expose the offline Analysis compiler as a first-class Agent handoff."""

    from .agent_analysis import analysis_query_spec_cards as build_cards
    from .agent_segment import segment_rule_spec_cards as segment_cards

    return segment_cards(query, domain=domain, platform=platform) or build_cards(
        query, domain=domain, platform=platform
    )


def composite_capability_cards(
    query: str,
    *,
    domain: str | None,
    platform: str | None,
    inventory: Sequence[Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Return strongly matching Plan composite cards without network access."""

    if platform is not None:
        return []
    from .agent_composite import composite_card

    normalized = normalize_agent_query(query)
    cards = [
        card
        for definition in inventory or _COMPOSITE_CAPABILITIES
        if (card := composite_card(query, normalized, domain, definition)) is not None
    ]
    return sorted(
        cards,
        key=lambda card: (
            not bool(card["match"].get("exact_selector")),
            -float(card["match"].get("coverage", 0)),
            str(card["composite"]),
        ),
    )


def capability_handoff_cards(
    query: str,
    *,
    domain: str | None,
    platform: str | None,
    export_inventory: Sequence[Mapping[str, Any]],
    composite_inventory: Sequence[Mapping[str, Any]] | None,
) -> tuple[list[dict[str, Any]], bool]:
    """Select direct product handoffs and whether they exclude local catalogs."""

    from .agent_monetization_guard import (
        monetization_guard_blocks_operation_fallback,
    )
    from .agent_discovery_policy import operation_fallback_excluded
    from .agent_export import export_capability_cards
    from .agent_intent_routing import multiple_product_intents
    from .agent_table_lineage import table_lineage_capability_cards
    from .agent_user_journey import user_journey_capability_cards

    if monetization_guard_blocks_operation_fallback(query):
        if multiple_product_intents(query, inventory=composite_inventory):
            return [], True
        products = [
            card
            for card in composite_capability_cards(
                query,
                domain=domain,
                platform=platform,
                inventory=composite_inventory,
            )
            if card.get("composite") == MONETIZATION_DETAIL_NAME
        ]
        return products, True
    if multiple_product_intents(query, inventory=composite_inventory):
        return [], True
    exports = export_capability_cards(
        query, domain=domain, platform=platform, inventory=export_inventory
    )
    lineage = table_lineage_capability_cards(
        query, domain=domain, platform=platform
    )
    journeys = user_journey_capability_cards(
        query, domain=domain, platform=platform
    )
    products = [
        *analysis_query_spec_cards(query, domain=domain, platform=platform),
        *composite_capability_cards(
            query,
            domain=domain,
            platform=platform,
            inventory=composite_inventory,
        ),
    ]
    return exports or lineage or journeys or products, bool(
        exports
        or lineage
        or journeys
        or operation_fallback_excluded(query)
    )


def should_load_capability_catalog(
    query: str,
    *,
    domain: str | None,
    platform: str | None,
    direct_cards: Sequence[Mapping[str, Any]],
    catalog_excluded: bool,
) -> bool:
    """Keep catalog loading compatible while enabling Analysis task candidates."""

    from .agent_handoff import is_analysis_task_handoff_query

    task_catalog = (
        not direct_cards
        and platform is None
        and domain in {None, "analysis"}
        and is_analysis_task_handoff_query(query)
    )
    return (
        not catalog_excluded
        and platform is None
        and (domain is None or task_catalog)
    )


def merge_catalog_handoff_cards(
    query: str,
    *,
    domain: str | None,
    platform: str | None,
    direct_cards: list[dict[str, Any]],
    catalog: list[dict[str, Any]],
    warnings: list[str],
    sources: Any | None,
) -> list[dict[str, Any]]:
    """Give recipes/vocabulary precedence, otherwise emit one Analysis task."""

    from .agent_analysis_task import analysis_task_cards
    from .agent_handoff import is_analysis_task_handoff_query
    from .agent_vocabulary import is_authoritative_local_metadata_card

    recipes = [card for card in catalog if card.get("kind") == "recipe"]
    local = [card for card in catalog if is_authoritative_local_metadata_card(card)]
    task_cards = (
        analysis_task_cards(
            query,
            metadata_rows=_analysis_task_metadata_rows(catalog, warnings, sources),
            domain=domain,
            platform=platform,
        )
        if (
            is_analysis_task_handoff_query(query)
            and not direct_cards
            and not recipes
            and not local
        )
        else []
    )
    return task_cards or [*catalog, *direct_cards]


def authoritative_capability_cards(
    cards: Sequence[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    """Return the first exclusive discovery product class, if one exists."""

    from .agent_intent_routing import unique_authoritative_cards
    from .agent_segment import is_authoritative_direct_card
    from .agent_user_journey import is_user_journey_card
    from .agent_vocabulary import is_authoritative_local_metadata_card

    authoritative_composites = [
        card
        for card in cards
        if card.get("kind") == "composite"
        and card.get("composite")
        in {
            "dashboard_analysis",
            "dashboard_snapshot",
            BUSINESS_PULSE_NAME,
            COMPANY_USAGE_NAME,
            CUSTOM_AUDIENCE_NAME,
            BILIBILI_ACCOUNT_PERFORMANCE_NAME,
            "material_performance",
            TITLE_PACKAGE_NAME,
            MONETIZATION_DETAIL_NAME,
            ORDER_DIRECTORY_NAME,
            ORDER_SPLIT_TRACE_NAME,
            PROMOTION_PERFORMANCE_NAME,
            "multidim",
            "saved_analysis",
            "analysis_template",
            "segment_snapshot",
            "segment_members",
            ADVERTISER_PROFILE_NAME,
        }
    ]
    return unique_authoritative_cards(
        authoritative_composites
        or [card for card in cards if is_authoritative_direct_card(card)]
        or [
            card
            for card in cards
            if card.get("kind") == "analysis_task" or is_user_journey_card(card)
        ]
        or [card for card in cards if is_authoritative_local_metadata_card(card)]
    )


def _analysis_task_metadata_rows(
    catalog: Sequence[Mapping[str, Any]], warnings: Sequence[str], sources: Any | None
) -> tuple[Mapping[str, Any], ...] | None:
    if sources is not None:
        if not bool(getattr(sources, "metadata_catalog_available", True)):
            return None
        return tuple(getattr(sources, "metadata_inventory", ()))
    if any(
        "metadata catalog is unavailable" in warning.casefold()
        for warning in warnings
    ):
        return None
    return tuple(
        {
            "kind": card.get("metadata_kind"),
            "name": card.get("name"),
            "cname": card.get("display_name"),
            "operation_id": card.get("operation_id"),
            "app_id": card.get("app_id"),
            "scope": card.get("scope"),
            "source": card.get("source"),
        }
        for card in catalog
        if card.get("kind") == "metadata"
    )


__all__ = [
    "AGENT_SCOPE",
    "agent_query_match",
    "analysis_query_spec_cards",
    "authoritative_capability_cards",
    "capability_handoff_cards",
    "composite_capability_cards",
    "composite_capability_inventory",
    "merge_catalog_handoff_cards",
    "normalize_agent_query",
    "operation_query_match",
    "should_load_capability_catalog",
]
