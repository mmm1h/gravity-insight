"""Natural-language boundary for the account-readable App catalog."""

from __future__ import annotations

import re

from .agent_intent_text import affirmative_intent_text
from .catalog import APP_LIST_OPERATION_ID


APP_CATALOG_SELECTOR = APP_LIST_OPERATION_ID


def app_catalog_query(query: str) -> bool:
    """Identify App-project catalog requests without matching member journeys."""

    selected = affirmative_intent_text(query)
    words = frozenset(re.findall(r"[a-z0-9_]+", selected))
    english = (
        bool(words & {"project", "projects"})
        and bool(
            words
            & {
                "account",
                "allowed",
                "app",
                "catalog",
                "directory",
                "list",
                "read",
                "readable",
            }
        )
    )
    chinese = "项目" in selected and any(
        term in selected
        for term in ("app", "当前账号", "可读", "可以读取", "读取", "清单", "列表")
    )
    return english or chinese


def app_catalog_operation_query(query: str) -> str:
    """Return the exact governed operation selector for an App-catalog intent."""

    return APP_CATALOG_SELECTOR if app_catalog_query(query) else query


__all__ = ["APP_CATALOG_SELECTOR", "app_catalog_operation_query", "app_catalog_query"]
