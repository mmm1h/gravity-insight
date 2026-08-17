"""Natural-language boundary for the account-readable App catalog."""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping
from typing import Any

from .agent_intent_text import affirmative_intent_text
from .catalog import APP_LIST_OPERATION_ID


APP_CATALOG_SELECTOR = APP_LIST_OPERATION_ID
APP_CATALOG_CAPABILITY: Mapping[str, Any] = {
    "kind": "operation",
    "selector": APP_CATALOG_SELECTOR,
    "operation_id": APP_CATALOG_SELECTOR,
    "domain": "app",
    "description": (
        "读取当前账号可访问的 App 项目目录，返回受合同治理的项目条目；"
        "用于账号可读项目清单，不用于 App 治理快照、普通对象成员管理、"
        "数据表当前 schema 或任意未登记目录。"
    ),
    "effect": "read",
    "executable": True,
    "plan_executable": True,
    "natural_language_auto_execute": False,
    "input_schema": {},
    "required_inputs": (),
    "missing_inputs": [],
    "match": {
        "confidence": "strong",
        "coverage": 1.0,
        "matched_terms": [APP_CATALOG_SELECTOR],
        "missing_terms": [],
        "score": 100,
        "exact_selector": True,
    },
    "next": {
        "ready_without_input": True,
        "argv": ["gravity", "run", APP_CATALOG_SELECTOR],
    },
}


def app_catalog_capability_inventory() -> tuple[dict[str, Any], ...]:
    """Return the canonical product card owned by the existing App router."""

    return (copy.deepcopy(dict(APP_CATALOG_CAPABILITY)),)


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


def app_catalog_capability_cards(
    query: str, *, domain: str | None = None, platform: str | None = None
) -> list[dict[str, Any]]:
    if platform is not None or domain not in {None, "app"}:
        return []
    exact = query.strip().casefold() == APP_CATALOG_SELECTOR
    if not exact and not app_catalog_query(query):
        return []
    return [copy.deepcopy(dict(APP_CATALOG_CAPABILITY))]


def app_catalog_operation_query(query: str) -> str:
    """Return the exact governed operation selector for an App-catalog intent."""

    return APP_CATALOG_SELECTOR if app_catalog_query(query) else query


__all__ = [
    "APP_CATALOG_CAPABILITY",
    "APP_CATALOG_SELECTOR",
    "app_catalog_capability_cards",
    "app_catalog_capability_inventory",
    "app_catalog_operation_query",
    "app_catalog_query",
]
