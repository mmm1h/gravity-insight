"""Natural-language gaps owned by unavailable report journeys."""

from __future__ import annotations

import re
from typing import Any

from .agent_gap import unavailable_gap
from .agent_intent_text import affirmative_intent_text


_MEDIA_REPORT_OWNER_TYPO = re.compile(
    r"煤体(?=\s*(?:(?:类|投放)(?:的)?\s*)?报表)"
)


def unavailable_report_gap(query: str) -> dict[str, Any] | None:
    selected = _normalize_media_report_owner(affirmative_intent_text(query))
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
    return None


def _normalize_media_report_owner(selected: str) -> str:
    """Normalize the observed typo only inside a media-report owner phrase."""

    return _MEDIA_REPORT_OWNER_TYPO.sub("媒体", selected)


def _media_reports(selected: str, words: frozenset[str]) -> bool:
    english = "media" in words and bool(words & {"report", "reports"})
    chinese = "媒体" in selected and "报表" in selected
    return english or chinese


__all__ = ["unavailable_report_gap"]
