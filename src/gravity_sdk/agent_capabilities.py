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
from .agent_business_pulse import BUSINESS_PULSE_NAME
from .agent_company_usage import COMPANY_USAGE_NAME
from . import agent_report_directory as report_agent
from .agent_analysis_default_dictionary import (
    ANALYSIS_DEFAULT_DICTIONARY_NAME,
)
from .agent_realtime_event_catalog import REALTIME_EVENT_CATALOG_NAME
from .agent_custom_audience import CUSTOM_AUDIENCE_NAME
from .agent_bilibili_account_performance import (
    BILIBILI_ACCOUNT_PERFORMANCE_NAME,
)
from .agent_advertiser_profile import (
    ADVERTISER_PROFILE_NAME,
)
from .agent_composite_inventory import COMPOSITE_CAPABILITIES
from .agent_derived_metrics import DERIVED_METRICS_NAME
from .agent_monetization_guard import MONETIZATION_DETAIL_NAME
from .agent_order_directory import ORDER_DIRECTORY_NAME
from .agent_order_trace import ORDER_SPLIT_TRACE_NAME
from .agent_promotion_performance import PROMOTION_PERFORMANCE_NAME
from .agent_attribution_performance import ATTRIBUTION_PERFORMANCE_NAME
from .agent_title_package import TITLE_PACKAGE_NAME


_ASCII_WORD = re.compile(r"[a-z0-9_]+", re.IGNORECASE)
AGENT_SCOPE = (
    "workspace_recipes_analysis_query_spec_segment_rule_spec_stable_insight_composites_"
    "sql_products_governed_exports_and_local_metadata"
)

_COMPOSITE_CAPABILITIES = COMPOSITE_CAPABILITIES


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

    inventory = tuple(copy.deepcopy(item) for item in _COMPOSITE_CAPABILITIES)
    for item in inventory:
        declared = item.get("boundaries")
        if not isinstance(declared, (tuple, list)) or not declared:
            raise RuntimeError(
                f"composite {item.get('name')!r} must declare non-empty boundaries"
            )
    return inventory


def analysis_query_spec_cards(
    query: str, *, domain: str | None, platform: str | None
) -> list[dict[str, Any]]:
    """Expose the offline Analysis compiler as a first-class Agent handoff."""

    from .agent_analysis import analysis_query_spec_cards as build_cards
    from .agent_segment import (
        segment_mutation_cards,
        segment_rule_spec_cards as segment_cards,
    )

    return segment_mutation_cards(
        query, domain=domain, platform=platform
    ) or segment_cards(query, domain=domain, platform=platform) or build_cards(
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

    from .agent_unavailable import unavailable_journey_gap

    if unavailable_journey_gap(query) is not None:
        return [], True
    guarded = _guarded_handoff_cards(
        query,
        domain=domain,
        platform=platform,
        composite_inventory=composite_inventory,
    )
    if guarded is not None:
        return guarded
    return _routed_handoff_cards(
        query,
        domain=domain,
        platform=platform,
        export_inventory=export_inventory,
        composite_inventory=composite_inventory,
    )


def _guarded_handoff_cards(
    query: str,
    *,
    domain: str | None,
    platform: str | None,
    composite_inventory: Sequence[Mapping[str, Any]] | None,
) -> tuple[list[dict[str, Any]], bool] | None:
    from .agent_intent_routing import multiple_product_intents
    from .agent_monetization_aggregate import monetization_aggregate_capability_cards
    from .agent_monetization_guard import (
        monetization_guard_blocks_operation_fallback,
    )

    aggregate = monetization_aggregate_capability_cards(
        query, domain=domain, platform=platform
    )
    if aggregate:
        return aggregate, False
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
    return None


def _routed_handoff_cards(
    query: str,
    *,
    domain: str | None,
    platform: str | None,
    export_inventory: Sequence[Mapping[str, Any]],
    composite_inventory: Sequence[Mapping[str, Any]] | None,
) -> tuple[list[dict[str, Any]], bool]:
    from .agent_app_catalog import app_catalog_capability_cards
    from .agent_app_public_info import app_public_info_capability_cards
    from .agent_discovery_policy import operation_fallback_excluded
    from .agent_export import export_capability_cards
    from .agent_material_asset import material_asset_capability_cards
    from .agent_metadata_search import metadata_search_capability_cards
    from .agent_mutation_cards import mutation_cards
    from .agent_table_lineage import table_lineage_capability_cards
    from .agent_user_journey import user_journey_capability_cards

    direct_effects = [
        *mutation_cards(query, domain=domain, platform=platform),
        *material_asset_capability_cards(query, domain=domain, platform=platform),
        *export_capability_cards(
            query, domain=domain, platform=platform, inventory=export_inventory
        ),
    ]
    metadata_search = metadata_search_capability_cards(
        query, domain=domain, platform=platform
    )
    lineage = table_lineage_capability_cards(
        query, domain=domain, platform=platform
    )
    journeys = user_journey_capability_cards(
        query, domain=domain, platform=platform
    )
    operation_products = [
        *app_catalog_capability_cards(query, domain=domain, platform=platform),
        *app_public_info_capability_cards(query, domain=domain, platform=platform),
    ]
    products = [
        *analysis_query_spec_cards(query, domain=domain, platform=platform),
        *composite_capability_cards(
            query,
            domain=domain,
            platform=platform,
            inventory=composite_inventory,
        ),
    ]
    return (
        direct_effects
        or metadata_search
        or lineage
        or journeys
        or operation_products
        or products
    ), bool(
        direct_effects
        or metadata_search
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
            report_agent.REPORT_DIRECTORY_NAME,
            report_agent.REPORT_SUBSCRIPTIONS_NAME,
            CUSTOM_AUDIENCE_NAME,
            BILIBILI_ACCOUNT_PERFORMANCE_NAME,
            "material_performance",
            TITLE_PACKAGE_NAME,
            MONETIZATION_DETAIL_NAME,
            ORDER_DIRECTORY_NAME,
            ORDER_SPLIT_TRACE_NAME,
            PROMOTION_PERFORMANCE_NAME,
            ATTRIBUTION_PERFORMANCE_NAME,
            "attribution_user_detail",
            "multidim",
            "semantic_compose",
            "saved_analysis",
            "analysis_template",
            "segment_snapshot",
            "segment_members",
            ANALYSIS_DEFAULT_DICTIONARY_NAME,
            REALTIME_EVENT_CATALOG_NAME,
            ADVERTISER_PROFILE_NAME,
            DERIVED_METRICS_NAME, "metadata_sync",
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
