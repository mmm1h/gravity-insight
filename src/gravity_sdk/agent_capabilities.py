"""Built-in Agent capabilities and deterministic query normalization.

This module contains only value-free product metadata.  Keeping composite
discovery beside the Agent protocol avoids making callers reverse-engineer
CLI subcommands or the Plan adapter allowlist.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import re
from typing import Any

from .find import query_match


_ASCII_WORD = re.compile(r"[a-z0-9_]+", re.IGNORECASE)
AGENT_SCOPE = (
    "workspace_recipes_analysis_query_spec_segment_rule_spec_stable_insight_composites_"
    "sql_products_governed_exports_and_local_metadata"
)

_COMPOSITE_CAPABILITIES: tuple[Mapping[str, Any], ...] = (
    {
        "name": "analysis_context",
        "domain": "analysis",
        "aliases": (
            "analysis context",
            "analysis metadata",
            "analysis vocabulary",
            "分析上下文",
            "分析元数据",
        ),
        "description": (
            "并发读取事件、事件属性、用户属性、指标和报表模板的固定分析上下文。"
        ),
        "required_inputs": ("app",),
        "input_schema": {
            "app": {"type": "string", "required": True, "nullable": False},
        },
    },
    {
        "name": "app_snapshot",
        "domain": "app",
        "aliases": (
            "app snapshot",
            "application snapshot",
            "app governance",
            "应用快照",
            "应用治理",
        ),
        "description": (
            "并发读取 App 详情、实时事件、容量、权限菜单、角色和模板的治理快照。"
        ),
        "required_inputs": ("app",),
        "input_schema": {
            "app": {"type": "string", "required": True, "nullable": False},
        },
    },
    {
        "name": "attribution_snapshot",
        "domain": "attribution",
        "aliases": (
            "attribution snapshot",
            "attribution configuration",
            "归因快照",
            "归因配置",
        ),
        "description": "并发读取已登记归因映射、回溯与采集配置的固定快照。",
        "required_inputs": ("app",),
        "input_schema": {
            "app": {"type": "string", "required": True, "nullable": False},
        },
    },
    {
        "name": "saved_analysis",
        "domain": "analysis",
        "accepted_domains": ("analysis", "report"),
        "aliases": (
            "saved analysis",
            "saved report template",
            "saved report templates",
            "saved report",
            "保存分析",
            "保存的分析",
            "已存分析",
            "保存报表模板",
        ),
        "intent_terms": ("saved", "save", "保存", "已存"),
        "description": (
            "按稳定引用列出、读取或严格重放保存分析；重放仅接受能由现有 "
            "Analysis Spec 编译器原样验证的定义。"
        ),
        "required_inputs": ("app", "ref"),
        "input_schema": {
            "app": {
                "type": "string|integer",
                "required": True,
                "nullable": False,
            },
            "ref": {
                "type": "string|integer",
                "required": True,
                "nullable": False,
            },
            "mode": {
                "type": "string",
                "required": False,
                "enum": ["prepare", "run"],
                "default": "run",
            },
        },
    },
    {
        "name": "multidim",
        "domain": "report",
        "aliases": (
            "multidim",
            "multi dimension",
            "multidimensional report",
            "cross dimension",
            "多维分析",
            "交叉维度",
        ),
        "description": (
            "执行受合同约束的多维报表查询，并可组合总计与维度元数据。"
        ),
        "required_inputs": ("app", "inputs"),
        "input_schema": {
            "app": {"type": "string", "required": True, "nullable": False},
            "inputs": {"type": "object", "required": True, "nullable": False},
        },
    },
    {
        "name": "business_pulse",
        "domain": "report",
        "aliases": (
            "business pulse",
            "business analysis",
            "operating pulse",
            "经营分析",
            "经营脉搏",
            "业务脉搏",
        ),
        "intent_terms": ("pulse", "business analysis", "经营", "业务脉搏"),
        "description": (
            "并发汇总多个 App 在指定时间窗内的核心经营指标、趋势和可复核来源。"
        ),
        "required_inputs": ("apps", "start", "end"),
        "input_schema": {
            "apps": {
                "type": "array",
                "item_type": "string",
                "required": True,
                "nullable": False,
                "min_items": 1,
            },
            "start": {"type": "string", "required": True, "nullable": False},
            "end": {"type": "string", "required": True, "nullable": False},
        },
    },
)


def normalize_agent_query(query: str) -> str:
    """Normalize only safe English inflections; do not guess business meaning."""

    def singular(match: re.Match[str]) -> str:
        word = match.group(0)
        lowered = word.casefold()
        if len(lowered) > 4 and lowered.endswith("ies"):
            return lowered[:-3] + "y"
        if (
            len(lowered) > 3
            and lowered.endswith("s")
            and not lowered.endswith(("ss", "us", "is"))
        ):
            return lowered[:-1]
        return lowered

    return _ASCII_WORD.sub(singular, query.strip().casefold())


def agent_query_match(
    query: str, *values: object, score: int = 0
) -> dict[str, Any]:
    """Apply the shared matcher after bounded, deterministic normalization."""

    return query_match(normalize_agent_query(query), *values, score=score)


def operation_query_match(query: str, item: Mapping[str, Any]) -> dict[str, Any]:
    """Match one operation while making selector-shaped queries fail closed."""

    match = agent_query_match(
        query,
        item.get("operation_id"),
        item.get("domain"),
        item.get("resource"),
        item.get("action"),
        item.get("platform"),
        item.get("description"),
        score=int(item.get("score", 0)),
    )
    operation_id = str(item.get("operation_id", ""))
    normalized_query = query.strip().casefold()
    if operation_id.casefold() == normalized_query:
        return {
            **match,
            "confidence": "strong",
            "coverage": 1.0,
            "matched_terms": [normalized_query],
            "missing_terms": [],
            "exact_selector": True,
        }
    selector_shaped = bool(query.isascii() and " " not in query and "." in query)
    if selector_shaped:
        return {
            **match,
            "confidence": "partial",
            "coverage": 0.0,
            "matched_terms": [],
            "missing_terms": [normalized_query],
        }
    return match


def composite_capability_inventory() -> tuple[Mapping[str, Any], ...]:
    """Return the immutable, value-free built-in composite inventory."""

    return _COMPOSITE_CAPABILITIES


def analysis_query_spec_cards(
    query: str, *, domain: str | None, platform: str | None
) -> list[dict[str, Any]]:
    """Expose the offline Analysis compiler as a first-class Agent handoff."""

    from .agent_analysis import analysis_query_spec_cards as build_cards
    from .agent_segment import segment_rule_spec_cards as segment_cards

    return segment_cards(query, domain=domain, platform=platform) or build_cards(
        query, domain=domain, platform=platform
    )


def composite_capability_cards(
    query: str,
    *,
    domain: str | None,
    platform: str | None,
    inventory: Sequence[Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Return strongly matching Plan composite cards without network access."""

    if platform is not None:
        return []
    normalized = normalize_agent_query(query)
    cards = [
        card
        for definition in inventory or _COMPOSITE_CAPABILITIES
        if (card := _composite_card(query, normalized, domain, definition)) is not None
    ]
    return sorted(
        cards,
        key=lambda card: (
            not bool(card["match"].get("exact_selector")),
            -float(card["match"].get("coverage", 0)),
            str(card["composite"]),
        ),
    )


