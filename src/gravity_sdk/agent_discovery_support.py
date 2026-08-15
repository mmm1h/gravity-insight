"""Small helpers kept outside the size-ratcheted Agent entry point."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


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
    "capability_gaps_for_page",
    "materialize_candidates",
    "select_authoritative_cards",
]
