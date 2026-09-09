"""Shared discovery response protocol and projections, independent of routing."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


SCHEMA_VERSION = "gravity.agent.v1"
DEFAULT_LIMIT = 3
CATALOG_BROWSE_ARGV = ["gravity", "agent-catalog", "categories"]
ANSWERABLE_LIMIT = 8
NO_CANDIDATE_NEXT_ACTION = (
    "Use an `answerable` catalog_ref if one matches the goal; otherwise browse "
    "`gravity agent-catalog categories` then `category` and `describe` to "
    "confirm the capability is absent; do not execute weak partial matches "
    "or invent a selector."
)


def catalog_browse_next() -> dict[str, Any]:
    return {"argv": list(CATALOG_BROWSE_ARGV)}


def answerable_examples(client: Any) -> list[dict[str, Any]]:
    """One executable registered ask per domain, from existing caller language."""

    from .caller_language import caller_language_fields
    from .product_inventory import canonical_capability_cards

    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for card in sorted(
        canonical_capability_cards(client),
        key=lambda item: (str(item.get("domain") or ""), str(item.get("selector") or "")),
    ):
        selector = str(card.get("selector") or "")
        domain = str(card.get("domain") or "")
        phrases = caller_language_fields(selector)
        if (
            domain in seen
            or not phrases
            or not card.get("executable")
            or card.get("effect") == "mutation"
            or selector.startswith("gap:")
        ):
            continue
        seen.add(domain)
        selected.append({
            "catalog_ref": selector,
            "query": phrases[0],
            "next": {"argv": ["gravity", "agent-catalog", "describe", selector]},
        })
        if len(selected) >= ANSWERABLE_LIMIT:
            break
    return selected


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
    items = gap.get("answerable")
    if isinstance(items, Sequence) and not isinstance(items, (str, bytes)):
        copied = [dict(item) for item in items if isinstance(item, Mapping)]
        if copied:
            fields["answerable"] = copied
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


def ndjson_metadata(value: Any) -> dict[str, Any]:
    """Preserve the Agent protocol when candidates become NDJSON rows."""

    if not isinstance(value, Mapping) or value.get("schema_version") != SCHEMA_VERSION:
        return {}
    return {
        "payload_schema_version": SCHEMA_VERSION,
        "ok": value.get("ok"),
        "offline": value.get("offline"),
        "network_called": value.get("network_called"),
        "mode": value.get("mode"),
        "routing_mode": value.get("routing_mode"),
        "routing": value.get("routing"),
        "count": value.get("count"),
        "total": value.get("total"),
        "query": value.get("query"),
        "continuation_token": value.get("continuation_token"),
        "next_action": value.get("next_action"),
        "execution": value.get("execution"),
        "scope": value.get("scope"),
        "fallbacks": value.get("fallbacks"),
        "catalog_warnings": value.get("catalog_warnings"),
        "capability_gaps": value.get("capability_gaps"),
        "match_policy": value.get("match_policy"),
    }


__all__ = [
    "ANSWERABLE_LIMIT",
    "CATALOG_BROWSE_ARGV",
    "DEFAULT_LIMIT",
    "NO_CANDIDATE_NEXT_ACTION",
    "SCHEMA_VERSION",
    "answerable_examples",
    "catalog_browse_next",
    "discovery_next_fields",
    "ndjson_metadata",
]
