"""Natural-language gaps owned by unavailable App catalog journeys."""

from __future__ import annotations

import re
from typing import Any

from .agent_gap import unavailable_gap
from .agent_intent_text import affirmative_intent_text


def unavailable_app_gap(query: str) -> dict[str, Any] | None:
    selected = affirmative_intent_text(query)
    words = frozenset(re.findall(r"[a-z0-9_]+", selected))
    if _readable_projects(selected, words):
        return unavailable_gap(
            query, code="APP_PROJECT_ITEM_SCHEMA_MISSING",
            journey="readable_app_projects",
            reason="The project-list request and pagination are verified, but the current account returned an empty first page.",
            next_action=(
                "Use an account with one readable project for a single page=1/page_size=1 shape probe, "
                "then register the item projection before adding product surfaces."
            ),
        )
    if _onelink_public_info(selected, words):
        return unavailable_gap(
            query, code="APP_ONELINK_PUBLIC_BINDING_SAMPLE_MISSING",
            journey="app_onelink_public_binding",
            reason="OneLink is empty for this account and known public-store URL reads are error-shaped, not successful bindings.",
            next_action=(
                "Provide one caller-known public store URL that Gravity can resolve, then perform exactly one read "
                "and register the successful shape without image bytes or values."
            ),
        )
    return None


def _readable_projects(selected: str, words: frozenset[str]) -> bool:
    english = (
        bool(words & {"project", "projects"})
        and bool(words & {"account", "allowed", "app", "catalog", "directory", "list", "read", "readable"})
    )
    chinese = (
        "项目" in selected
        and any(term in selected for term in ("app", "当前账号", "可读", "可以读取", "读取", "清单", "列表"))
    )
    return english or chinese


def _onelink_public_info(selected: str, words: frozenset[str]) -> bool:
    english = (
        "onelink" in words
        and bool(words & {"store", "public", "binding", "information"})
    )
    chinese = (
        "onelink" in words
        and any(term in selected for term in ("应用商店", "公开信息", "绑定"))
    )
    return english or chinese


__all__ = ["unavailable_app_gap"]
