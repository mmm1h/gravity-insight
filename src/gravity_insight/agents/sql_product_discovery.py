"""Catalog-aware discovery for governed workspace SQL product requests."""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from typing import Any

from .lexical_retrieval import AppliedLexicalFallback


WORKSPACE_SQL_NAME_ALGORITHM = "registered_workspace_sql_name.v1"


def apply_workspace_sql_owner(
    query: str, *, workspace: Any | None, sources: Any | None
) -> AppliedLexicalFallback:
    """Resolve the SQL owner against exact registered names, never raw SQL."""

    from .batch_sources import snapshot_products
    from .semantic_context import load_agent_workspace
    from .sql_product_gap import (
        registered_sql_product_gap,
        registered_sql_product_names,
    )

    selected_workspace = load_agent_workspace(workspace, sources)
    inventory = tuple(getattr(sources, "product_inventory", ()) or ())
    if not inventory:
        inventory = snapshot_products(selected_workspace, [])
    names = registered_sql_product_names(query, inventory)
    receipt = _receipt(names)
    cards = _product_cards(names, inventory)
    if len(cards) == 1:
        card = copy.deepcopy(cards[0])
        card["match"] = _exact_name_match(names[0])
        return AppliedLexicalFallback((("catalog", card),), (), receipt)
    if len(cards) > 1:
        return AppliedLexicalFallback(
            (), (_multiple_products_gap(query, cards, receipt),), receipt
        )
    gap = registered_sql_product_gap(query)
    if gap is None:
        raise RuntimeError("workspace SQL owner intent did not produce its gap")
    gap["lexical_retrieval"] = receipt
    return AppliedLexicalFallback((), (gap,), receipt)


def _product_cards(
    names: Sequence[str], inventory: Sequence[Mapping[str, Any]]
) -> tuple[dict[str, Any], ...]:
    from .sources import snapshot_product_cards

    return tuple(
        card
        for name in names
        for card in snapshot_product_cards(
            name,
            tuple(item for item in inventory if str(item.get("name")) == name),
        )
    )


def _exact_name_match(name: str) -> dict[str, Any]:
    return {
        "confidence": "strong",
        "coverage": 1.0,
        "matched_terms": [name],
        "missing_terms": [],
        "score": 0,
        "exact_registered_name": True,
        "lexical_retrieval": {"algorithm": WORKSPACE_SQL_NAME_ALGORITHM},
    }


def _multiple_products_gap(
    query: str,
    cards: Sequence[Mapping[str, Any]],
    receipt: Mapping[str, Any],
) -> dict[str, Any]:
    from .intent_routing import product_selection_gap

    gap = product_selection_gap(
        query,
        [str(card["selector"]) for card in cards],
        reason=(
            "multiple exact workspace SQL product names were stated; "
            "choose one governed product before execution"
        ),
    )
    gap["lexical_retrieval"] = dict(receipt)
    return gap


def _receipt(names: Sequence[str]) -> dict[str, Any]:
    disposition = (
        "below_threshold" if not names
        else "single_match" if len(names) == 1
        else "multiple_matches"
    )
    return {
        "algorithm": WORKSPACE_SQL_NAME_ALGORITHM,
        "disposition": disposition,
        "minimum_score": 1.0,
        "minimum_matched_terms": 1,
        "top_score": 1.0 if names else 0.0,
        "catalog_scope": "workspace_sql_products_only",
        "matches": [
            {
                "selector": f"sql:{name}",
                "document_kind": "card",
                "score": 1.0,
                "matched_terms": [name],
            }
            for name in names
        ],
    }


__all__ = ["WORKSPACE_SQL_NAME_ALGORITHM", "apply_workspace_sql_owner"]
