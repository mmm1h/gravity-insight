"""Small helpers kept outside the size-ratcheted Agent entry point."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


CATALOG_BROWSE_ARGV = ["gravity", "agent-catalog", "categories"]
NO_CANDIDATE_NEXT_ACTION = (
    "Browse `gravity agent-catalog categories` then `category` and `describe` "
    "to confirm the capability is absent; do not execute weak partial matches "
    "or invent a selector."
)


def catalog_browse_next() -> dict[str, Any]:
    return {"argv": list(CATALOG_BROWSE_ARGV)}


def discovery_next_fields(has_candidates: bool) -> dict[str, Any]:
    if has_candidates:
        return {
            "next_action": (
                "Prefer a recipe, registered composite, then stable Insight; use a "
                "matching SQL product only when Insight cannot express the goal, and "
                "invoke the selected next.argv."
            )
        }
    return {
        "next_action": NO_CANDIDATE_NEXT_ACTION,
        "next": catalog_browse_next(),
    }


def select_authoritative_cards(
    cards: list[dict[str, Any]],
) -> list[Mapping[str, Any]]:
    from .agent_capabilities import authoritative_capability_cards
    from .agent_semantic_context import is_semantic_card

    semantic = [card for card in cards if is_semantic_card(card)]
    return semantic or authoritative_capability_cards(cards)


def capability_gaps_for_page(
    request: Any,
    client: Any,
    weak_operations: list[Mapping[str, Any]],
    operation_fallback_excluded: bool,
) -> list[dict[str, Any]]:
    if operation_fallback_excluded:
        from .agent_discovery_policy import operation_fallback_gap

        return operation_fallback_gap(request.query)
    from .find import capability_gaps

    return capability_gaps(
        client,
        request.query,
        domain=request.domain,
        platform=request.platform,
        limit=request.limit,
        weak_operations=weak_operations,
    )


def materialize_candidates(
    client: Any, selected: list[tuple[str, Mapping[str, Any]]]
) -> list[dict[str, Any]]:
    from .agent_sources import describe_operation_cards

    described = iter(
        describe_operation_cards(
            client, [item for source, item in selected if source == "operation"]
        )
    )
    return [
        next(described) if source == "operation" else dict(item)
        for source, item in selected
    ]


__all__ = [
    "CATALOG_BROWSE_ARGV",
    "NO_CANDIDATE_NEXT_ACTION",
    "capability_gaps_for_page",
    "catalog_browse_next",
    "discovery_next_fields",
    "materialize_candidates",
    "select_authoritative_cards",
]
