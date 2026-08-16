"""Strict Agent metadata for report-directory reads."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from .agent_intent_text import affirmative_intent_text


REPORT_DIRECTORY_NAME = "report_directory"
REPORT_SUBSCRIPTIONS_NAME = "report_subscriptions"

REPORT_DIRECTORY_CAPABILITY: Mapping[str, Any] = {
    "name": REPORT_DIRECTORY_NAME,
    "domain": "report",
    "aliases": ("report directory", "report definitions", "报表目录", "报表定义"),
    "description": "读取账号自有报表目录，并按内存中的精确 ID 下钻完整定义。",
    "required_inputs": (),
    "input_schema": {},
}

REPORT_SUBSCRIPTIONS_CAPABILITY: Mapping[str, Any] = {
    "name": REPORT_SUBSCRIPTIONS_NAME,
    "domain": "report",
    "aliases": ("report subscriptions", "subscription list", "报表订阅", "订阅清单"),
    "description": "读取账号级报表订阅清单。",
    "required_inputs": (),
    "input_schema": {},
}


def report_directory_query(query: str) -> bool:
    selected = affirmative_intent_text(query)
    if selected in {REPORT_DIRECTORY_NAME, f"composite:{REPORT_DIRECTORY_NAME}"}:
        return True
    words = frozenset(re.findall(r"[a-z0-9_]+", selected))
    english = bool(words & {"report", "reports"}) and bool(
        words & {"catalog", "definition", "definitions", "directory", "list"}
    ) and not bool(words & {"subscription", "subscriptions", "subscribed"})
    return english or (
        "报表" in selected and any(term in selected for term in ("定义", "目录", "清单", "列表"))
        and "订阅" not in selected
    )


def report_subscriptions_query(query: str) -> bool:
    selected = affirmative_intent_text(query)
    if selected in {REPORT_SUBSCRIPTIONS_NAME, f"composite:{REPORT_SUBSCRIPTIONS_NAME}"}:
        return True
    words = frozenset(re.findall(r"[a-z0-9_]+", selected))
    return (
        bool(words & {"subscription", "subscriptions", "subscribed"})
        and bool(words & {"report", "reports", "catalog", "list"})
    ) or "报表订阅" in selected or "订阅清单" in selected


def report_read_plan_request(name: str, _card: Mapping[str, Any]) -> dict[str, str]:
    return {"name": name}


__all__ = [
    "REPORT_DIRECTORY_CAPABILITY", "REPORT_DIRECTORY_NAME",
    "REPORT_SUBSCRIPTIONS_CAPABILITY", "REPORT_SUBSCRIPTIONS_NAME",
    "report_directory_query", "report_read_plan_request",
    "report_subscriptions_query",
]