def capability_handoff_cards(
    query: str,
    *,
    domain: str | None,
    platform: str | None,
    export_inventory: Sequence[Mapping[str, Any]],
    composite_inventory: Sequence[Mapping[str, Any]] | None,
) -> tuple[list[dict[str, Any]], bool]:
    """Select direct product handoffs and whether they exclude local catalogs."""

    from .agent_export import export_capability_cards
    from .agent_table_lineage import table_lineage_capability_cards
    from .agent_user_journey import user_journey_capability_cards

    exports = export_capability_cards(
        query, domain=domain, platform=platform, inventory=export_inventory
    )
    lineage = table_lineage_capability_cards(
        query, domain=domain, platform=platform
    )
    journeys = user_journey_capability_cards(
        query, domain=domain, platform=platform
    )
    products = [
        *analysis_query_spec_cards(query, domain=domain, platform=platform),
        *composite_capability_cards(
            query,
            domain=domain,
            platform=platform,
            inventory=composite_inventory,
        ),
    ]
    return exports or lineage or journeys or products, bool(
        exports or lineage or journeys
    )


def should_load_capability_catalog(
    query: str,
    *,
    domain: str | None,
    platform: str | None,
    direct_cards: Sequence[Mapping[str, Any]],
    catalog_excluded: bool,
) -> bool:
    """Keep catalog loading compatible while enabling Analysis task candidates."""

    from .agent_handoff import is_analysis_task_handoff_query

    task_catalog = (
        not direct_cards
        and platform is None
        and domain in {None, "analysis"}
        and is_analysis_task_handoff_query(query)
    )
    return (
        not catalog_excluded
        and platform is None
        and (domain is None or task_catalog)
    )


