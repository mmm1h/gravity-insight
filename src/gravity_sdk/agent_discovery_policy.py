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


def operation_fallback_excluded(query: str) -> bool:
    """Return whether an explicit product request must not become a raw card."""

    return (
        monetization_guard_blocks_operation_fallback(query)
        or order_directory_blocks_operation_fallback(query)
        or order_split_trace_blocks_operation_fallback(query)
        or promotion_performance_blocks_operation_fallback(query)
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

    if order_split_trace_blocks_operation_fallback(query):
        reason = (
            "the explicit Order Split Trace request is excluded by its closed "
            "sensitive read-only product boundary"
        )
    elif order_directory_blocks_operation_fallback(query):
        reason = (
            "the explicit Order Directory request is excluded by its closed "
            "identifier-free single-day product boundary"
        )
    elif monetization_guard_blocks_operation_fallback(query):
        reason = MONETIZATION_GAP_REASON
    else:
        reason = (
            "the explicit Promotion Performance request is excluded by its "
            "closed read-only product boundary"
        )
    return [{
        "kind": "capability_gap",
        "query": safe_discovery_query(query),
        "reason": reason,
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
