"""Natural-language gaps owned by unavailable Analysis data journeys."""

from __future__ import annotations

import re
from typing import Any

from .agent_gap import unavailable_gap
from .agent_intent_text import affirmative_intent_text


def unavailable_analysis_gap(query: str) -> dict[str, Any] | None:
    selected = affirmative_intent_text(query)
    words = frozenset(re.findall(r"[a-z0-9_]+", selected))
    if _analysis_defaults(selected, words):
        return unavailable_gap(
            query, code="ANALYSIS_DEFAULT_DICTIONARY_CONTRACT_MISSING",
            journey="analysis_default_dictionary",
            reason="The dynamic default-dictionary item keys lack a non-empty registered contract.",
            next_action=(
                "Capture one authorized non-empty shape-only response, register every "
                "observed key and type with synthetic fixtures, then run compiler and quality checks."
            ),
        )
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
            reason="Single-user attribution detail depends on the still-unclosed attribution aggregate contract.",
            next_action=(
                "Close the attribution aggregate request and response contract first, then use one "
                "caller-supplied authorized user identifier for a bounded shape-only detail probe."
            ),
        )
    if _attribution_aggregate(selected, words):
        return unavailable_gap(
            query, code="ATTRIBUTION_AGGREGATE_CONTRACT_MISSING",
            journey="attribution_aggregate",
            reason="The recovered attribution body still fails semantically; required fields and value domains are unknown.",
            next_action=(
                "Obtain the server-required field list and valid value domains from the upstream owner, "
                "then run one minimal bounded aggregate probe."
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
            reason="All nine analysis export creators still lack a complete successful request/file contract.",
            next_action=(
                "Choose the exact export family, obtain one authorized successful non-empty file, "
                "and register worksheet, header, logical type, and request-binding evidence without values."
            ),
            argv=["gravity", "export", "list-capabilities"],
        )
    return None


def _analysis_defaults(selected: str, words: frozenset[str]) -> bool:
    return (
        {"default", "dictionary"} <= words
        and bool(words & {"analysis", "value", "values"})
    ) or ("默认值" in selected and "字典" in selected)


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


def _attribution_aggregate(selected: str, words: frozenset[str]) -> bool:
    configuration = {
        "configuration", "configured", "lookback", "mapping", "mappings",
        "rule", "rules", "setting", "settings", "window",
    }
    english = (
        bool(words & {"attribution", "attributed"})
        and bool(words & {"aggregate", "aggregated", "performance", "summary"})
        and not bool(words & configuration)
    )
    chinese = "归因" in selected and any(
        term in selected for term in ("汇总", "表现", "聚合")
    ) and not any(term in selected for term in ("配置", "规则", "映射", "回溯", "设置", "窗口"))
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
