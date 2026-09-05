"""Narrow arbitration for explicitly coordinated Agent product intents."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import re
from typing import Any


MULTIPLE_INTENTS = "MULTIPLE_INTENTS"

_BASE_COORDINATOR = re.compile(
    r"\s+and\s+|以及|同时|连同|和(?=其他)|"
    r"既(?:要|看)|也(?:要|看|比较)",
    re.IGNORECASE,
)
_CLAUSE_HANDOFFS = re.compile(
    r"以及|同时|连同|和(?=其他)|既(?:要|看)|也(?:要|看|比较)"
)
_PAIRED_COORDINATION = re.compile(r"既.+?(?:也|又)")
_PAIRED_MARKERS = re.compile(r"既(?:要|看)?|(?:也|又)(?:要|看|比较)?")
_TOGETHER_COORDINATION = re.compile(r"和[^。！？!?]+(?:一起|一并)")
_TOGETHER_HANDOFF = re.compile(r"和(?=[^。！？!?]+(?:一起|一并))")
_WRAPPER_SELECTORS = frozenset({
    "composite:saved_analysis", "composite:segment_snapshot", "composite:segment_members"
})


def adjacent_product_conflict(owner: str, query: str) -> bool:
    """Preserve proven compact conflicts without distributing foreign terms."""

    from .order_directory import order_directory_adjacent_intent

    selected = " ".join(query.strip().casefold().split())
    words = frozenset(re.findall(r"[a-z0-9_]+", selected))
    if order_directory_adjacent_intent(selected):
        return True
    if owner == "business_pulse":
        return bool(words & {
            "attribution", "audience", "cohort", "dashboard", "dimension",
            "dimensions", "event", "funnel", "journey", "material", "materials",
            "multidim", "multidimensional", "property", "retention", "saved",
            "scatter", "segment", "user", "users",
        }) or _contains(selected, (
            "归因", "分群", "人群", "看板", "多维", "事件", "漏斗", "旅程",
            "素材", "留存", "保存分析", "保存", "已存", "属性分析", "分布分析",
            "单用户",
        ))
    if owner == "dashboard_snapshot":
        return bool(words & {"chart"}) or "图表" in selected
    if owner == "dashboard_analysis":
        return bool(words & {
            "snapshot", "member", "favourite", "favorite", "saved", "material",
            "pulse", "multidim",
        }) or _contains(selected, (
            "control plane", "快照", "控制面", "成员", "收藏", "保存", "已存",
            "素材", "脉搏", "多维",
        ))
    if owner == "material_performance":
        return bool(words & {
            "dashboard", "promotion", "campaign", "business", "pulse", "multidim",
            "saved",
        }) or _contains(selected, (
            "看板", "推广", "经营", "业务脉搏", "多维", "保存", "已存", "脉搏",
            "脉动",
        ))
    if owner == "multidim":
        return bool(words & {
            "pulse", "business", "operating", "dashboard", "event", "funnel",
            "retention", "property", "scatter", "saved",
        }) or _contains(selected, (
            "经营", "业务脉搏", "看板", "事件分析", "漏斗", "留存", "属性分析",
            "分布分析", "保存", "已存",
        ))
    return False


def multiple_product_intents(
    query: str,
    *,
    inventory: Sequence[Mapping[str, Any]] | None = None,
) -> tuple[str, ...]:
    """Detect competing cards directly, then recognize coordinated clauses."""

    direct = _strict_query_selectors(query, inventory)
    clauses = _coordinated_clauses(query)
    selectors: list[str] = []
    matched_clauses = 0
    local_handoffs = explicit_clause_coordination(query)
    if len(clauses) >= 2:
        for clause in clauses:
            clause_selectors = _clause_selectors(
                clause, inventory, include_local_handoffs=local_handoffs
            )
            if clause_selectors:
                matched_clauses += 1
            for selector in clause_selectors:
                if selector not in selectors:
                    selectors.append(selector)
    coordinated = tuple(selectors) if matched_clauses >= 2 and len(selectors) >= 2 else ()
    if coordinated:
        return coordinated
    if set(direct) & _WRAPPER_SELECTORS and not local_handoffs:
        return ()
    if len(direct) >= 2:
        return direct
    positive = _positive_query_selectors(query)
    return positive if len(positive) >= 2 else ()


def _clause_selectors(
    clause: str,
    inventory: Sequence[Mapping[str, Any]] | None,
    *,
    include_local_handoffs: bool = False,
) -> tuple[str, ...]:
    from .capabilities import (
        analysis_query_spec_cards,
        composite_capability_cards,
    )

    if include_local_handoffs:
        if local := _local_clause_selectors(clause):
            return local
    direct = analysis_query_spec_cards(clause, domain=None, platform=None)
    composites = composite_capability_cards(
        clause, domain=None, platform=None, inventory=inventory
    )
    strict = [
        card for card in composites if card.get("match", {}).get("exact_selector")
    ]
    cards = [*direct, *strict] or composites
    selectors = tuple(
        str(card["selector"])
        for card in cards
        if card.get("kind") in {
            "analysis_query_spec",
            "segment_rule_spec",
            "segment_mutation",
            "composite",
        }
    )
    if selectors or not include_local_handoffs:
        return selectors
    return _positive_query_selectors(clause)


def _local_clause_selectors(clause: str) -> tuple[str, ...]:
    """Classify one coordinated clause without consulting the whole query."""

    from .material_asset import material_asset_capability_cards
    from .export import material_export_capability_cards
    from .table_lineage import table_lineage_capability_cards
    from .unavailable import unavailable_journey_gap

    if gap := unavailable_journey_gap(clause):
        return (f"gap:{gap['code']}",)
    return tuple(
        str(card["selector"])
        for cards in (
            table_lineage_capability_cards(clause, domain=None, platform=None),
            material_export_capability_cards(clause),
            material_asset_capability_cards(clause, domain=None, platform=None),
        )
        for card in cards
        if card.get("selector")
    )


def _strict_query_selectors(
    query: str, inventory: Sequence[Mapping[str, Any]] | None
) -> tuple[str, ...]:
    from .capabilities import (
        analysis_query_spec_cards,
        composite_capability_cards,
    )

    cards = [
        *analysis_query_spec_cards(query, domain=None, platform=None),
        *(
            card
            for card in composite_capability_cards(
                query, domain=None, platform=None, inventory=inventory
            )
            if card.get("match", {}).get("exact_selector")
        ),
    ]
    selectors = [str(card["selector"]) for card in cards]
    if _analysis_context_intent(query):
        selectors.append("composite:analysis_context")
    return tuple(dict.fromkeys(selectors))


def _positive_query_selectors(query: str) -> tuple[str, ...]:
    """Collect independent owner evidence without enumerating product pairs."""

    from .analysis import analysis_query_spec_cards
    from .business_pulse import business_pulse_intent
    from .company_usage import company_usage_intent
    from .analysis_default_dictionary import analysis_default_dictionary_intent
    from .realtime_event_catalog import realtime_event_catalog_intent
    from .custom_audience import custom_audience_intent
    from .bilibili_account_performance import (
        bilibili_account_performance_intent,
    )
    from .dashboard import dashboard_analysis_intent, dashboard_snapshot_intent
    from .material_performance import material_performance_intent
    from .title_package import title_package_intent
    from .multidim import multidim_intent
    from .order_directory import order_directory_intent
    from .order_trace import order_split_trace_intent
    from .promotion_performance import promotion_performance_intent
    from .attribution_performance import attribution_performance_intent
    from .advertiser_profile import advertiser_profile_query
    from .segment import segment_evaluate_intent, segment_mutation_intent
    from .segment_snapshot import segment_snapshot_intent
    from .segment_members import segment_members_intent

    analysis = analysis_query_spec_cards(query, domain=None, platform=None)
    claims = (
        *((str(card["selector"]), True) for card in analysis),
        ("composite:analysis_context", _analysis_context_intent(query)),
        ("composite:dashboard_snapshot", dashboard_snapshot_intent(query)),
        ("composite:dashboard_analysis", dashboard_analysis_intent(query)),
        ("analysis.segment.rule.spec", segment_evaluate_intent(query)),
        ("analysis.segment.mutation", segment_mutation_intent(query)),
        ("composite:segment_snapshot", segment_snapshot_intent(query)),
        ("composite:segment_members", segment_members_intent(query)),
        ("composite:order_directory", order_directory_intent(query)),
        ("composite:order_split_trace", order_split_trace_intent(query)),
        ("composite:material_performance", material_performance_intent(query)),
        ("composite:title_package", title_package_intent(query)),
        ("composite:promotion_performance", promotion_performance_intent(query)),
        ("composite:attribution_performance", attribution_performance_intent(query)),
        (
            "composite:bilibili_account_performance",
            bilibili_account_performance_intent(query),
        ),
        ("composite:advertiser_profile", advertiser_profile_query(query)),
        ("composite:multidim", multidim_intent(query)),
        ("composite:business_pulse", business_pulse_intent(query)),
        ("composite:company_usage", company_usage_intent(query)),
        (
            "composite:analysis_default_dictionary",
            analysis_default_dictionary_intent(query),
        ),
        (
            "composite:realtime_event_catalog",
            realtime_event_catalog_intent(query),
        ),
        ("composite:custom_audience", custom_audience_intent(query)),
    )
    return tuple(selector for selector, claimed in claims if claimed)


def _analysis_context_intent(query: str) -> bool:
    selected = " ".join(query.strip().casefold().split())
    return _contains(selected, (
        "analysis context", "analysis metadata", "analysis vocabulary",
        "分析上下文", "分析元数据",
    ))


def explicit_clause_coordination(query: str) -> bool:
    """True only for explicit Chinese coordinators, not English list-and."""

    return bool(
        _CLAUSE_HANDOFFS.search(query)
        or _PAIRED_COORDINATION.search(query)
        or _TOGETHER_COORDINATION.search(query)
    )


def _coordinated_clauses(query: str) -> tuple[str, ...]:
    """Split only explicit coordination forms while preserving clause nouns."""

    splitters = [_BASE_COORDINATOR]
    if _PAIRED_COORDINATION.search(query):
        splitters.append(_PAIRED_MARKERS)
    if _TOGETHER_COORDINATION.search(query):
        splitters.append(_TOGETHER_HANDOFF)
    clauses = (query,)
    for splitter in splitters:
        clauses = tuple(
            piece
            for clause in clauses
            for piece in splitter.split(clause)
        )
    return tuple(clause.strip() for clause in clauses if clause.strip())


def multiple_intent_gap(query: str) -> list[dict[str, object]]:
    """Return a machine-decidable gap for an explicit multi-product request."""

    intents = multiple_product_intents(query)
    if not intents:
        return []
    from .unavailable import unavailable_journey_gap

    selected: list[dict[str, object]] = [product_selection_gap(query, intents)]
    seen: set[str] = set()
    for clause in _coordinated_clauses(query):
        gap = unavailable_journey_gap(clause)
        if gap is None or str(gap["code"]) in seen:
            continue
        seen.add(str(gap["code"]))
        selected.append(gap)
    return selected


def product_selection_gap(
    query: str,
    selectors: Sequence[str],
    *,
    reason: str = (
        "multiple authoritative product intents were identified; split the "
        "request and discover each product independently"
    ),
) -> dict[str, object]:
    """Centralize the fail-closed response for any multi-product selector."""

    return {
        "kind": "capability_gap",
        "code": MULTIPLE_INTENTS,
        "query": query,
        "reason": reason,
        "next_action": (
            "For each candidate_selectors value, run `gravity agent-catalog describe "
            "<selector>` independently; follow a returned gap card's own next_action, "
            "and execute only a returned authoritative product card marked executable."
        ),
        "candidate_selectors": list(dict.fromkeys(map(str, selectors))),
        "weak_matches": [],
    }


def unique_authoritative_cards(
    cards: Sequence[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    """Enforce one authoritative card per selector while preserving order."""

    selected: list[Mapping[str, Any]] = []
    seen: set[str] = set()
    for card in cards:
        selector = str(card.get("selector", ""))
        if selector not in seen:
            seen.add(selector)
            selected.append(card)
    return selected


def _contains(value: str, terms: tuple[str, ...]) -> bool:
    return any(term in value for term in terms)


__all__ = [
    "MULTIPLE_INTENTS",
    "adjacent_product_conflict",
    "multiple_product_intents",
    "explicit_clause_coordination",
    "multiple_intent_gap",
    "product_selection_gap",
    "unique_authoritative_cards",
]
