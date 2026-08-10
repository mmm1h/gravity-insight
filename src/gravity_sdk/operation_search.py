"""Pure ranking helpers for the local operation catalog."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any


_SEARCH_ALIASES: Mapping[str, tuple[str, ...]] = {
    "应用": ("app", "application"),
    "广告": ("promotion", "advertiser", "campaign"),
    "推广": ("promotion", "advertiser", "campaign"),
    "活动": ("campaign",),
    "报表": ("report", "query", "metric"),
    "指标": ("metric", "report"),
    "素材": ("material", "creative"),
    "归因": ("attribution", "postback", "backtrack"),
    "分群": ("segment", "cohort"),
    "用户": ("user", "account"),
    "事件": ("event",),
    "漏斗": ("funnel",),
    "留存": ("retention",),
    "看板": ("dashboard",),
    "订单": ("order",),
    "变现": ("monetization",),
    "模板": ("template",),
    "属性": ("property",),
    "字段": ("property", "field", "metric"),
    "配置": ("config", "configuration"),
    "campaign": ("推广", "广告", "活动"),
    "dashboard": ("看板",),
    "segment": ("分群",),
    "material": ("素材",),
}


def normalize_search_text(value: str) -> str:
    return " ".join(value.casefold().strip().split())


def ordered_search(
    scored: list[tuple[int, str, dict[str, Any]]], query: str
) -> list[dict[str, Any]]:
    def key(row: tuple[int, str, dict[str, Any]]) -> tuple[int, int, str]:
        exact = normalize_search_text(str(row[2].get("operation_id", ""))) == query
        rank = 0 if exact else _presentation_rank(row[2]) + 1
        return rank, -row[0], row[1]

    return [item for _, _, item in sorted(scored, key=key)]


def first_non_callable(items: list[dict[str, Any]]) -> int:
    return next(
        (
            index
            for index, item in enumerate(items)
            if not bool(item.get("executable", True))
        ),
        len(items),
    )


def expose_non_callable_result(
    items: list[dict[str, Any]], limit: int, stability: str | None
) -> list[dict[str, Any]]:
    first_other = first_non_callable(items)
    if stability is None and limit > 1 and limit <= first_other < len(items):
        items.insert(limit - 1, items.pop(first_other))
    return items


def search_page_limit(
    items: list[dict[str, Any]],
    requested_limit: int,
    *,
    continuation: str | None,
    stability: str | None,
) -> int:
    if continuation is not None or stability is not None:
        return requested_limit
    callable_count = first_non_callable(items)
    if callable_count < len(items):
        return min(requested_limit, callable_count + 1)
    return requested_limit


def search_score(
    query: str,
    *,
    operation_id: str,
    domain: str,
    resource: str,
    platform: str,
    description: str,
) -> tuple[int, list[str]]:
    fields = {
        "operation_id": normalize_search_text(operation_id),
        "domain": normalize_search_text(domain),
        "resource": normalize_search_text(resource),
        "platform": normalize_search_text(platform),
        "description": normalize_search_text(description),
    }
    terms = {query}
    terms.update(re.findall(r"[a-z0-9_]+|[\u3400-\u9fff]+", query))
    for key, values in _SEARCH_ALIASES.items():
        if key in query or key in terms:
            terms.update(normalize_search_text(value) for value in values)
    matched_on: set[str] = set()
    score = 0
    weights = {
        "operation_id": 16,
        "domain": 10,
        "resource": 9,
        "platform": 8,
        "description": 6,
    }
    for field, value in fields.items():
        if not value:
            continue
        if value == query:
            score += weights[field] * 8
            matched_on.add(field)
        elif query in value:
            score += weights[field] * 5
            matched_on.add(field)
        for term in sorted(terms - {query}):
            if term and term in value:
                score += weights[field]
                matched_on.add(field)
    return score, sorted(matched_on)


def _presentation_rank(operation: Mapping[str, Any]) -> int:
    if (
        operation.get("stability") == "stable"
        and bool(operation.get("executable", True))
        and operation.get("health") not in {"blocked", "upstream_changed"}
    ):
        return 0
    return 1 if bool(operation.get("executable", True)) else 2


__all__ = [
    "expose_non_callable_result",
    "first_non_callable",
    "normalize_search_text",
    "ordered_search",
    "search_page_limit",
    "search_score",
]
