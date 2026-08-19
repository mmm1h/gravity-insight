"""Direct-confirmation Agent card for the realtime-event warehousing write."""

from __future__ import annotations

import re
from typing import Any

from .agent_intent_text import affirmative_intent_text
from .realtime_event_contracts import REALTIME_EVENT_UPDATE
from .realtime_event_mutation import realtime_event_mutation_schema


SELECTOR = "realtime_event.mutation"
_SUBJECTS = (
    "realtime event warehousing",
    "real-time event warehousing",
    "realtime warehousing",
    "real-time warehousing",
    "实时事件入库",
    "实时入库开关",
)
_VERBS = ({"update", "enable", "disable", "open", "close"}, ("开启", "关闭", "更新", "打开", "关掉"))


def realtime_event_mutation_cards(
    query: str, *, domain: str | None, platform: str | None
) -> list[dict[str, Any]]:
    if platform is not None or domain not in {None, "app", "analysis"}:
        return []
    return [] if _action(query) is None else [_card(query)]


def realtime_event_mutation_capability_inventory() -> tuple[dict[str, Any], ...]:
    return (_card(SELECTOR),)


def is_realtime_event_mutation_card(card: Any) -> bool:
    return isinstance(card, dict) and (
        card.get("kind") == "realtime_event_mutation"
        and card.get("selector") == SELECTOR
        and card.get("effect") == "mutation"
        and card.get("plan_executable") is False
        and card.get("natural_language_auto_execute") is False
    )


def _action(query: str) -> str | None:
    selected = affirmative_intent_text(query)
    if selected in {SELECTOR, "realtime_event_mutation"}:
        return "update"
    if not any(term in selected for term in _SUBJECTS):
        return None
    words = frozenset(re.findall(r"[a-z0-9_-]+", selected))
    if words & _VERBS[0] or any(term in selected for term in _VERBS[1]):
        return "update"
    return None


def _card(query: str) -> dict[str, Any]:
    argv = ["gravity", "apps", "realtime-event", "update", "--input", "<inputs.json>"]
    return {
        "kind": "realtime_event_mutation",
        "selector": SELECTOR,
        "domain": "app",
        "description": (
            "设置单个 App 的实时事件入库开关与时间窗；"
            "先零网络 dry-run，再由调用方确认同参数 execute；"
            "执行后读回 app.realtime_event.list.conf；自然语言永不自动写。"
        ),
        "boundaries": (
            "自然语言永不自动写。",
            "不读取实时事件目录。",
            "Selection is read-only; preview and execute still require the governed user authorization flow.",
        ),
        "effect": "mutation",
        "mutation_action": "update",
        "operation_id": REALTIME_EVENT_UPDATE,
        "operation_ids": [REALTIME_EVENT_UPDATE],
        "executable": True,
        "plan_executable": False,
        "natural_language_auto_execute": False,
        "confirmation_required": True,
        "execution_mode": "direct_cli_after_explicit_confirmation",
        "offline": True,
        "network_called": False,
        "input_schema": realtime_event_mutation_schema()["actions"]["update"],
        "required_inputs": ["inputs"],
        "missing_inputs": ["inputs"],
        "input_template": {
            "app_id": "<positive-app-id>",
            "is_enabled": "<0|1>",
            "start_time": "<YYYY-MM-DD HH:MM:SS>",
            "end_time": "<YYYY-MM-DD HH:MM:SS>",
            "time_slot": 2,
        },
        "match": {
            "confidence": "strong",
            "coverage": 1.0,
            "exact_selector": affirmative_intent_text(query) == SELECTOR,
            "matched_terms": ["update"],
            "missing_terms": [],
        },
        "next": {
            "ready_without_input": False,
            "argv": [*argv, "--dry-run"],
            "then_argv": [*argv, "--execute"],
            "call_count_after_discovery": 2,
        },
    }


__all__ = [
    "SELECTOR",
    "is_realtime_event_mutation_card",
    "realtime_event_mutation_capability_inventory",
    "realtime_event_mutation_cards",
]