def merge_catalog_handoff_cards(
    query: str,
    *,
    domain: str | None,
    platform: str | None,
    direct_cards: list[dict[str, Any]],
    catalog: list[dict[str, Any]],
    warnings: list[str],
    sources: Any | None,
) -> list[dict[str, Any]]:
    """Give recipes/vocabulary precedence, otherwise emit one Analysis task."""

    from .agent_analysis_task import analysis_task_cards
    from .agent_handoff import is_analysis_task_handoff_query
    from .agent_vocabulary import is_authoritative_local_metadata_card

    recipes = [card for card in catalog if card.get("kind") == "recipe"]
    local = [card for card in catalog if is_authoritative_local_metadata_card(card)]
    task_cards = (
        analysis_task_cards(
            query,
            metadata_rows=_analysis_task_metadata_rows(catalog, warnings, sources),
            domain=domain,
            platform=platform,
        )
        if (
            is_analysis_task_handoff_query(query)
            and not direct_cards
            and not recipes
            and not local
        )
        else []
    )
    return task_cards or [*catalog, *direct_cards]


def authoritative_capability_cards(
    cards: Sequence[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    """Return the first exclusive discovery product class, if one exists."""

    from .agent_segment import is_authoritative_direct_card
    from .agent_user_journey import is_user_journey_card
    from .agent_vocabulary import is_authoritative_local_metadata_card

    return [card for card in cards if is_authoritative_direct_card(card)] or [
        card
        for card in cards
        if card.get("kind") == "analysis_task" or is_user_journey_card(card)
    ] or [card for card in cards if is_authoritative_local_metadata_card(card)]


def _analysis_task_metadata_rows(
    catalog: Sequence[Mapping[str, Any]], warnings: Sequence[str], sources: Any | None
) -> tuple[Mapping[str, Any], ...] | None:
    if sources is not None:
        if not bool(getattr(sources, "metadata_catalog_available", True)):
            return None
        return tuple(getattr(sources, "metadata_inventory", ()))
    if any(
        "metadata catalog is unavailable" in warning.casefold()
        for warning in warnings
    ):
        return None
    return tuple(
        {
            "kind": card.get("metadata_kind"),
            "name": card.get("name"),
            "cname": card.get("display_name"),
            "operation_id": card.get("operation_id"),
            "app_id": card.get("app_id"),
            "scope": card.get("scope"),
            "source": card.get("source"),
        }
        for card in catalog
        if card.get("kind") == "metadata"
    )


def _composite_card(
    query: str,
    normalized: str,
    domain: str | None,
    definition: Mapping[str, Any],
) -> dict[str, Any] | None:
    name = str(definition["name"])
    selected_domain = str(definition["domain"])
    accepted_domains = tuple(
        str(value)
        for value in definition.get("accepted_domains", (selected_domain,))
    )
    if domain is not None and domain not in accepted_domains:
        return None
    intent = tuple(str(value) for value in definition.get("intent_terms", ()))
    if intent and not any(term in query.casefold() for term in intent):
        return None
    selector = f"composite:{name}"
    aliases = tuple(str(value) for value in definition.get("aliases", ()))
    match = agent_query_match(
        query,
        selector,
        name,
        name.replace("_", " "),
        selected_domain,
        *accepted_domains,
        definition.get("description"),
        *aliases,
    )
    if normalized in {selector.casefold(), name.casefold()}:
        match = _exact_match(match, normalized)
    if match["confidence"] != "strong":
        return None
    required = [str(value) for value in definition.get("required_inputs", ())]
    input_schema = {
        str(key): dict(value)
        for key, value in definition.get("input_schema", {}).items()
        if isinstance(value, Mapping)
    }
    return {
        "kind": "composite",
        "selector": selector,
        "composite": name,
        "domain": selected_domain,
        "description": str(definition.get("description", "")),
        "effect": "read",
        "executable": True,
        "input_schema": input_schema,
        "required_inputs": required,
        "match": match,
        "next": {
            "ready_without_input": not required,
            "argv": ["gravity", "plan", "run", "--input", "<plan.json>"],
        },
    }


def _exact_match(match: Mapping[str, Any], normalized: str) -> dict[str, Any]:
    return {
        **dict(match),
        "confidence": "strong",
        "coverage": 1.0,
        "matched_terms": [normalized],
        "missing_terms": [],
        "exact_selector": True,
    }


__all__ = [
    "AGENT_SCOPE",
    "agent_query_match",
    "analysis_query_spec_cards",
    "authoritative_capability_cards",
    "capability_handoff_cards",
    "composite_capability_cards",
    "composite_capability_inventory",
    "merge_catalog_handoff_cards",
    "normalize_agent_query",
    "operation_query_match",
    "should_load_capability_catalog",
]
