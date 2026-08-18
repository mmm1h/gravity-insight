"""Small helpers kept outside the size-ratcheted Agent entry point."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any


CATALOG_BROWSE_ARGV = ["gravity", "agent-catalog", "categories"]
HOST_CATALOG_ARGV = ["gravity", "agent-catalog", "host"]
NO_CANDIDATE_NEXT_ACTION = (
    "Browse `gravity agent-catalog categories` then `category` and `describe` "
    "to confirm the capability is absent; do not execute weak partial matches "
    "or invent a selector."
)
UNRANKED_OPERATIONS = "UNRANKED_OPERATIONS"
UNRANKED_OPERATIONS_NEXT_ACTION = (
    "The recognizer did not select one product; it only ranked distinct raw "
    "operations. Browse `gravity agent-catalog host`, return one "
    "gravity.host-product-selection.v1, then call gravity agent --routing "
    "host_catalog --host-selection; do not execute a ranked raw operation."
)
_MIN_UNRANKED_OPERATIONS = 3


def catalog_browse_next() -> dict[str, Any]:
    return {"argv": list(CATALOG_BROWSE_ARGV)}


def host_catalog_next() -> dict[str, Any]:
    return {"argv": list(HOST_CATALOG_ARGV)}


def host_arm_upgrade_argv(query: str) -> list[str]:
    """Copyable argv that re-runs the same query on the host arm."""

    return [
        "gravity",
        "agent",
        query,
        "--routing",
        "host_catalog",
        "--host-selection",
        "<gravity.host-product-selection.v1>",
    ]


def recognizer_routing_declaration(query: str) -> dict[str, Any]:
    """Declare the offline floor and how a capable caller upgrades."""

    from .agent_discovery_policy import safe_discovery_query
    from .agent_host_selection import DEFAULT_ROUTING_MODE

    selected = safe_discovery_query(query)
    return {
        "mode": DEFAULT_ROUTING_MODE,
        "floor": True,
        "upgrade": {
            "when": (
                "the caller can emit gravity.host-product-selection.v1 after "
                "reading the host catalog"
            ),
            "next_action": (
                "This answer is the offline recognizer floor. Read "
                "`gravity agent-catalog host` and resubmit the same query with "
                "`--routing host_catalog --host-selection`."
            ),
            "next": {
                "argv": list(HOST_CATALOG_ARGV),
                "then_argv": host_arm_upgrade_argv(selected),
            },
        },
    }


def unranked_operation_ids(
    unified: Sequence[tuple[str, Mapping[str, Any]]],
) -> tuple[str, ...]:
    """Return distinct raw-operation ids when the page never selected a product.

    Exact-selector lookups and any catalog card (recipe, compiler, composite)
    stay executable. Only a page of distinct raw operations is a guess.
    """

    identities: list[str] = []
    for source, item in unified:
        if source != "operation":
            return ()
        match = item.get("agent_match")
        if isinstance(match, Mapping) and match.get("exact_selector"):
            return ()
        identity = str(item.get("operation_id") or item.get("selector") or "")
        if not identity or identity in identities:
            return ()
        identities.append(identity)
    if len(identities) < _MIN_UNRANKED_OPERATIONS:
        return ()
    return tuple(identities)


def unranked_operations_gap(
    query: str, operation_ids: Sequence[str]
) -> dict[str, Any]:
    """Hand the host the catalog projection instead of guessing a top-1 product."""

    from .agent_discovery_policy import safe_discovery_query

    return {
        "kind": "capability_gap",
        "code": UNRANKED_OPERATIONS,
        "query": safe_discovery_query(query),
        "reason": (
            "offline discovery returned only distinct raw operations and no "
            "authoritative product card; the recognizer does not rank them"
        ),
        "next_action": UNRANKED_OPERATIONS_NEXT_ACTION,
        "next": host_catalog_next(),
        "ranked_operation_ids": list(operation_ids),
        "weak_matches": [],
        "network_called": False,
    }


def drop_auxiliary_catalog_tail(
    unified: Sequence[tuple[str, Mapping[str, Any]]],
) -> list[tuple[str, Mapping[str, Any]]]:
    """Drop catalog cards that only trail a raw-operation ranking page."""

    if not unified or unified[0][0] != "operation":
        return list(unified)
    selected: list[tuple[str, Mapping[str, Any]]] = []
    for source, item in unified:
        if source == "catalog" and item.get("kind") not in {
            "recipe",
            "analysis_query_spec",
        }:
            continue
        selected.append((source, item))
    return selected


def is_short_catalog_lookup(query: str) -> bool:
    """ASCII keyword lookups stay ranked; a sentence is not a catalog lookup."""

    selected = query.strip().casefold()
    if any("\u3400" <= character <= "\u9fff" for character in selected):
        return False
    words = re.findall(r"[a-z0-9_.]+", selected)
    return 0 < len(words) <= 3


def apply_unranked_operation_handoff(
    query: str,
    unified: Sequence[tuple[str, Mapping[str, Any]]],
    existing_gaps: Sequence[Mapping[str, Any]],
) -> tuple[list[tuple[str, Mapping[str, Any]]], tuple[Mapping[str, Any], ...]]:
    """Replace an unranked raw-operation page with a host-catalog handoff."""

    if is_short_catalog_lookup(query):
        return list(unified), tuple(existing_gaps)
    ranked = unranked_operation_ids(drop_auxiliary_catalog_tail(unified))
    if not ranked:
        return list(unified), tuple(existing_gaps)
    return [], (unranked_operations_gap(query, ranked),)


def finish_discovery_candidates(query: str, lexical: Any) -> tuple[list[Any], tuple[Any, ...]]:
    """Apply lexical output then the unranked-operation host handoff."""

    return apply_unranked_operation_handoff(query, lexical.candidates, lexical.gaps)


def assert_discovery_page(
    page: Any, request: Any, unified: Sequence[Any], fingerprint: str
) -> None:
    from .errors import InputValidationError

    if (
        page.expected_candidates_fingerprint is not None
        and page.expected_candidates_fingerprint != fingerprint
    ):
        raise InputValidationError(
            "agent continuation does not match the current candidate catalog",
            field="continuation", next_action="Drop continuation and run the search again.",
        )
    if page.offset >= len(unified) and request.continuation:
        raise InputValidationError(
            "agent continuation no longer points to an available candidate",
            field="continuation", next_action="Drop continuation and run the search again.",
        )


def _navigation_from_gap(gap: Mapping[str, Any]) -> dict[str, Any]:
    """Copy a gap's own next fields; do not invent a more general command."""

    fields: dict[str, Any] = {}
    action = gap.get("next_action")
    if isinstance(action, str) and action.strip():
        fields["next_action"] = action
    nxt = gap.get("next")
    argv = nxt.get("argv") if isinstance(nxt, Mapping) else None
    if isinstance(argv, Sequence) and not isinstance(argv, (str, bytes)) and argv:
        fields["next"] = {"argv": list(argv)}
    return fields


