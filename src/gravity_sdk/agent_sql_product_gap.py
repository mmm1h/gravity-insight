"""Natural-language gap for a named workspace SQL product that is not configured."""

from __future__ import annotations

import re
from typing import Any

from .agent_gap import unavailable_gap


def registered_sql_product_gap(query: str) -> dict[str, Any] | None:
    selected = " ".join(query.strip().casefold().split())
    words = frozenset(re.findall(r"[a-z0-9_]+", selected))
    english = (
        "workspace" in words and "registered" in words
        and "analysis" in words and bool(words & {"run", "execute"})
    )
    chinese = (
        "workspace" in words and "登记" in selected and "分析" in selected
        and any(term in selected for term in ("运行", "执行"))
    )
    if not (english or chinese):
        return None
    return unavailable_gap(
        query, code="WORKSPACE_SQL_PRODUCT_NOT_CONFIGURED",
        journey="workspace_sql_product",
        reason="No configured SQL product matches the requested human name in the selected workspace.",
        next_action=(
            "List the selected workspace products; if absent, add a governed [products.<name>] "
            "contract, then ask again using that exact human product name."
        ),
        argv=["gravity", "sql", "products"],
    )


__all__ = ["registered_sql_product_gap"]
