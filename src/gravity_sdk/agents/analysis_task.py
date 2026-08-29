"""Offline Agent handoff for underspecified Analysis tasks.

The helpers in this module deliberately stop before compilation.  They expose
the decisions an Agent still has to make and rank only identities supplied by
an already-synchronized metadata snapshot.  Natural language never becomes an
event name, property, metric, App, time range, or executable Analysis spec.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import re
from typing import Any


ANALYSIS_TASK_SELECTOR = "analysis.task.handoff"
ANALYSIS_TASK_KIND = "analysis_task"
ANALYSIS_QUERY_COMPOSITE = "analysis_query"
ANALYSIS_SPEC_VERSION = "gravity-insight.analysis-query-spec.v1"
DEFAULT_CANDIDATE_LIMIT = 5

_PLAN_SPEC_PLACEHOLDER = f"<explicit-{ANALYSIS_SPEC_VERSION}-object>"
_WORD = re.compile(r"[a-z0-9_]+", re.IGNORECASE)
_NON_WORD = re.compile(r"[^a-z0-9\u3400-\u9fff]+", re.IGNORECASE)

_ENGLISH_ANALYSIS_TERMS = frozenset(
    {
        "analysis",
        "analytics",
        "analyze",
        "analyse",
        "trend",
        "trends",
        "funnel",
        "funnels",
        "retention",
    }
)
_ENGLISH_QUANTITATIVE_TERMS = frozenset(
    {
        "count",
        "counts",
        "number",
        "numbers",
        "ratio",
        "ratios",
        "rate",
        "rates",
        "percent",
        "percentage",
        "total",
        "conversion",
    }
)
_ENGLISH_GENERIC_TERMS = frozenset(
    {
        "a",
        "an",
        "and",
        "by",
        "for",
        "from",
        "in",
        "last",
        "of",
        "over",
        "past",
        "per",
        "the",
        "this",
        "to",
        "week",
        "weeks",
        "day",
        "days",
        "month",
        "months",
        *_ENGLISH_ANALYSIS_TERMS,
        *_ENGLISH_QUANTITATIVE_TERMS,
    }
)
_CHINESE_ANALYSIS_TERMS = ("分析", "趋势", "漏斗", "留存")
_CHINESE_QUANTITATIVE_TERMS = (
    "转化率",
    "用户数",
    "人数",
    "数量",
    "次数",
    "占比",
    "比例",
)
_CHINESE_GENERIC_TERMS = (
    "查询",
    "查看",
    "多少",
    "过去",
    "最近",
    "近几天",
    "今天",
    "昨天",
    "本周",
    "本月",
    "每日",
    "每周",
    "每月",
)

_EXPORT_TERMS = ("export", "导出")
_SAVED_TERMS_EN = frozenset({"saved"})
_SAVED_TERMS_ZH = ("保存", "已存")
_JOURNEY_TERMS_EN = frozenset({"journey", "path"})
_JOURNEY_TERMS_ZH = ("旅程", "路径")
_SEGMENT_SUBJECTS_EN = frozenset({"segment", "audience", "cohort"})
_SEGMENT_RULES_EN = frozenset({"rule", "rules", "condition", "conditions"})
_SEGMENT_PRODUCTS_EN = frozenset(
    {"detail", "details", "history", "member", "members", "membership"}
)
_SEGMENT_ACTIONS_EN = frozenset(
    {
        "evaluate",
        "evaluation",
        "estimate",
        "estimation",
        "predict",
        "prediction",
        "count",
        "population",
        "percent",
        "percentage",
        "ratio",
    }
)
_SEGMENT_SUBJECTS_ZH = ("人群", "受众", "分群")
_SEGMENT_RULES_ZH = ("规则", "条件")
_SEGMENT_PRODUCTS_ZH = ("成员", "历史", "详情", "明细", "画像")
_SEGMENT_ACTIONS_ZH = (
    "评估",
    "预估",
    "估算",
    "测算",
    "人数",
    "规模",
    "占比",
    "比例",
    "命中",
)

_METADATA_GROUPS: Mapping[str, str] = {
    "event": "events",
    "property": "properties",
    "user_property": "properties",
    "event_property": "properties",
    "event_property_group": "properties",
    "metric": "metrics",
    "custom_metric": "metrics",
}
_MATCH_STOPWORDS = frozenset(
    {
        *_ENGLISH_GENERIC_TERMS,
        "app",
        "data",
        "event",
        "events",
        "metric",
        "metrics",
        "property",
        "properties",
        "query",
        "report",
        "show",
        "user",
        "users",
    }
)


def analysis_task_cards(
    query: str,
    *,
    metadata_rows: Sequence[Mapping[str, Any]] | None,
    domain: str | None = None,
    platform: str | None = None,
    candidate_limit: int = DEFAULT_CANDIDATE_LIMIT,
) -> list[dict[str, Any]]:
    """Return one non-executing handoff for an explicit Analysis task.

    ``metadata_rows=None`` means that no synchronized catalog is available.
    An empty sequence means that the catalog exists but contains no relevant
    rows.  This distinction lets callers give one deterministic sync action
    without treating a legitimate empty search as an infrastructure failure.
    """

    if platform is not None or domain not in {None, "analysis"}:
        return []
    if not is_analysis_task_query(query):
        return []
    candidates = analysis_metadata_candidates(
        query,
        metadata_rows or (),
        limit=candidate_limit,
    )
    return [
        _analysis_task_card(
            query,
            candidates,
            catalog_missing=metadata_rows is None,
        )
    ]


def is_analysis_task_query(query: str) -> bool:
    """Recognize analysis-task language while yielding to stronger products."""

    selected = _normalized_text(query)
    if not selected or _is_excluded_product_intent(selected):
        return False
    words = frozenset(_WORD.findall(selected))
    if words & _ENGLISH_ANALYSIS_TERMS:
        return True
    if any(term in selected for term in _CHINESE_ANALYSIS_TERMS):
        return True
    if words & _ENGLISH_QUANTITATIVE_TERMS:
        return bool(words - _ENGLISH_GENERIC_TERMS)
    return _has_chinese_quantitative_subject(selected)


def analysis_metadata_candidates(
    query: str,
    metadata_rows: Sequence[Mapping[str, Any]],
    *,
    limit: int = DEFAULT_CANDIDATE_LIMIT,
) -> dict[str, list[dict[str, Any]]]:
    """Rank safe event/property/metric identities from caller-owned rows only."""

    if type(limit) is not int or not 1 <= limit <= 20:
        raise ValueError("analysis metadata candidate limit must be between 1 and 20")
    if isinstance(metadata_rows, (str, bytes, bytearray)):
        raise TypeError("analysis metadata rows must be a sequence of mappings")
    grouped: dict[str, list[dict[str, Any]]] = {
        "events": [],
        "properties": [],
        "metrics": [],
    }
    for row in metadata_rows:
        candidate = _metadata_candidate(query, row)
        if candidate is None:
            continue
        grouped[str(candidate.pop("_group"))].append(candidate)
    for group in grouped:
        grouped[group] = sorted(grouped[group], key=_candidate_sort_key)[:limit]
    return grouped


def _analysis_task_card(
    query: str,
    candidates: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    catalog_missing: bool,
) -> dict[str, Any]:
    candidate_count = sum(len(items) for items in candidates.values())
    card: dict[str, Any] = {
        "kind": ANALYSIS_TASK_KIND,
        "selector": ANALYSIS_TASK_SELECTOR,
        "domain": "analysis",
        "description": (
            "把明确但尚未结构化的分析任务交给调用 Agent 补齐；"
            "只展示本地目录候选，不从自然语言生成或选择业务字段。"
        ),
        "effect": "read",
        "executable": False,
        "compiler_callable": False,
        "plan_executable": False,
        "natural_language_auto_execute": False,
        "execution_mode": "explicit_decisions_then_analysis_query_plan",
        "offline": True,
        "network_called": False,
        "required_inputs": ["app", "kind", "time", "steps_or_metrics"],
        "missing_inputs": ["app", "kind", "time", "steps_or_metrics"],
        "missing_decisions": ["app", "kind", "time", "steps|metrics"],
        "input_template": _input_template(),
        "kind_candidates": _kind_candidates(query),
        "decision_schema": _decision_schema(),
        "metadata_candidates": {
            name: [dict(item) for item in items]
            for name, items in candidates.items()
        },
        "catalog_missing": catalog_missing,
        "catalog": {
            "status": "missing" if catalog_missing else "available",
            "candidate_count": candidate_count,
            "source": "caller_supplied_local_metadata",
        },
        "plan_node": None,
        "plan_template": _plan_template(),
        "match": {
            "confidence": "strong",
            "coverage": 1.0,
            "matched_terms": ["analysis task"],
            "missing_terms": [],
            "score": 100,
            "exact_selector": query.strip().casefold() == ANALYSIS_TASK_SELECTOR,
            "intent_only": query.strip().casefold() != ANALYSIS_TASK_SELECTOR,
        },
        "next": {
            "ready_without_input": False,
            "argv": ["gravity", "plan", "run", "--input", "<plan.json>"],
            "schema_argv": [
                "gravity",
                "analysis",
                "query",
                "--kind",
                "<explicit-kind>",
                "--spec-schema",
            ],
            "call_count_after_decisions": 1,
        },
    }
    if catalog_missing:
        sync = ["gravity", "metadata", "sync", "--all-apps"]
        card["catalog_sync_argv"] = sync
        card["catalog"]["next"] = {"argv": sync}
    return card


def _decision_schema() -> dict[str, Any]:
    return {
        "app": {
            "type": "string|integer",
            "description": "workspace App alias or positive id",
        },
        "kind": {
            "type": "string",
            "enum": ["event", "funnel", "retention", "property", "scatter"],
            "selection": "caller_explicit",
        },
        "time": {
            "type": "object",
            "required": ["start", "end"],
            "selection": "caller_explicit",
        },
        "steps_or_metrics": {
            "type": "object",
            "selection": "caller_explicit_from_local_metadata_or_project_knowledge",
        },
    }


def _input_template() -> dict[str, Any]:
    return {
        "app": "<explicit-workspace-app-alias-or-positive-id>",
        "kind": "<explicit-event|funnel|retention|property|scatter>",
        "time": {
            "start": "<explicit-inclusive-date>",
            "end": "<explicit-inclusive-date>",
        },
        "steps_or_metrics": "<explicit-selection-from-local-metadata-or-project-knowledge>",
    }


def _plan_template() -> dict[str, Any]:
    return {
        "id": "analysis_query",
        "kind": "composite",
        "request": {
            "name": ANALYSIS_QUERY_COMPOSITE,
            "kind": "<explicit-kind>",
            "app": "<explicit-workspace-app-alias-or-positive-id>",
            "spec": _PLAN_SPEC_PLACEHOLDER,
        },
    }


def _kind_candidates(query: str) -> list[str]:
    selected = _normalized_text(query)
    words = frozenset(_WORD.findall(selected))
    if "funnel" in words or "funnels" in words or "漏斗" in selected:
        return ["funnel"]
    if "retention" in words or "留存" in selected:
        return ["retention"]
    if "trend" in words or "trends" in words or "趋势" in selected:
        return ["event", "property"]
    if "conversion" in words or "转化率" in selected:
        return ["funnel", "event"]
    return ["event", "funnel", "retention", "property", "scatter"]


def _metadata_candidate(
    query: str, row: Mapping[str, Any]
) -> dict[str, Any] | None:
    if not isinstance(row, Mapping):
        return None
    metadata_kind = str(row.get("kind", ""))
    group = _METADATA_GROUPS.get(metadata_kind)
    if group is None:
        return None
    name = _safe_identity(row.get("name"))
    display_name = _safe_identity(row.get("cname"))
    if name is None and display_name is None:
        return None
    score = _candidate_score(query, tuple(value for value in (name, display_name) if value))
    if score <= 0:
        return None
    selected: dict[str, Any] = {
        "_group": group,
        "metadata_kind": metadata_kind,
        "name": name,
        "display_name": display_name,
        "operation_id": _safe_identity(row.get("operation_id")),
        "match_score": score,
        "selected": False,
    }
    for field in ("app_id", "scope", "source"):
        value = _safe_identity(row.get(field))
        if value is not None:
            selected[field] = value
    return selected


def _candidate_score(query: str, values: Sequence[str]) -> int:
    normalized_query = _normalized_text(query)
    compact_query = _compact_text(normalized_query)
    query_words = _meaningful_words(normalized_query)
    best = 0
    for value in values:
        normalized_value = _normalized_text(value)
        compact_value = _compact_text(normalized_value)
        if compact_value and compact_value in compact_query:
            best = max(best, 100)
            continue
        if compact_query and compact_query in compact_value:
            best = max(best, 90)
            continue
        overlap = query_words & _meaningful_words(normalized_value)
        if overlap:
            best = max(best, 70 + min(20, len(overlap) * 5))
            continue
        chinese_overlap = _chinese_bigrams(compact_query) & _chinese_bigrams(compact_value)
        if chinese_overlap:
            best = max(best, 40 + min(20, len(chinese_overlap) * 5))
    return best


def _candidate_sort_key(item: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        -int(item.get("match_score", 0)),
        str(item.get("metadata_kind", "")),
        str(item.get("app_id", "")),
        str(item.get("name") or item.get("display_name") or "").casefold(),
        str(item.get("operation_id", "")),
    )


def _is_excluded_product_intent(selected: str) -> bool:
    if any(term in selected for term in _EXPORT_TERMS):
        return True
    words = frozenset(_WORD.findall(selected))
    if words & _SAVED_TERMS_EN or any(term in selected for term in _SAVED_TERMS_ZH):
        return True
    if words & _JOURNEY_TERMS_EN or any(term in selected for term in _JOURNEY_TERMS_ZH):
        return True
    return _is_explicit_segment_rule_intent(selected)


def _is_explicit_segment_rule_intent(selected: str) -> bool:
    words = frozenset(_WORD.findall(selected))
    return _is_english_segment_product(words) or _is_chinese_segment_product(selected)


def _is_english_segment_product(words: frozenset[str]) -> bool:
    subjects = words & _SEGMENT_SUBJECTS_EN
    if not subjects:
        return False
    if subjects & {"segment", "audience"}:
        product_signals = (
            _SEGMENT_PRODUCTS_EN
            | _SEGMENT_RULES_EN
            | _SEGMENT_ACTIONS_EN
            | _ENGLISH_ANALYSIS_TERMS
        )
        return bool(words & product_signals)
    return bool(words & _SEGMENT_RULES_EN and words & _SEGMENT_ACTIONS_EN)


def _is_chinese_segment_product(selected: str) -> bool:
    if not any(term in selected for term in _SEGMENT_SUBJECTS_ZH):
        return False
    product_signals = (
        *_SEGMENT_PRODUCTS_ZH,
        *_SEGMENT_RULES_ZH,
        *_SEGMENT_ACTIONS_ZH,
    )
    return "分群" in selected or any(term in selected for term in product_signals)


def _has_chinese_quantitative_subject(selected: str) -> bool:
    matched = [term for term in _CHINESE_QUANTITATIVE_TERMS if term in selected]
    if not matched:
        return False
    remainder = selected
    for term in (*matched, *_CHINESE_GENERIC_TERMS):
        remainder = remainder.replace(term, "")
    remainder = re.sub(r"[0-9年月日周天个的和与及]+", "", remainder)
    return bool(remainder) or "转化率" in matched


def _meaningful_words(value: str) -> frozenset[str]:
    return frozenset(
        word
        for word in _WORD.findall(value.replace("_", " "))
        if len(word) >= 2 and word not in _MATCH_STOPWORDS
    )


def _chinese_bigrams(value: str) -> frozenset[str]:
    characters = "".join(
        character for character in value if "\u3400" <= character <= "\u9fff"
    )
    return frozenset(
        characters[index : index + 2]
        for index in range(max(0, len(characters) - 1))
    )


def _safe_identity(value: Any) -> str | None:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    selected = str(value).strip()
    return selected or None


def _normalized_text(value: Any) -> str:
    return " ".join(_NON_WORD.sub(" ", str(value).strip().casefold()).split())


def _compact_text(value: str) -> str:
    return "".join(value.replace("_", "").split())


__all__ = [
    "ANALYSIS_TASK_KIND",
    "ANALYSIS_TASK_SELECTOR",
    "analysis_metadata_candidates",
    "analysis_task_cards",
    "is_analysis_task_query",
]
