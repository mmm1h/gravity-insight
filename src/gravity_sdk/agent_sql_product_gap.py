"""Natural-language gap for a named workspace SQL product that is not configured."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence
from typing import Any

from .agent_gap import unavailable_gap
from .agent_intent_text import affirmative_intent_text


_ASCII_NAME_TERM = re.compile(r"[a-z0-9]+", re.IGNORECASE)


def registered_sql_product_gap(query: str) -> dict[str, Any] | None:
    if not registered_sql_product_intent(query):
        return None
    return unavailable_gap(
        query, code="WORKSPACE_SQL_PRODUCT_NOT_CONFIGURED",
        journey="workspace_sql_product",
        reason=(
            "The goal is to run a team-reviewed cross-table aggregate by its "
            "registered workspace product name and caller date window, but no "
            "configured SQL product matches that human name. This never accepts "
            "ad-hoc SQL text or substitutes an Insight/Analysis product."
        ),
        next_action=(
            "List the selected workspace products; if absent, add a governed [products.<name>] "
            "contract, then ask again using that exact human product name."
        ),
        argv=["gravity", "sql", "products"],
    )


def registered_sql_product_intent(query: str) -> bool:
    """Recognize a governed product request without inferring product names."""

    selected = affirmative_intent_text(query)
    if not selected:
        return False
    words = frozenset(re.findall(r"[a-z0-9_]+", selected))
    return (
        _english_registered_sql(words)
        or _english_indirect_registered_sql(words)
        or _chinese_registered_sql(selected, words)
        or _chinese_indirect_registered_sql(selected)
    )


def registered_sql_product_names(
    query: str, inventory: Sequence[Mapping[str, Any]]
) -> tuple[str, ...]:
    """Return only catalog names stated verbatim, allowing registered separators."""

    selected = affirmative_intent_text(query)
    query_terms = tuple(_ASCII_NAME_TERM.findall(
        unicodedata.normalize("NFKC", selected).casefold()
    ))
    matched: list[str] = []
    for product in inventory:
        name = str(product.get("name", ""))
        name_terms = tuple(_ASCII_NAME_TERM.findall(name.casefold()))
        if name_terms and _contains_term_sequence(query_terms, name_terms):
            matched.append(name)
    return tuple(dict.fromkeys(matched))


def _english_registered_sql(words: frozenset[str]) -> bool:
    return (
        "workspace" in words and "registered" in words
        and "analysis" in words and bool(words & {"run", "execute"})
    ) or (
        bool(words & {"registered", "governed"}) and "sql" in words
        and bool(words & {"analysis", "product", "products", "run", "execute"})
    )


def _english_indirect_registered_sql(words: frozenset[str]) -> bool:
    return (
        {"cross", "table", "name"}.issubset(words)
        and bool(words & {"reviewed", "approved", "registered", "governed"})
        and bool(words & {"aggregate", "aggregation", "rollup", "summary"})
        and bool(words & {"window", "range"})
        and bool(words & {"run", "execute", "result", "results"})
    )


def _chinese_registered_sql(selected: str, words: frozenset[str]) -> bool:
    return (
        "workspace" in words and "登记" in selected
        and any(term in selected for term in ("分析", "聚合", "产品"))
        and any(term in selected for term in ("运行", "执行"))
    ) or (
        "登记" in selected and "sql" in words
        and any(term in selected for term in ("分析", "产品", "运行", "执行", "只允许"))
    )


def _chinese_indirect_registered_sql(selected: str) -> bool:
    return (
        any(term in selected for term in (
            "已审过", "已审核", "已审查", "审核过", "团队审过", "已登记",
        ))
        and "跨表" in selected
        and any(term in selected for term in ("汇总", "聚合", "口径"))
        and any(term in selected for term in (
            "登记名称", "登记名", "产品名称", "产品名",
        ))
        and any(term in selected for term in (
            "时间窗", "日期窗", "时间范围", "日期范围",
        ))
        and any(term in selected for term in (
            "运行", "执行", "跑出", "出结果", "取结果",
        ))
    )


def _contains_term_sequence(
    query_terms: tuple[str, ...], name_terms: tuple[str, ...]
) -> bool:
    width = len(name_terms)
    return any(
        query_terms[start:start + width] == name_terms
        for start in range(len(query_terms) - width + 1)
    )


__all__ = [
    "registered_sql_product_gap",
    "registered_sql_product_intent",
    "registered_sql_product_names",
]
