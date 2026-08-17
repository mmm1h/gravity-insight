"""Natural-language gap for a named workspace SQL product that is not configured."""

from __future__ import annotations

import re
from typing import Any

from .agent_gap import unavailable_gap
from .agent_intent_text import affirmative_intent_text


def registered_sql_product_gap(query: str) -> dict[str, Any] | None:
    selected = affirmative_intent_text(query)
    words = frozenset(re.findall(r"[a-z0-9_]+", selected))
    if not (_english_registered_sql(words) or _chinese_registered_sql(selected, words)):
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


def _english_registered_sql(words: frozenset[str]) -> bool:
    return (
        "workspace" in words and "registered" in words
        and "analysis" in words and bool(words & {"run", "execute"})
    ) or (
        bool(words & {"registered", "governed"}) and "sql" in words
        and bool(words & {"analysis", "product", "products", "run", "execute"})
    )


def _chinese_registered_sql(selected: str, words: frozenset[str]) -> bool:
    return (
        "workspace" in words and "登记" in selected and "分析" in selected
        and any(term in selected for term in ("运行", "执行"))
    ) or (
        "登记" in selected and "sql" in words
        and any(term in selected for term in ("分析", "产品", "运行", "执行", "只允许"))
    ) or (
        "登记" in selected
        and any(term in selected for term in ("跨表", "汇总口径", "聚合产品"))
        and any(term in selected for term in ("运行", "执行", "跑出来", "时间窗"))
    )


__all__ = ["registered_sql_product_gap"]
