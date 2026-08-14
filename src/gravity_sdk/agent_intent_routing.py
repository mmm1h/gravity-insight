"""Narrow arbitration for explicitly coordinated Agent product intents."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import re
from typing import Any


MULTIPLE_INTENTS = "MULTIPLE_INTENTS"

_COORDINATOR = re.compile(r"\s+and\s+|以及|同时", re.IGNORECASE)
_WRAPPER_SELECTORS = frozenset({"composite:saved_analysis", "composite:segment_snapshot"})


def adjacent_product_conflict(owner: str, query: str) -> bool:
    """Preserve proven compact conflicts without distributing foreign terms."""

    from .agent_order_directory import order_directory_adjacent_intent

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
    clauses = tuple(part.strip() for part in _COORDINATOR.split(query) if part.strip())
    selectors: list[str] = []
    matched_clauses = 0
    if len(clauses) >= 2:
        for clause in clauses:
            clause_selectors = _clause_selectors(clause, inventory)
            if clause_selectors:
                matched_clauses += 1
            for selector in clause_selectors:
                if selector not in selectors:
                    selectors.append(selector)
    coordinated = tuple(selectors) if matched_clauses >= 2 and len(selectors) >= 2 else ()
    if coordinated:
        return coordinated
    if set(direct) & _WRAPPER_SELECTORS:
        return ()
    if len(direct) >= 2:
        return direct
    positive = _positive_query_selectors(query)
    return positive if len(positive) >= 2 else ()


def _clause_selectors(
    clause: str, inventory: Sequence[Mapping[str, Any]] | None
) -> tuple[str, ...]:
    from .agent_capabilities import (
        analysis_query_spec_cards,
        composite_capability_cards,
    )

    direct = analysis_query_spec_cards(clause, domain=None, platform=None)
    composites = composite_capability_cards(
        clause, domain=None, platform=None, inventory=inventory
    )
    strict = [
        card for card in composites if card.get("match", {}).get("exact_selector")
    ]
    cards = [*direct, *strict] or composites
    return tuple(
        str(card["selector"])
        for card in cards
        if card.get("kind") in {
            "analysis_query_spec",
            "segment_rule_spec",
            "composite",
        }
    )


def _strict_query_selectors(
    query: str, inventory: Sequence[Mapping[str, Any]] | None
) -> tuple[str, ...]:
    from .agent_capabilities import (
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

    from .agent_analysis import analysis_query_spec_cards
    from .agent_business_pulse import business_pulse_intent
    from .agent_company_usage import company_usage_intent
    from .agent_dashboard import dashboard_analysis_intent, dashboard_snapshot_intent
    from .agent_material_performance import material_performance_intent
    from .agent_title_package import title_package_intent
    from .agent_multidim import multidim_intent
    from .agent_order_directory import order_directory_intent
    from .agent_order_trace import order_split_trace_intent
    from .agent_promotion_performance import promotion_performance_intent
    from .agent_segment import segment_evaluate_intent
    from .agent_segment_snapshot import segment_snapshot_intent

    analysis = analysis_query_spec_cards(query, domain=None, platform=None)
    claims = (
        *((str(card["selector"]), True) for card in analysis),
        ("composite:analysis_context", _analysis_context_intent(query)),
        ("composite:dashboard_snapshot", dashboard_snapshot_intent(query)),
        ("composite:dashboard_analysis", dashboard_analysis_intent(query)),
        ("analysis.segment.rule.spec", segment_evaluate_intent(query)),
        ("composite:segment_snapshot", segment_snapshot_intent(query)),
        ("composite:order_directory", order_directory_intent(query)),
        ("composite:order_split_trace", order_split_trace_intent(query)),
        ("composite:material_performance", material_performance_intent(query)),
        ("composite:title_package", title_package_intent(query)),
        ("composite:promotion_performance", promotion_performance_intent(query)),
        ("composite:multidim", multidim_intent(query)),
        ("composite:business_pulse", business_pulse_intent(query)),
        ("composite:company_usage", company_usage_intent(query)),
    )
    return tuple(selector for selector, claimed in claims if claimed)


def _analysis_context_intent(query: str) -> bool:
    selected = " ".join(query.strip().casefold().split())
    return _contains(selected, (
        "analysis context", "analysis metadata", "analysis vocabulary",
        "分析上下文", "分析元数据",
    ))


def multiple_intent_gap(query: str) -> list[dict[str, object]]:
    """Return a machine-decidable gap for an explicit multi-product request."""

    intents = multiple_product_intents(query)
    if not intents:
        return []
    return [{
        "kind": "capability_gap",
        "code": MULTIPLE_INTENTS,
        "query": query,
        "reason": (
            "multiple authoritative product intents were identified; split the "
            "request and discover each product independently"
        ),
        "candidate_selectors": list(intents),
        "weak_matches": [],
    }]


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
    "multiple_intent_gap",
    "unique_authoritative_cards",
]
