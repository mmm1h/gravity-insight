"""Natural-language gaps owned by unavailable Analysis data journeys."""

from __future__ import annotations

import re
from typing import Any

from .agent_gap import unavailable_gap
from .agent_intent_text import affirmative_intent_text


def unavailable_analysis_gap(query: str) -> dict[str, Any] | None:
    selected = affirmative_intent_text(query)
    words = frozenset(re.findall(r"[a-z0-9_]+", selected))
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
        from .agent_export import analysis_export_family_choices

        choices = analysis_export_family_choices()
        gap = unavailable_gap(
            query, code="ANALYSIS_EXPORT_FILE_CONTRACT_MISSING",
            journey="analysis_result_export",
            reason=(
                "Seven governed Analysis export families are currently callable. "
                "This broad request needs exactly one family selection because "
                "their input contracts are not interchangeable; stream-event "
                "export is client-side and has no frontend server request."
            ),
            next_action=(
                "Choose exactly one family_choices item and run its next.argv; "
                "inspect its next.schema_argv before supplying that family's "
                "documented inputs."
            ),
            argv=["gravity", "export", "list-capabilities"],
        )
        gap.update({
            "reason_code": "ANALYSIS_EXPORT_FAMILY_SELECTION_REQUIRED",
            "selection_required": True,
            "candidate_selectors": [choice["selector"] for choice in choices],
            "family_choices": choices,
        })
        return gap
    return None


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
        "analysis" in words or "分析" in selected
        or any(term in selected for term in ("事件", "分群", "用户", "付费", "变现"))
    )
    return english or chinese


__all__ = ["unavailable_analysis_gap"]
