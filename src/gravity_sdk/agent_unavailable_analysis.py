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
    if _single_user_attribution(selected, words):
        return unavailable_gap(
            query, code="USER_ATTRIBUTION_DETAIL_DEPENDENCY_MISSING",
            journey="single_user_attribution_detail",
            reason=(
                "The request needs a caller-selected registered testing-device row id, and "
                "the detail response item fields and types lack successful or explicit-empty evidence."
            ),
            next_action=(
                "Have the caller authorize one real testing-device row id, then send one detail "
                "request and register every observed attribution, device, postback, and pay field."
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
                "User-event export is callable, but the other six server-generated "
                "analysis export families still lack their own successful file shape; "
                "stream-event export is client-side and has no frontend server request."
            ),
            next_action=(
                "For user-event results, select export.analysis.user_event.start. For any "
                "other exact family, obtain one authorized successful non-empty file and "
                "register its worksheet, headers, storage types, logical types, and request binding."
            ),
            argv=["gravity", "export", "list-capabilities"],
        )
    return None


def _realtime_event_catalog(selected: str, words: frozenset[str]) -> bool:
    english = (
        "event" in words and "catalog" in words
        and "real" in words and "time" in words
    )
    return english or "实时事件目录" in selected


def _single_user_attribution(selected: str, words: frozenset[str]) -> bool:
    english = (
        "attribution" in words and bool(words & {"user", "users"})
        and bool(words & {"detail", "details", "drill", "source"})
    )
    chinese = "用户" in selected and "归因" in selected and any(
        term in selected for term in ("明细", "来源", "下钻")
    )
    return english or chinese


def _current_table_schema(selected: str, words: frozenset[str]) -> bool:
    english = (
        "current" in words and "schema" in words
        and bool(words & {"field", "fields", "table", "version"})
    )
    chinese = "当前" in selected and "schema" in selected
    return english or chinese


def _analysis_export(selected: str, words: frozenset[str]) -> bool:
    if re.search(r"(?<![a-z0-9_])export\.analysis\.", selected):
        return False
    if _specific_user_event_export(selected):
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


def _specific_user_event_export(selected: str) -> bool:
    english = bool(re.search(
        r"\b(?:export\s+(?:user\s+events?|event\s+timeline)|"
        r"(?:user\s+events?|event\s+timeline)\s+export)\b",
        selected,
    ))
    chinese = any(term in selected for term in (
        "导出用户事件", "用户事件导出", "导出事件时间线", "事件时间线导出"
    ))
    return english or chinese


__all__ = ["unavailable_analysis_gap"]
