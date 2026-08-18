"""Local product policy used before generic Agent operation discovery."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .agent_monetization_guard import (
    MONETIZATION_GAP_REASON,
    monetization_guard_blocks_operation_fallback,
    monetization_guard_safe_query,
)
from .agent_order_directory import (
    order_directory_blocks_operation_fallback,
    order_directory_safe_query,
)
from .agent_order_trace import (
    order_split_trace_blocks_operation_fallback,
    order_split_trace_safe_query,
)
from .agent_promotion_performance import (
    promotion_performance_blocks_operation_fallback,
)
from .agent_bilibili_account_performance import (
    bilibili_account_performance_blocks_operation_fallback,
)
from .agent_advertiser_profile import (
    advertiser_profile_blocks_operation_fallback,
)


def operation_fallback_excluded(query: str) -> bool:
    """Return whether an explicit product request must not become a raw card."""

    from .agent_unavailable import unavailable_journey_gap

    return (
        unavailable_journey_gap(query) is not None
        or monetization_guard_blocks_operation_fallback(query)
        or order_directory_blocks_operation_fallback(query)
        or order_split_trace_blocks_operation_fallback(query)
        or promotion_performance_blocks_operation_fallback(query)
        or bilibili_account_performance_blocks_operation_fallback(query)
        or advertiser_profile_blocks_operation_fallback(query)
    )


def safe_discovery_query(query: str) -> str:
    """Remove values from every sensitive product-shaped Agent query."""

    protected = order_directory_safe_query(order_split_trace_safe_query(query))
    if protected != query:
        return protected
    if monetization_guard_blocks_operation_fallback(query):
        return monetization_guard_safe_query(query)
    return query


def operation_fallback_gap(query: str) -> list[dict[str, Any]]:
    """Return one product-specific safe gap without consulting operations."""

    from .agent_intent_routing import (
        explicit_clause_coordination,
        multiple_intent_gap,
    )
    from .agent_unavailable import unavailable_journey_gap

    unavailable = unavailable_journey_gap(query)
    if gap := multiple_intent_gap(query):
        if unavailable is None or explicit_clause_coordination(query):
            query_text = safe_discovery_query(query)
            for item in gap:
                item["query"] = query_text
            return gap

    if unavailable:
        return [unavailable]
    if order_split_trace_blocks_operation_fallback(query):
        reason = (
            "the explicit Order Split Trace request is excluded by its closed "
            "sensitive read-only product boundary"
        )
    elif order_directory_blocks_operation_fallback(query):
        reason = (
            "the explicit Order Directory request is excluded by its closed "
            "bounded single-day product boundary"
        )
    elif monetization_guard_blocks_operation_fallback(query):
        reason = MONETIZATION_GAP_REASON
    elif bilibili_account_performance_blocks_operation_fallback(query):
        reason = (
            "the explicit Bilibili Account Performance request is excluded by "
            "its closed read-only product boundary"
        )
    elif advertiser_profile_blocks_operation_fallback(query):
        reason = (
            "the explicit Advertiser Profile request is excluded by its closed "
            "read-only account-directory boundary"
        )
    else:
        reason = (
            "the explicit Promotion Performance request is excluded by its "
            "closed read-only product boundary"
        )
    return [{
        "kind": "capability_gap",
        "query": safe_discovery_query(query),
        "reason": reason,
        "next_action": (
            "Treat this as a confirmed product-boundary gap; do not browse "
            "for a substitute raw operation or invent a selector."
        ),
        "weak_matches": [],
    }]


def promotion_performance_gap(query: str) -> list[dict[str, Any]]:
    """Return one safe gap for a product-shaped but excluded request."""

    return operation_fallback_gap(query)


def is_authoritative_local_question(
    cards: Sequence[Mapping[str, Any]], query: str
) -> bool:
    """Treat safe product gaps as local without broadening card authority."""

    from .agent_segment import is_authoritative_direct_card
    from .agent_vocabulary import is_authoritative_local_metadata_card

    return operation_fallback_excluded(query) or any(
        (
            is_authoritative_local_metadata_card(card)
            or is_authoritative_direct_card(card)
            or card.get("kind")
            in {"recipe", "composite", "analysis_query_spec", "analysis_task"}
        )
        and card.get("match", {}).get("confidence") == "strong"
        for card in cards
    )


__all__ = [
    "is_authoritative_local_question",
    "operation_fallback_gap",
    "operation_fallback_excluded",
    "promotion_performance_gap",
    "safe_discovery_query",
]
