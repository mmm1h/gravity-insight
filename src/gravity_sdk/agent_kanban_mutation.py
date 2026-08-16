"""Explicit-confirmation Agent handoff for governed Kanban mutations."""

from __future__ import annotations

import re
from typing import Any

from .agent_intent_text import affirmative_intent_text
from .kanban_mutation import kanban_mutation_schema


SELECTOR = "kanban.mutation"
_RESOURCE_TERMS = {
    "space": ({"space", "workspace"}, ("空间",)),
    "folder": ({"folder", "directory"}, ("文件夹", "目录")),
    "dashboard": ({"dashboard", "kanban", "board"}, ("看板", "仪表盘")),
    "note": ({"note"}, ("便签", "注释")),
}
_VERB_TERMS = {
    "create": ({"create", "add", "new"}, ("创建", "新建")),
    "rename": ({"rename"}, ("重命名", "改名")),
    "delete": ({"delete", "remove"}, ("删除",)),
    "move": ({"move"}, ("移动",)),
    "copy": ({"copy", "duplicate"}, ("复制",)),
    "transfer": ({"transfer"}, ("移交", "转交")),
}


def kanban_mutation_cards(
    query: str, *, domain: str | None, platform: str | None
) -> list[dict[str, Any]]:
    if platform is not None or domain not in {None, "analysis", "dashboard"}:
        return []
    action = _action(query)
    return [] if action is None else [_card(query, action)]


def kanban_mutation_capability_inventory() -> tuple[dict[str, Any], ...]:
    return tuple(kanban_mutation_cards(SELECTOR, domain=None, platform=None))


def is_kanban_mutation_card(card: Any) -> bool:
    return isinstance(card, dict) and (
        card.get("kind") == "kanban_mutation"
        and card.get("selector") == SELECTOR
        and card.get("effect") == "mutation"
        and card.get("plan_executable") is True
        and card.get("natural_language_auto_execute") is False
    )


def _action(query: str) -> str | None:
    selected = affirmative_intent_text(query)
    if selected in {SELECTOR, "kanban_mutation"}:
        return "space.create"
    words = frozenset(re.findall(r"[a-z0-9_-]+", selected))
    resource = _matched_key(words, selected, _RESOURCE_TERMS)
    verb = _matched_key(words, selected, _VERB_TERMS)
    if resource is None or verb is None:
        return None
    action = f"{resource}.{verb}"
    return action if action in kanban_mutation_schema()["actions"] else None


def _matched_key(
    words: frozenset[str],
    selected: str,
    vocabulary: dict[str, tuple[set[str], tuple[str, ...]]],
) -> str | None:
    matches = [
        key
        for key, (english, chinese) in vocabulary.items()
        if words & english or any(term in selected for term in chinese)
    ]
    return matches[0] if len(matches) == 1 else None


def _card(query: str, action: str) -> dict[str, Any]:
    plan_inputs = {"action": action, "inputs": "<exact-input-object>"}
    plan_request = {"name": "kanban_mutation", "mode": "preview", "inputs": plan_inputs}
    execute_request = {**plan_request, "mode": "execute"}
    argv = [
        "gravity", "analysis", "dashboard", "kanban", "mutate",
        "--action", action, "--input", "<inputs.json>",
    ]
    return {
        "kind": "kanban_mutation",
        "selector": SELECTOR,
        "domain": "analysis",
        "description": "看板写操作只交接精确 SDK/CLI/Plan 输入：先 dry-run，再人工确认同参数 execute；自然语言永不自动写入。",
        "effect": "mutation",
        "mutation_action": action,
        "executable": True,
        "plan_executable": True,
        "natural_language_auto_execute": False,
        "confirmation_required": True,
        "execution_mode": "explicit_plan_or_cli_after_human_review",
        "offline": False,
        "network_called": False,
        "input_schema": kanban_mutation_schema()["actions"][action],
        "required_inputs": ["action", "inputs"],
        "missing_inputs": ["inputs"],
        "input_template": plan_inputs,
        "match": {
            "confidence": "strong",
            "coverage": 1.0,
            "exact_selector": affirmative_intent_text(query) in {SELECTOR, "kanban_mutation"},
            "matched_terms": [action],
            "missing_terms": [],
        },
        "next": {
            "ready_without_input": False,
            "argv": [*argv, "--dry-run"],
            "then_argv": [*argv, "--execute"],
            "plan_node": {"id": "kanban-preview", "kind": "composite", "request": plan_request},
            "then_plan_node": {"id": "kanban-execute", "kind": "composite", "request": execute_request},
            "call_count_after_discovery": 2,
        },
    }


__all__ = [
    "SELECTOR",
    "is_kanban_mutation_card",
    "kanban_mutation_capability_inventory",
    "kanban_mutation_cards",
]
