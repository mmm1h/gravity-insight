"""Direct-confirmation Agent cards for report mutations."""

from __future__ import annotations

import re
from typing import Any

from .agent_intent_text import affirmative_intent_text
from .report_contracts import REPORT_UPDATE, SUBSCRIBE_CREATE, SUBSCRIBE_DELETE


SELECTOR = "report.mutation"
_ACTIONS = (
    "create-report",
    "delete-report",
    "create-subscription",
    "delete-subscription",
)
_COMMANDS = {
    "create-report": [
        "create", "--app-id", "<app-id>", "--name", "<test-name>",
        "--config", "<config.json>",
    ],
    "delete-report": ["delete", "--report-id", "<report-id>"],
    "create-subscription": [
        "subscribe", "--report-id", "<report-id>", "--report-name",
        "<report-name>", "--start", "<start>", "--end", "<end>",
        "--column", "<column>",
    ],
    "delete-subscription": [
        "unsubscribe", "--subscription-id", "<subscription-id>",
    ],
}
_ACTION_OPERATIONS = {
    "create-report": (REPORT_UPDATE,),
    "delete-report": (REPORT_UPDATE,),
    "create-subscription": (SUBSCRIBE_CREATE,),
    "delete-subscription": (SUBSCRIBE_DELETE,),
}
_ACTION_SUMMARIES = {
    "create-report": "创建带 SDK marker 的测试报表",
    "delete-report": "删除 marker 或 owner 验证通过的报表",
    "create-subscription": "创建 disabled、无收件人的报表订阅",
    "delete-subscription": "删除 marker 或 owner 验证通过的报表订阅",
}


def report_mutation_cards(
    query: str, *, domain: str | None, platform: str | None,
) -> list[dict[str, Any]]:
    if platform is not None or domain not in {None, "report"}:
        return []
    selected = affirmative_intent_text(query)
    words = frozenset(re.findall(r"[a-z0-9_]+", selected))
    if words & {"download", "export"} or any(term in selected for term in ("下载", "导出")):
        return []
    action = _action(query)
    return [] if action is None else [_card(query, action)]


def report_mutation_capability_inventory() -> tuple[dict[str, Any], ...]:
    """Materialize every caller-facing report-mutation handoff card."""

    return tuple(
        _card(
            SELECTOR,
            action,
            selector=(SELECTOR if action == _ACTIONS[0] else f"{SELECTOR}:{action}"),
        )
        for action in _ACTIONS
    )


def is_report_mutation_card(card: Any) -> bool:
    return isinstance(card, dict) and (
        card.get("kind") == "report_mutation"
        and card.get("selector") == SELECTOR
        and card.get("effect") == "mutation"
        and card.get("plan_executable") is False
        and card.get("natural_language_auto_execute") is False
    )


def _action(query: str) -> str | None:
    selected = affirmative_intent_text(query)
    if selected in {SELECTOR, "report_mutation"}:
        return "create-report"
    words = frozenset(re.findall(r"[a-z0-9_]+", selected))
    subscription = _has_intent(words, selected, {"subscription", "subscriptions", "subscribe"}, ("订阅",))
    report = _has_intent(words, selected, {"report", "reports"}, ("报表",))
    if not report and not subscription:
        return None
    deleting = _has_intent(words, selected, {"delete", "remove", "unsubscribe"}, ("删除", "取消订阅"))
    creating = _has_intent(words, selected, {"create", "add", "subscribe"}, ("创建", "新建"))
    if subscription and deleting:
        return "delete-subscription"
    if subscription and creating:
        return "create-subscription"
    if report and deleting:
        return "delete-report"
    if report and creating:
        return "create-report"
    return None


def _has_intent(
    words: frozenset[str], selected: str, english: set[str], chinese: tuple[str, ...],
) -> bool:
    return bool(words & english) or any(term in selected for term in chinese)


def _card(query: str, action: str, *, selector: str = SELECTOR) -> dict[str, Any]:
    command = _COMMANDS[action]
    base = ["gravity", "reports", *command]
    return {
        "kind": "report_mutation",
        "selector": selector,
        "domain": "report",
        "description": (
            f"报表受治理动作 `{action}`：{_ACTION_SUMMARIES[action]}；"
            "只交接显式 CLI，先零网络 dry-run，再由调用方确认执行；"
            "自然语言永不自动发送写请求。"
        ),
        "boundaries": (
            "只交接显式 CLI，先零网络 dry-run，再由调用方确认执行。",
            "自然语言永不自动发送写请求。",
            "Selection is read-only; preview and execute still require the governed user authorization flow.",
        ),
        "effect": "mutation",
        "mutation_action": action,
        "operation_ids": list(_ACTION_OPERATIONS[action]),
        "executable": True,
        "plan_executable": False,
        "natural_language_auto_execute": False,
        "confirmation_required": True,
        "execution_mode": "direct_cli_after_explicit_confirmation",
        "offline": True,
        "network_called": False,
        "input_schema": {
            "action": {"type": "string", "required": True},
            "explicit_inputs": {"type": "object", "required": True},
        },
        "required_inputs": ["action", "explicit_inputs"],
        "missing_inputs": ["action", "explicit_inputs"],
        "input_template": {
            "action": action,
            "explicit_inputs": "<fill from authoritative IDs/config; do not copy identifiers from natural language>",
        },
        "match": {
            "confidence": "strong", "coverage": 1.0, "exact_selector": selected_exact(query),
            "matched_terms": [action], "missing_terms": [],
        },
        "next": {
            "ready_without_input": False,
            "argv": [*base, "--dry-run"],
            "then_argv": [*base, "--execute"],
            "call_count_after_discovery": 2,
        },
    }


def selected_exact(query: str) -> bool:
    return affirmative_intent_text(query) in {SELECTOR, "report_mutation"}


__all__ = [
    "SELECTOR",
    "is_report_mutation_card",
    "report_mutation_capability_inventory",
    "report_mutation_cards",
]