def discovery_next_fields(
    has_candidates: bool,
    gaps: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    if has_candidates:
        return {
            "next_action": (
                "Prefer a recipe, registered composite, then stable Insight; use a "
                "matching SQL product only when Insight cannot express the goal, and "
                "invoke the selected next.argv."
            )
        }
    first = gaps[0] if gaps else None
    fields = _navigation_from_gap(first) if isinstance(first, Mapping) else {}
    if "next_action" not in fields:
        fields["next_action"] = NO_CANDIDATE_NEXT_ACTION
        fields.setdefault("next", catalog_browse_next())
    return fields


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
    "HOST_CATALOG_ARGV",
    "NO_CANDIDATE_NEXT_ACTION",
    "UNRANKED_OPERATIONS",
    "UNRANKED_OPERATIONS_NEXT_ACTION",
    "apply_unranked_operation_handoff",
    "assert_discovery_page",
    "finish_discovery_candidates",
    "drop_auxiliary_catalog_tail",
    "capability_gaps_for_page",
    "catalog_browse_next",
    "discovery_next_fields",
    "host_arm_upgrade_argv",
    "host_catalog_next",
    "recognizer_routing_declaration",
    "is_short_catalog_lookup",
    "materialize_candidates",
    "select_authoritative_cards",
    "unranked_operation_ids",
    "unranked_operations_gap",
]
