"""Natural-language gaps owned by unavailable Analysis data journeys."""

from __future__ import annotations

import re
from typing import Any

from .agent_gap import unavailable_gap
from .agent_intent_text import affirmative_intent_text


def unavailable_analysis_gap(query: str) -> dict[str, Any] | None:
    selected = affirmative_intent_text(query)
    words = frozenset(re.findall(r"[a-z0-9_]+", selected))
    if _realtime_event_catalog(selected, words):
        return unavailable_gap(
            query, code="REALTIME_EVENT_CATALOG_CONTRACT_MISSING",
            journey="realtime_event_catalog",
            reason="The real-time event request is known, but item schema and server pagination are unproven.",
            next_action=(
                "Use a tenant with a non-empty catalog for one bounded first-page shape probe; "
                "record item paths, types, and pagination without response values."
            ),
        )
    if _current_table_schema(selected, words):
        return unavailable_gap(
            query, code="CURRENT_TABLE_SCHEMA_PARENT_MISSING",
            journey="current_table_schema",
            reason="No trustworthy table name or App parent is available for current-schema detail/version lookup.",
            next_action=(
                "Run a complete table-lineage sync, select one observed table_id without inferring its name, "
                "then verify the detail/version parent chain and current-version semantics."
            ),
            argv=["gravity", "metadata", "sync", "--all-apps", "--include-table-lineage"],
        )
    if _analysis_export(selected, words):
        return unavailable_gap(
            query, code="ANALYSIS_EXPORT_FILE_CONTRACT_MISSING",
            journey="analysis_result_export",
            reason=(
                "Seven Analysis export families are callable: user-event, "
                "segment-result, segment-user-detail, user-detail, pay-event, "
                "monetization-detail and origin-event. They take seven "
                "non-interchangeable input contracts, so a single broad request "
                "cannot be resolved to one of them; stream-event export is "
                "client-side and has no frontend server request."
            ),
            next_action=(
                "Run `gravity export list-capabilities` to see the seven callable "
                "Analysis families and their required inputs, then re-run the "
                "discovery naming the family you want."
            ),
            argv=["gravity", "export", "list-capabilities"],
        )
    return None


def _realtime_event_catalog(selected: str, words: frozenset[str]) -> bool:
    english = (
        "event" in words and "catalog" in words
        and "real" in words and "time" in words
    )
    return english or "实时事件目录" in selected or (
        "实时" in selected
        and any(term in selected for term in ("上报", "目录"))
        and any(term in selected for term in ("目录", "项", "治理"))
    )


def _current_table_schema(selected: str, words: frozenset[str]) -> bool:
    english = (
        "current" in words and "schema" in words
        and bool(words & {"field", "fields", "table", "version"})
    )
    chinese = (
        "当前" in selected
        and any(term in selected for term in ("schema", "字段", "版本"))
        and any(term in selected for term in ("表", "table"))
        and "项目" not in selected
    )
    return english or chinese


def _analysis_export(selected: str, words: frozenset[str]) -> bool:
    from .agent_export import analysis_export_is_specific

    if re.search(r"(?<![a-z0-9_])export\.analysis\.", selected):
        return False
    if analysis_export_is_specific(selected):
        return False
    analysis_families = {
        "event", "funnel", "path", "property", "retention", "scatter", "segment", "user",
    }
    english = (
        "export" in words and bool(words & {"result", "results"})
        and ("analysis" in words or len(words & analysis_families) >= 2)
    )
    chinese = "导出" in selected and "结果" in selected and (
        "analysis" in words
        or any(term in selected for term in ("事件", "分群", "用户", "付费", "变现"))
    )
    return english or chinese


__all__ = ["unavailable_analysis_gap"]
