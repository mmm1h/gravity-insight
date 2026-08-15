"""Natural-language gaps owned by unavailable report journeys."""

from __future__ import annotations

import re
from typing import Any

from .agent_gap import unavailable_gap
from .agent_intent_text import affirmative_intent_text


def unavailable_report_gap(query: str) -> dict[str, Any] | None:
    selected = affirmative_intent_text(query)
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
        bool(words & {"report", "reports"})
        and bool(words & {"catalog", "definition", "definitions", "directory", "list"})
        and not bool(words & {"subscribed", "subscription", "subscriptions"})
    )
    chinese = (
        "报表" in selected and any(term in selected for term in ("定义", "目录", "清单", "列表"))
        and not any(term in selected for term in ("订阅", "已订阅"))
    )
    return english or chinese


def _report_subscriptions(selected: str, words: frozenset[str]) -> bool:
    english = bool(words & {"subscribed", "subscription", "subscriptions"}) and bool(
        words & {"catalog", "list", "report", "reports"}
    )
    return english or any(term in selected for term in ("订阅清单", "报表订阅")) or (
        "报表" in selected and "订阅" in selected
    )


def _media_reports(selected: str, words: frozenset[str]) -> bool:
    english = "media" in words and bool(words & {"report", "reports"})
    chinese = "媒体" in selected and "报表" in selected
    return english or chinese


def _monetization_aggregate(selected: str, words: frozenset[str]) -> bool:
    english = (
        "monetization" in words
        and bool(words & {"aggregate", "aggregated", "breakdown", "daily", "summarize", "summary"})
    )
    chinese = (
        "变现" in selected and any(term in selected for term in ("汇总", "聚合"))
    )
    return english or chinese


__all__ = ["unavailable_report_gap"]
