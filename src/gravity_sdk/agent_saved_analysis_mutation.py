"""Direct-confirmation Agent cards for saved-Analysis CRUD."""

from __future__ import annotations

import re
from typing import Any

from .agent_intent_text import affirmative_intent_text
from .saved_analysis_mutation import UPDATE_OPERATION_ID


SELECTOR = "saved_analysis.mutation"
_ACTIONS = ("create", "update", "delete")
_VERBS = {
    "create": ({"create", "new", "save"}, ("创建", "新建")),
    "update": ({"update", "edit", "change"}, ("更新", "编辑", "修改")),
    "delete": ({"delete", "remove"}, ("删除", "移除")),
}
_SUMMARIES = {
    "create": "创建带 GSDK marker 且可严格重放的保存分析",
    "update": "替换 marker 或 owner 验证通过的保存分析完整定义",
    "delete": "删除 marker 或 owner 验证通过的保存分析并确认消失",
}
_SUBJECTS = (
    "analysis_event",
    "analysis_funnel",
    "analysis_retention",
    "analysis_scatter",
    "analysis_user_property",
)


def saved_analysis_mutation_cards(
    query: str, *, domain: str | None, platform: str | None
) -> list[dict[str, Any]]:
    if platform is not None or domain not in {None, "analysis"}:
        return []
    action = _action(query)
    return [] if action is None else [_card(query, action)]


def saved_analysis_mutation_capability_inventory() -> tuple[dict[str, Any], ...]:
    return tuple(
        _card(
            SELECTOR,
            action,
            selector=(SELECTOR if action == "create" else f"{SELECTOR}:{action}"),
        )
        for action in _ACTIONS
    )


def is_saved_analysis_mutation_card(card: Any) -> bool:
    return isinstance(card, dict) and (
        card.get("kind") == "saved_analysis_mutation"
        and str(card.get("selector", "")).startswith(SELECTOR)
        and card.get("effect") == "mutation"
        and card.get("plan_executable") is False
        and card.get("natural_language_auto_execute") is False
    )


def _action(query: str) -> str | None:
    selected = affirmative_intent_text(query)
    if selected in {SELECTOR, "saved_analysis_mutation"}:
        return "create"
    for action in _ACTIONS:
        if selected == f"{SELECTOR}:{action}":
            return action
    words = frozenset(re.findall(r"[a-z0-9_]+", selected))
    saved_analysis = (
        ({"saved", "analysis"} <= words)
        or "saved_analysis" in words
        or any(term in selected for term in ("保存分析", "已存分析"))
    )
    if not saved_analysis:
        return None
    matches = [
        action
        for action, (english, chinese) in _VERBS.items()
        if words & english or any(term in selected for term in chinese)
    ]
    if any(term in selected for term in ("保存这个分析", "保存这份分析", "把分析保存", "存下分析")):
        matches.append("create")
    matches = list(dict.fromkeys(matches))
    return matches[0] if len(matches) == 1 else None


def _card(query: str, action: str, *, selector: str = SELECTOR) -> dict[str, Any]:
    common = ["gravity", "analysis", "saved", action, "--app", "<app>"]
    argv = (
        [*common, "--id", "<saved-analysis-id>"]
        if action == "delete"
        else [
            *common,
            *(["--id", "<saved-analysis-id>"] if action == "update" else []),
            "--name", "<name>", "--subject", "<supported-subject>",
            "--config", "<config.json>",
        ]
    )
    exact = affirmative_intent_text(query) in {
        SELECTOR,
        "saved_analysis_mutation",
        f"{SELECTOR}:{action}",
    }
    input_schema, required_inputs, input_template = _input_contract(action)
    return {
        "kind": "saved_analysis_mutation",
        "selector": selector,
        "domain": "analysis",
        "description": (
            f"保存分析受治理动作 `{action}`：{_SUMMARIES[action]}；"
            "先零网络 dry-run，再由调用方人工确认同参数 execute；"
            "subject 只接受 event/funnel/retention/scatter/user-property 五类；"
            "自然语言永不自动发送写请求，且不提供分享能力。"
        ),
        "boundaries": (
            "subject 只接受 event/funnel/retention/scatter/user-property 五类。",
            "自然语言永不自动发送写请求，且不提供分享能力。",
            "Selection is read-only; preview and execute still require the governed user authorization flow.",
        ),
        "effect": "mutation",
        "mutation_action": action,
        "operation_ids": [UPDATE_OPERATION_ID],
        "executable": True,
        "plan_executable": False,
        "natural_language_auto_execute": False,
        "confirmation_required": True,
        "execution_mode": "direct_cli_after_explicit_confirmation",
        "offline": True,
        "network_called": False,
        "input_schema": input_schema,
        "required_inputs": required_inputs,
        "missing_inputs": required_inputs[1:],
        "input_template": input_template,
        "match": {
            "confidence": "strong",
            "coverage": 1.0,
            "exact_selector": exact,
            "matched_terms": [action],
            "missing_terms": [],
        },
        "next": {
            "ready_without_input": False,
            "argv": [*argv, "--dry-run"],
            "then_argv": [*argv, "--execute"],
            "call_count_after_discovery": 2,
        },
    }


def _input_contract(
    action: str,
) -> tuple[dict[str, Any], list[str], dict[str, Any]]:
    schema: dict[str, Any] = {
        "action": {"type": "string", "required": True, "enum": [action]},
        "app": {"type": ["string", "integer"], "required": True},
    }
    template: dict[str, Any] = {"action": action, "app": "<workspace-app-or-id>"}
    required = ["action", "app"]
    if action in {"update", "delete"}:
        schema["id"] = {"type": ["string", "integer"], "required": True}
        template["id"] = "<saved-analysis-id>"
        required.append("id")
    if action != "delete":
        schema.update({
            "name": {"type": "string", "required": True},
            "subject": {"type": "string", "required": True, "enum": list(_SUBJECTS)},
            "config": {"type": "object", "required": True},
            "remark": {"type": "string", "required": False},
            "start": {"type": "string", "required": False},
            "end": {"type": "string", "required": False},
        })
        template.update({
            "name": "<name>", "subject": "<one-enumerated-subject>",
            "config": "<validated-definition-object>",
        })
        required.extend(("name", "subject", "config"))
    return schema, required, template


__all__ = [
    "SELECTOR",
    "is_saved_analysis_mutation_card",
    "saved_analysis_mutation_capability_inventory",
    "saved_analysis_mutation_cards",
]
