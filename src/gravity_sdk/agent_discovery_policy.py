"""Local product policy used before generic Agent operation discovery."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .agent_promotion_performance import (
    promotion_performance_blocks_operation_fallback,
)


def operation_fallback_excluded(query: str) -> bool:
    """Return whether an explicit product request must not become a raw card."""

    return promotion_performance_blocks_operation_fallback(query)


def promotion_performance_gap(query: str) -> list[dict[str, Any]]:
    """Return one safe gap for a product-shaped but excluded request."""

    return [{
        "kind": "capability_gap",
        "query": query,
        "reason": (
            "the explicit Promotion Performance request is excluded by its "
            "closed read-only product boundary"
        ),
        "weak_matches": [],
    }]


def is_authoritative_local_question(
    cards: Sequence[Mapping[str, Any]], query: str
) -> bool:
    """Treat safe product gaps as local without broadening card authority."""

    from .agent_segment import is_authoritative_direct_card
    from .agent_vocabulary import is_authoritative_local_metadata_card

    return promotion_performance_blocks_operation_fallback(query) or any(
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
    "operation_fallback_excluded",
    "promotion_performance_gap",
]
