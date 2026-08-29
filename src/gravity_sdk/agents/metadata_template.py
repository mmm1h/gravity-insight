"""Distinct Agent action cards for governed metadata-template lifecycle."""

from __future__ import annotations

import re
from typing import Any

from .intent_text import affirmative_intent_text
from ..metadata_template_contracts import (
    TEMPLATE_APPEND,
    TEMPLATE_EVENT_REMOVE,
    TEMPLATE_MASTER,
    TEMPLATE_PROPERTY_REMOVE,
)
from ..metadata_template_mutation import metadata_template_mutation_schema


SELECTORS = {
    "create": "metadata_template.create",
    "append": "metadata_template.append",
    "remove": "metadata_template.remove",
    "delete": "metadata_template.delete",
}
_SUBJECTS = ("metadata template", "property template", "元数据模板", "属性模板")
_VERBS = {
    "create": ({"create", "new"}, ("创建", "新建")),
    "append": ({"append", "add"}, ("追加", "添加成员")),
    "remove": ({"remove", "detach"}, ("移除成员", "删除成员")),
    "delete": ({"delete"}, ("删除模板",)),
}
_ACTION_OPERATIONS = {
    "create": (TEMPLATE_MASTER,),
    "append": (TEMPLATE_APPEND,),
    "remove": (TEMPLATE_EVENT_REMOVE, TEMPLATE_PROPERTY_REMOVE),
    "delete": (TEMPLATE_MASTER,),
}


def metadata_template_cards(
    query: str, *, domain: str | None, platform: str | None
) -> list[dict[str, Any]]:
    if platform is not None or domain not in {None, "analysis", "metadata"}:
        return []
    action = _action(query)
    return [] if action is None else [_card(query, action)]


def metadata_template_capability_inventory() -> tuple[dict[str, Any], ...]:
    return tuple(
        metadata_template_cards(selector, domain=None, platform=None)[0]
        for selector in SELECTORS.values()
    )


def is_metadata_template_card(card: Any) -> bool:
    return isinstance(card, dict) and (
        card.get("kind") == "metadata_template_mutation"
        and card.get("selector") in SELECTORS.values()
        and card.get("effect") == "mutation"
        and card.get("plan_executable") is True
        and card.get("natural_language_auto_execute") is False
    )


def _action(query: str) -> str | None:
    selected = affirmative_intent_text(query)
    exact = [action for action, selector in SELECTORS.items() if selected == selector]
    if exact:
        return exact[0]
    if not any(term in selected for term in _SUBJECTS):
        return None
    words = frozenset(re.findall(r"[a-z0-9_-]+", selected))
    matches = [
        action
        for action, (english, chinese) in _VERBS.items()
        if words & english or any(term in selected for term in chinese)
    ]
    return matches[0] if len(matches) == 1 else None


def _card(query: str, action: str) -> dict[str, Any]:
    selector = SELECTORS[action]
    plan_inputs = {"action": action, "inputs": "<exact-input-object>"}
    preview = {
        "name": "metadata_template_mutation", "mode": "preview",
        "inputs": plan_inputs,
    }
    argv = [
        "gravity", "metadata", "property-templates", "mutate",
        "--action", action, "--input", "<inputs.json>",
    ]
    summaries = {
        "create": "创建带 GSDK marker 且成员可读回的事件/属性模板",
        "append": "向 marker 或 owner 已验证模板追加精确目录成员",
        "remove": "在成员 preimage 后移除事件或属性并确认消失",
        "delete": "在 master preimage 后软删模板并确认 ID 消失",
    }
    return {
        "kind": "metadata_template_mutation", "selector": selector,
        "domain": "metadata",
        "description": (
            f"元数据模板受治理动作 `{action}`：{summaries[action]}；"
            "先 dry-run，人工审查后以同参数 execute；自然语言永不自动写入。"
        ),
        "boundaries": (
            "自然语言永不自动写入。",
            "Selection is read-only; preview and execute still require the governed user authorization flow.",
        ),
        "effect": "mutation", "mutation_action": action,
        "operation_ids": list(_ACTION_OPERATIONS[action]),
        "executable": True, "plan_executable": True,
        "natural_language_auto_execute": False, "confirmation_required": True,
        "execution_mode": "explicit_plan_or_cli_after_human_review",
        "offline": False, "network_called": False,
        "input_schema": metadata_template_mutation_schema()["actions"][action],
        "required_inputs": ["action", "inputs"], "missing_inputs": ["inputs"],
        "input_template": plan_inputs,
        "match": {
            "confidence": "strong", "coverage": 1.0,
            "exact_selector": affirmative_intent_text(query) == selector,
            "matched_terms": [action], "missing_terms": [],
        },
        "next": {
            "ready_without_input": False,
            "argv": [*argv, "--dry-run"], "then_argv": [*argv, "--execute"],
            "plan_node": {
                "id": f"metadata-template-{action}-preview", "kind": "composite",
                "request": preview,
            },
            "then_plan_node": {
                "id": f"metadata-template-{action}-execute", "kind": "composite",
                "request": {**preview, "mode": "execute"},
            },
            "call_count_after_discovery": 2,
        },
    }


__all__ = [
    "SELECTORS", "is_metadata_template_card",
    "metadata_template_capability_inventory", "metadata_template_cards",
]
