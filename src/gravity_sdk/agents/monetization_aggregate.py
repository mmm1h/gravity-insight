"""Canonical Agent product card for D28 monetization aggregate reads."""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping
from typing import Any

from .intent_text import affirmative_intent_text


MONETIZATION_AGGREGATE_SELECTOR = ".".join(("report", "get", "query"))
MONETIZATION_AGGREGATE_INPUT_TEMPLATE: Mapping[str, Any] = {
    "custom_metrics_list": [],
    "data_conf": {
        "accumulate": False,
        "asa_time_zone": "UTC",
        "decimal_point": 2,
        "minigame_pay_shared_ratio": 100,
        "minigame_pay_shared_ratio_ios": 100,
        "return_all_metrics": True,
    },
    "data_dims": ["monetization_platform", "ad_unit_id"],
    "data_topic": "monetization_report",
    "date_list": ["<start:YYYY-MM-DD>", "<end:YYYY-MM-DD>"],
    "filters": [
        {
            "field": "app_id",
            "operator": "EQUALS",
            "values": ["<catalog-app-id>"],
        }
    ],
    "metrics_list": ["reporting_ad_revenue"],
    "time_dims": "day",
}


def monetization_aggregate_input_template() -> dict[str, Any]:
    """Return a fresh raw-operation input backed by the proven example."""

    return copy.deepcopy(dict(MONETIZATION_AGGREGATE_INPUT_TEMPLATE))


MONETIZATION_AGGREGATE_CAPABILITY: Mapping[str, Any] = {
    "kind": "operation",
    "selector": MONETIZATION_AGGREGATE_SELECTOR,
    "operation_id": MONETIZATION_AGGREGATE_SELECTOR,
    "domain": "report",
    "description": (
        "按变现平台、广告位和日期汇总已观察变现指标与收入；"
        "这是聚合变现 / monetization aggregate，不是单日逐行变现明细。"
        "App 由调用方以 EQUALS 过滤提供，服务端一次返回完整 list 与 page_info.total，"
        "不接受 page/page_size。"
    ),
    "boundaries": (
        "这是聚合变现 / monetization aggregate，不是单日逐行变现明细。",
        "App 由调用方以 EQUALS 过滤提供，服务端一次返回完整 list 与 page_info.total，不接受 page/page_size。",
    ),
    "effect": "read",
    "executable": True,
    "plan_executable": True,
    "natural_language_auto_execute": False,
    "input_schema": {
        "date_list": {
            "type": "array",
            "item_type": "string",
            "required": True,
            "min_items": 2,
            "max_items": 2,
            "description": "Closed [start, end] YYYY-MM-DD window.",
        },
        "metrics_list": {
            "type": "array",
            "item_type": "string",
            "required": True,
            "min_items": 1,
            "description": "Observed monetization metric names.",
        },
        "filters": {
            "type": "array",
            "item_type": "object",
            "required": False,
            "description": "Must include app_id EQUALS one catalog App.",
        },
    },
    "required_inputs": ("date_list", "metrics_list"),
    "missing_inputs": ["date_list", "metrics_list"],
    "input_template": monetization_aggregate_input_template(),
    "match": {
        "confidence": "strong",
        "coverage": 1.0,
        "matched_terms": ["monetization platform and ad placement"],
        "missing_terms": [],
        "score": 100,
        "exact_selector": True,
    },
    "next": {
        "ready_without_input": False,
        "argv": [
            "gravity",
            "run",
            MONETIZATION_AGGREGATE_SELECTOR,
            "--input",
            "<json-object-or-file>",
        ],
        "call_count_after_discovery": 1,
    },
}


def monetization_aggregate_capability_inventory() -> tuple[dict[str, Any], ...]:
    """Return the single canonical card backed by the stable operation."""

    return (copy.deepcopy(dict(MONETIZATION_AGGREGATE_CAPABILITY)),)


def is_authoritative_monetization_aggregate_card(card: Mapping[str, Any]) -> bool:
    """Keep the product owner ahead of a generic card for the same operation."""

    return (
        card.get("kind") == "operation"
        and card.get("selector") == MONETIZATION_AGGREGATE_SELECTOR
    )


def monetization_aggregate_query(query: str) -> bool:
    """Recognize platform/slot/date monetization totals, not row-level detail."""

    selected = affirmative_intent_text(query)
    if selected in {MONETIZATION_AGGREGATE_SELECTOR, "monetization aggregate"}:
        return True
    words = frozenset(re.findall(r"[a-z0-9_]+", selected))
    if words & {"detail", "details"} or any(
        term in selected for term in ("明细", "逐行", "逐笔", "细账")
    ):
        return False
    english = (
        bool(words & {"monetization", "iap", "revenue"})
        and bool(words & {"aggregate", "aggregated", "summary", "summarize", "total", "totals"})
        and bool(words & {"platform", "platforms", "slot", "ad", "placement", "date", "dates"})
    )
    chinese = (
        ("变现" in selected or "收入" in selected)
        and any(term in selected for term in ("汇总", "聚合", "合计"))
        and (
            any(term in selected for term in ("平台", "广告位", "日期"))
            or "聚合变现" in selected
        )
    )
    return english or chinese


def monetization_aggregate_capability_cards(
    query: str, *, domain: str | None = None, platform: str | None = None
) -> list[dict[str, Any]]:
    if platform is not None or domain not in {None, "report", "analysis"}:
        return []
    exact = query.strip().casefold() == MONETIZATION_AGGREGATE_SELECTOR
    if not exact and not monetization_aggregate_query(query):
        return []
    return [copy.deepcopy(dict(MONETIZATION_AGGREGATE_CAPABILITY))]


__all__ = [
    "MONETIZATION_AGGREGATE_CAPABILITY",
    "MONETIZATION_AGGREGATE_INPUT_TEMPLATE",
    "MONETIZATION_AGGREGATE_SELECTOR",
    "is_authoritative_monetization_aggregate_card",
    "monetization_aggregate_capability_cards",
    "monetization_aggregate_capability_inventory",
    "monetization_aggregate_input_template",
    "monetization_aggregate_query",
]
