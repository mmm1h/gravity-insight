"""Strict Agent handoff for company resource-usage trends."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from .agent_intent_text import affirmative_intent_text


COMPANY_USAGE_NAME = "company_usage"
COMPANY_USAGE_SELECTOR = f"composite:{COMPANY_USAGE_NAME}"
_EXACT = frozenset({
    COMPANY_USAGE_NAME,
    COMPANY_USAGE_SELECTOR,
    "company resource usage",
    "company usage trend",
    "公司资源用量",
    "公司用量趋势",
})


COMPANY_USAGE_CAPABILITY: Mapping[str, Any] = {
    "name": COMPANY_USAGE_NAME,
    "domain": "report",
    "aliases": (
        "company resource usage",
        "company usage trend",
        "公司资源用量",
        "公司用量趋势",
    ),
    "description": (
        "读取公司级按日广告、点击、成本、事件、画像、存储、追踪和素材传输用量。"
    ),
    "required_inputs": (),
    "input_schema": {},
}


def company_usage_query(query: str) -> bool:
    selected = affirmative_intent_text(query)
    if selected in _EXACT:
        return True
    if not selected:
        return False
    words = frozenset(re.findall(r"[a-z0-9_]+", selected))
    if words & {"not", "without", "exclude", "export", "app"}:
        return False
    english = "company" in words and bool(words & {"usage", "consumption"}) and bool(
        words & {"resource", "resources", "trend", "trends", "usage"}
    )
    chinese = "公司" in selected and "用量" in selected and any(
        term in selected for term in ("资源", "消耗", "趋势", "用量")
    )
    return english or chinese


def company_usage_intent(query: str) -> bool:
    return company_usage_query(query)


def company_usage_plan_request(_card: Mapping[str, Any]) -> dict[str, str]:
    return {"name": COMPANY_USAGE_NAME}


__all__ = [
    "COMPANY_USAGE_CAPABILITY",
    "COMPANY_USAGE_NAME",
    "COMPANY_USAGE_SELECTOR",
    "company_usage_intent",
    "company_usage_plan_request",
    "company_usage_query",
]
