"""Natural-language gaps owned by unavailable report journeys."""

from __future__ import annotations

import re
from typing import Any

from .agent_gap import unavailable_gap
from .agent_intent_text import affirmative_intent_text


def unavailable_report_gap(query: str) -> dict[str, Any] | None:
    selected = affirmative_intent_text(query)
    words = frozenset(re.findall(r"[a-z0-9_]+", selected))
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
