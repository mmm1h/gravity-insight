"""Derived-formula matching and semantic gaps kept out of the main router."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .workspace_semantic_context import phrase_matches


_ANALYSIS_TASK_CUES = (
    "analyze",
    "analysis",
    "compare",
    "trend",
    " between ",
    " over ",
    " last ",
    " by ",
    "分析",
    "比较",
    "趋势",
    "环比",
    "同比",
    "过去",
    "本周",
    "上周",
    "按",
    "评估",
)


def unbound_gap(
    query: str,
    cards: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any] | None:
    from .agent_derived_metrics import derived_metric_gap, derived_metric_intent

    if not derived_metric_intent(query) or _registered_route_owns(query, cards):
        return None
    return derived_metric_gap(query)


def _registered_route_owns(
    query: str,
    cards: Sequence[Mapping[str, Any]],
) -> bool:
    if not cards:
        return False
    if any(card.get("kind") != "analysis_task" for card in cards):
        return True
    selected = f" {query.strip().casefold()} "
    return any(cue in selected for cue in _ANALYSIS_TASK_CUES)


def derived_matches(context: Any, query: str) -> tuple[tuple[Any, tuple[str, ...]], ...]:
    return tuple(
        (item, matches)
        for item in context.derived_metrics
        if (matches := tuple(phrase for phrase in item.phrases if phrase_matches(query, phrase)))
    )


def resolve_derived(
    query: str,
    matches: Sequence[tuple[Any, tuple[str, ...]]],
    *,
    competing: bool,
    direct: Sequence[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], bool] | None:
    if not matches:
        return None
    if len(matches) != 1 or competing or any(
        selector != "composite:derived_metrics" for selector in direct
    ):
        selectors = [
            *(f"semantic-derived:{item.name}" for item, _phrases in matches),
            *direct,
        ]
        return [], [multiple_gap(query, selectors)], True
    from .agent_derived_metrics import semantic_derived_card

    declaration, phrases = matches[0]
    return [semantic_derived_card(declaration, phrases)], [], True


def public_matches(
    matches: Sequence[tuple[Any, tuple[str, ...]]],
) -> list[dict[str, Any]]:
    return [
        {
            "kind": "derived_metric",
            "declaration": item.name,
            "matched_phrases": list(phrases),
            "target": {"kind": "product", "ref": "composite:derived_metrics"},
        }
        for item, phrases in matches
    ]


def multiple_gap(query: str, selectors: Sequence[str]) -> dict[str, Any]:
    from .agent_intent_routing import MULTIPLE_INTENTS

    return {
        "kind": "capability_gap",
        "code": MULTIPLE_INTENTS,
        "query": query,
        "reason": (
            "caller semantic evidence and registered product evidence identify "
            "multiple authoritative intents"
        ),
        "next_action": (
            "Split the request and discover each candidate_selectors value independently; "
            "do not execute either candidate from this response."
        ),
        "candidate_selectors": list(dict.fromkeys(selectors)),
        "weak_matches": [],
    }


def exclusion_gap(
    query: str,
    selectors: Sequence[str],
    exclusions: Sequence[tuple[Any, tuple[str, ...]]],
) -> dict[str, Any]:
    reasons = list(dict.fromkeys(item.reason for item, _phrases in exclusions))
    return {
        "kind": "capability_gap",
        "code": "SEMANTIC_CONTEXT_EXCLUDED",
        "query": query,
        "reason": "caller semantic exclusions block the matched target: " + "; ".join(reasons),
        "next_action": "Clarify the intended registered object; do not fall back to a raw operation.",
        "candidate_selectors": list(dict.fromkeys(selectors)),
        "weak_matches": [],
    }


__all__ = [
    "derived_matches",
    "exclusion_gap",
    "multiple_gap",
    "public_matches",
    "resolve_derived",
    "unbound_gap",
]
