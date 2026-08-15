"""Natural-language gaps owned by unavailable report journeys."""

from __future__ import annotations

import re
from typing import Any

from .agent_gap import unavailable_gap


def unavailable_report_gap(query: str) -> dict[str, Any] | None:
    selected = " ".join(query.strip().casefold().split())
    words = frozenset(re.findall(r"[a-z0-9_]+", selected))
    if _report_directory(selected, words):
        return unavailable_gap(
            query, code="REPORT_DIRECTORY_ITEM_SCHEMA_MISSING",
            journey="report_directory_and_definition",
            reason="Own, shared, and MasterKey report lists are proven reads but all observed first pages are empty.",
            next_action=(
                "Use a tenant with one visible report to capture a single non-empty list item, "
                "then feed its in-memory parent id to the minimal detail read."
            ),
        )
    if _report_subscriptions(selected, words):
        return unavailable_gap(
            query, code="REPORT_SUBSCRIPTION_ITEM_SCHEMA_MISSING",
            journey="report_subscriptions",
            reason="The subscription list envelope is known, but the only observed page was explicitly empty.",
            next_action=(
                "In a tenant with a subscription, repeat page 1 with page_size 1 and register the item schema "
                "before evaluating pagination."
            ),
        )
    if _media_reports(selected, words):
        return unavailable_gap(
            query, code="MEDIA_REPORT_ITEM_SCHEMA_MISSING",
            journey="media_report_directory",
            reason="The media-report list read is confirmed, but the bounded observed response was empty.",
            next_action=(
                "Use a tenant with a media report and repeat the same unfiltered first-page request once; "
                "register only shape, types, and pagination evidence."
            ),
        )
    if _monetization_aggregate(selected, words):
        return unavailable_gap(
            query, code="MONETIZATION_AGGREGATE_CONTRACT_MISSING",
            journey="monetization_aggregate",
            reason="Account-to-platform app directories do not contain dated placement-level monetization metrics.",
            next_action=(
                "Recover the exact custom_get and calc_total request/response contracts, then register every "
                "returned field before one bounded aggregate probe."
            ),
        )
    return None


def _report_directory(selected: str, words: frozenset[str]) -> bool:
    english = (
        bool(words & {"report", "reports"}) and "masterkey" in words and "shared" in words
        and bool(words & {"own", "definition", "definitions"})
    )
    chinese = (
        "报表" in selected and "masterkey" in selected and "共享" in selected
        and any(term in selected for term in ("自己的", "自有"))
        and "定义" in selected
    )
    return english or chinese


def _report_subscriptions(selected: str, words: frozenset[str]) -> bool:
    english = bool(words & {"report", "reports"}) and bool(words & {"subscribed", "subscription", "subscriptions"})
    return english or ("报表" in selected and any(term in selected for term in ("订阅了", "订阅清单", "报表订阅")))


def _media_reports(selected: str, words: frozenset[str]) -> bool:
    english = "media" in words and bool(words & {"report", "reports"}) and bool(
        words & {"available", "advertising", "current"}
    )
    chinese = "媒体" in selected and "报表" in selected and any(
        term in selected for term in ("可用", "有哪些", "投放")
    )
    return english or chinese


def _monetization_aggregate(selected: str, words: frozenset[str]) -> bool:
    english = (
        "monetization" in words and bool(words & {"summarize", "aggregate", "daily"})
        and bool(words & {"placement", "placements"})
        and len(words & {"revenue", "impressions", "ecpm"}) >= 2
    )
    chinese = (
        "变现平台" in selected and "广告位" in selected
        and any(term in selected for term in ("汇总", "聚合"))
        and sum(term in selected for term in ("收入", "展示", "ecpm")) >= 2
    )
    return english or chinese


__all__ = ["unavailable_report_gap"]
