"""Explicit-confirmation Agent handoff for governed Kanban mutations."""

from __future__ import annotations

import re
from typing import Any

from .agent_intent_text import affirmative_intent_text
from .kanban_mutation import kanban_mutation_schema
from .kanban_mutation_contracts import (
    DASHBOARD_COPY,
    DASHBOARD_CREATE,
    DASHBOARD_DELETE,
    DASHBOARD_FOLDER_MOVE,
    DASHBOARD_MOVE,
    DASHBOARD_ORDER,
    DASHBOARD_RENAME,
    DASHBOARD_UPDATE,
    FOLDER_CREATE,
    FOLDER_DELETE,
    FOLDER_MOVE,
    FOLDER_UPDATE,
    NOTE_DELETE,
    REPORT_UNLINK,
    SPACE_CREATE,
    SPACE_DELETE,
    SPACE_TRANSFER,
    SPACE_UPDATE,
)


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
_ACTION_OPERATIONS = {
    "space.create": (SPACE_CREATE,),
    "space.rename": (SPACE_UPDATE,),
    "space.delete": (SPACE_DELETE,),
    "space.transfer": (SPACE_TRANSFER,),
    "folder.create": (FOLDER_CREATE,),
    "folder.rename": (FOLDER_UPDATE,),
    "folder.delete": (FOLDER_DELETE,),
    "folder.move": (FOLDER_MOVE,),
    "dashboard.create": (DASHBOARD_CREATE,),
    "dashboard.rename": (DASHBOARD_RENAME,),
    "dashboard.delete": (DASHBOARD_DELETE,),
    "dashboard.delete-many": (DASHBOARD_DELETE,),
    "dashboard.move": (DASHBOARD_MOVE,),
    "dashboard.move-folder": (DASHBOARD_FOLDER_MOVE,),
    "dashboard.copy": (DASHBOARD_COPY,),
    "dashboard.notes.replace": (DASHBOARD_UPDATE,),
    "dashboard.report.link": (DASHBOARD_UPDATE,),
    "dashboard.report.unlink": (REPORT_UNLINK,),
    "dashboard.order.save": (DASHBOARD_ORDER,),
    "note.delete": (NOTE_DELETE,),
}
_ACTION_SUMMARIES = {
    "space.create": "创建带 SDK marker 的看板空间",
    "space.rename": "重命名 marker 或 owner 验证通过的看板空间",
    "space.delete": "删除 marker 或 owner 验证通过的看板空间",
    "space.transfer": "把 marker 或 owner 验证通过的空间移交给精确用户",
    "folder.create": "在精确空间中创建带 SDK marker 的文件夹",
    "folder.rename": "重命名 SDK marker 文件夹",
    "folder.delete": "删除 SDK marker 文件夹并预览后代迁移",
    "folder.move": "跨空间移动 SDK marker 文件夹及其后代",
    "dashboard.create": "在精确空间或文件夹中创建空看板",
    "dashboard.rename": "重命名 marker 或 owner 验证通过的看板",
    "dashboard.delete": "删除一个无报表关联的 SDK marker 看板",
    "dashboard.delete-many": "批量删除无报表关联的 SDK marker 看板",
    "dashboard.move": "跨空间移动 marker 或 owner 验证通过的看板",
    "dashboard.move-folder": "在同一空间内移动看板到精确文件夹",
    "dashboard.copy": "复制不含报表关联的看板并写入 SDK marker",
    "dashboard.notes.replace": "替换看板内的 note-only 布局",
    "dashboard.report.link": "把当前 principal 可见的精确保存分析挂到看板并保留已有内容",
    "dashboard.report.unlink": "从看板移除精确报表关联",
    "dashboard.order.save": "保存看板树的同级顺序",
    "note.delete": "删除精确 SDK marker 的看板内嵌 note",
}


def kanban_mutation_cards(
    query: str, *, domain: str | None, platform: str | None
) -> list[dict[str, Any]]:
    if platform is not None or domain not in {None, "analysis", "dashboard"}:
        return []
    action = _action(query)
    return [] if action is None else [_card(query, action)]


def kanban_mutation_capability_inventory() -> tuple[dict[str, Any], ...]:
    actions = tuple(kanban_mutation_schema()["actions"])
    ordered = ("space.create", *(action for action in actions if action != "space.create"))
    return tuple(
        _card(
            SELECTOR,
            action,
            selector=(SELECTOR if action == "space.create" else f"{SELECTOR}:{action}"),
        )
        for action in ordered
    )


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


def _card(query: str, action: str, *, selector: str = SELECTOR) -> dict[str, Any]:
    plan_inputs = {"action": action, "inputs": "<exact-input-object>"}
    plan_request = {"name": "kanban_mutation", "mode": "preview", "inputs": plan_inputs}
    execute_request = {**plan_request, "mode": "execute"}
    argv = [
        "gravity", "analysis", "dashboard", "kanban", "mutate",
        "--action", action, "--input", "<inputs.json>",
    ]
    return {
        "kind": "kanban_mutation",
        "selector": selector,
        "domain": "analysis",
        "description": (
            f"看板受治理动作 `{action}`：{_ACTION_SUMMARIES[action]}；"
            "只交接精确 SDK/CLI/Plan 输入，先 dry-run，再人工确认同参数 execute；"
            "自然语言永不自动写入。"
        ),
        "boundaries": (
            "只交接精确 SDK/CLI/Plan 输入，先 dry-run，再人工确认同参数 execute。",
            "自然语言永不自动写入。",
            "Selection is read-only; preview and execute still require the governed user authorization flow.",
        ),
        "effect": "mutation",
        "mutation_action": action,
        "operation_ids": list(_ACTION_OPERATIONS[action]),
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
