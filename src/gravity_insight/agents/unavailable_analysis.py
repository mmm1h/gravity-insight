"""Natural-language gaps owned by unavailable Analysis data journeys."""

from __future__ import annotations

import re
from typing import Any

from .gap import unavailable_gap
from .intent_text import affirmative_intent_text


_CURRENT_SCHEMA_ENGLISH = re.compile(
    r"\b(?:current|latest|present)\s+(?:(?:data\s+)?table\s+)?schema\b"
)
_CURRENT_SCHEMA_CHINESE = re.compile(
    r"(?:当前|此刻|现在|现时)(?:的|实时)?\s*(?:数据)?表?\s*schema\b"
)
_ENGLISH_CURRENT_STATE = frozenset({"current", "latest", "present"})
_ENGLISH_FIELD_TERMS = frozenset({"field", "fields"})
_ENGLISH_TABLE_CONTEXT = frozenset({"table", "parent"})
_CHINESE_CURRENT_STATE = ("当前", "此刻", "现在", "现时")
_CHINESE_TABLE_CONTEXT = re.compile(r"(?<!报)表|table\b")
_SEGMENT_EVENT_RULE_GAP_CODE = "SEGMENT_EVENT_RULE_ACCEPTANCE_UNPROVEN"
_SEGMENT_EVENT_RULE_GAP_REASON = (
    "Event and ordinary Retention accepted the two consumer-observed, "
    "metadata-valid custom events, while Segment evaluation rejected their "
    "locally valid did=true, PresetAllCount/GTE 1, static-window rules. Issue "
    "#15 separately proves only $MPShow and $PayEvent unsupported and records "
    "one accepted metadata-backed custom control. The repository proves neither "
    "an all-custom-event exclusion nor a locally predictable accepted subset."
)
_SEGMENT_FIRST_EXPOSURE_GAP_NEXT_ACTION = (
    "Do not substitute ordinary event-date Retention. Close this gap only with a "
    "sanitized current-main paired Segment receipt using the same positive and "
    "negative static-window shape: one metadata-valid custom event accepted and "
    "the target event rejected, plus metadata kind, HTTP status, and sanitized "
    "extra.error. Until then an aggregate-only first-exposure cohort requires an "
    "existing set-once first-occurrence property; without one the read-only "
    "surfaces cannot compute the required NOT-before intersection."
)


def unavailable_analysis_gap(query: str) -> dict[str, Any] | None:
    selected = affirmative_intent_text(query)
    words = frozenset(re.findall(r"[a-z0-9_]+", selected))
    if _custom_event_first_exposure(selected, words):
        return unavailable_gap(
            query,
            code=_SEGMENT_EVENT_RULE_GAP_CODE,
            journey="segment_custom_event_first_exposure",
            reason=_SEGMENT_EVENT_RULE_GAP_REASON,
            next_action=_SEGMENT_FIRST_EXPOSURE_GAP_NEXT_ACTION,
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
        from .export import analysis_export_family_choices

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


def _custom_event_first_exposure(
    selected: str, words: frozenset[str]
) -> bool:
    english = (
        {"custom", "event"} <= words
        and bool(words & {"cohort", "segment"})
        and (
            {"first", "exposure"} <= words
            or {"first", "occurrence"} <= words
            or "never before" in selected
        )
    )
    chinese = (
        "自定义事件" in selected
        and any(term in selected for term in ("首次暴露", "首次发生", "此前没发生", "之前没发生"))
        and any(term in selected for term in ("cohort", "分群", "人群", "留存"))
    )
    return english or chinese


def _current_table_schema(selected: str, words: frozenset[str]) -> bool:
    return (
        _explicit_current_schema(selected)
        or _english_current_fields_and_version(words)
        or _chinese_current_fields_and_version(selected)
    )


def _explicit_current_schema(selected: str) -> bool:
    """Treat schema as table-scoped only when current-state words are adjacent."""

    return bool(
        _CURRENT_SCHEMA_ENGLISH.search(selected)
        or _CURRENT_SCHEMA_CHINESE.search(selected)
    )


def _english_current_fields_and_version(words: frozenset[str]) -> bool:
    return (
        bool(words & _ENGLISH_CURRENT_STATE)
        and bool(words & _ENGLISH_FIELD_TERMS)
        and "version" in words
        and bool(words & _ENGLISH_TABLE_CONTEXT)
    )


def _chinese_current_fields_and_version(selected: str) -> bool:
    return (
        any(term in selected for term in _CHINESE_CURRENT_STATE)
        and "字段" in selected
        and "版本" in selected
        and _CHINESE_TABLE_CONTEXT.search(selected) is not None
        and "项目" not in selected
    )


def _analysis_export(selected: str, words: frozenset[str]) -> bool:
    from .export import analysis_export_is_specific

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
