"""Agent cards for bounded metadata onboarding and offline status."""

from __future__ import annotations

import copy
import re
from typing import Any

from .intent_text import affirmative_intent_text
from ..metadata_onboarding import DEFAULT_MAX_PAGES, app_sync_request_budget


SYNC_SELECTOR = "metadata:sync_app"
STATUS_SELECTOR = "metadata:status"


def metadata_onboarding_capability_cards(
    query: str, *, domain: str | None, platform: str | None
) -> list[dict[str, Any]]:
    if platform is not None or domain not in {None, "metadata", "analysis"}:
        return []
    selected = affirmative_intent_text(query).strip().casefold()
    if _status_intent(selected):
        return [_status_card(selected)]
    if _sync_intent(selected):
        return [_sync_card(selected)]
    return []


def metadata_onboarding_capability_inventory() -> tuple[dict[str, Any], ...]:
    return (
        _sync_card(SYNC_SELECTOR),
        _status_card(STATUS_SELECTOR),
    )


def _sync_card(query: str) -> dict[str, Any]:
    budget = app_sync_request_budget("<app-id>", max_pages=DEFAULT_MAX_PAGES)
    return {
        "kind": "composite",
        "selector": SYNC_SELECTOR,
        "composite": "metadata_sync",
        "metadata_kind": "sync_app",
        "domain": "metadata",
        "description": (
            "只为一个显式 App 同步事件、事件属性、用户属性和事件属性分组；"
            "按页上限给出同步前逻辑请求界，执行后报告实际页数、对象数和失败来源。"
        ),
        "boundaries": (
            "只为一个显式 App 同步事件、事件属性、用户属性和事件属性分组。",
            "不同步账号级数据表血缘。",
        ),
        "scope": "single_app",
        "effect": "local_catalog_write",
        "executable": True,
        "plan_executable": True,
        "offline": False,
        "network_called": True,
        "natural_language_auto_execute": False,
        "required_inputs": ["app"],
        "missing_inputs": ["app"],
        "input_template": {"app": "<app-id-or-alias>"},
        "input_schema": {
            "app": {
                "type": "string|integer",
                "required": True,
                "nullable": False,
                "description": "Exact App id or workspace App alias.",
            },
            "max_pages": {
                "type": "integer",
                "required": False,
                "default": DEFAULT_MAX_PAGES,
                "minimum": 1,
                "maximum": 8,
            },
        },
        "request_budget": copy.deepcopy(budget),
        "plan_node_limits": {
            "max_pages": DEFAULT_MAX_PAGES,
            "max_items": 100_000,
        },
        "match": _match(query, SYNC_SELECTOR),
        "next": {
            "ready_without_input": False,
            "argv": [
                "gravity", "metadata", "sync", "--app-id", "<app-id>",
                "--max-pages", str(DEFAULT_MAX_PAGES),
            ],
            "estimate_argv": [
                "gravity", "metadata", "sync", "--app-id", "<app-id>",
                "--max-pages", str(DEFAULT_MAX_PAGES), "--dry-run",
            ],
        },
        "next_action": (
            "Fill the exact App and optionally lower or raise limits.max_pages; "
            "run the estimate command first when a separate cost receipt is required."
        ),
    }


def _status_card(query: str) -> dict[str, Any]:
    return {
        "kind": "metadata",
        "selector": STATUS_SELECTOR,
        "metadata_kind": "status",
        "domain": "metadata",
        "description": (
            "离线报告本地 metadata catalog 是否存在/兼容、哪些 App 同步过、"
            "同步时间、对象与失败数，以及相对 freshness 阈值是否过期。"
        ),
        "boundaries": (
            "只报告本地 catalog 状态，不同步任何 App。",
            "不搜索事件或属性名称。",
        ),
        "scope": "local_catalog",
        "effect": "local_read",
        "executable": True,
        "plan_executable": True,
        "offline": True,
        "network_called": False,
        "required_inputs": [],
        "missing_inputs": [],
        "input_schema": {
            "app_id": {
                "type": "string|integer",
                "required": False,
                "nullable": False,
            },
            "max_age_hours": {
                "type": "integer",
                "required": False,
                "default": 24,
                "minimum": 1,
                "maximum": 8_760,
            },
        },
        "plan_node_limits": {"max_pages": 1, "max_items": 20},
        "match": _match(query, STATUS_SELECTOR),
        "next": {
            "ready_without_input": True,
            "argv": ["gravity", "metadata", "status"],
        },
        "next_action": (
            "Execute the Plan node as-is for every local App, or add request.app_id "
            "to inspect one exact App; the answer never contacts Gravity."
        ),
    }


def _sync_intent(query: str) -> bool:
    if query == SYNC_SELECTOR:
        return True
    words = frozenset(re.findall(r"[a-z0-9_]+", query))
    return (
        bool(words & {"sync", "synchronize", "refresh"})
        and "metadata" in words
        and bool(words & {"app", "application", "bounded", "single"})
    ) or (
        "元数据" in query
        and any(term in query for term in ("同步", "刷新"))
        and any(term in query for term in ("app", "应用", "单个", "指定"))
    )


def _status_intent(query: str) -> bool:
    if query == STATUS_SELECTOR:
        return True
    words = frozenset(re.findall(r"[a-z0-9_]+", query))
    return (
        "metadata" in words
        and bool(words & {"status", "state", "fresh", "freshness", "stale"})
    ) or (
        "元数据" in query
        and any(term in query for term in ("状态", "过期", "新鲜", "同步过"))
    )


def _match(query: str, selector: str) -> dict[str, Any]:
    exact = query == selector
    return {
        "confidence": "strong",
        "coverage": 1.0,
        "matched_terms": [query],
        "missing_terms": [],
        "score": 100,
        "exact_selector": exact,
        "intent_only": not exact,
    }


__all__ = [
    "STATUS_SELECTOR",
    "SYNC_SELECTOR",
    "metadata_onboarding_capability_cards",
    "metadata_onboarding_capability_inventory",
]
