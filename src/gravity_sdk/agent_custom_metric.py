"""Distinct Agent product cards for each custom-metric lifecycle capability."""

from __future__ import annotations

import re
from typing import Any

from .agent_intent_text import affirmative_intent_text
from .custom_metric_contracts import (
    CUSTOM_METRIC_DELETE,
    CUSTOM_METRIC_LIST,
    CUSTOM_METRIC_UPSERT,
)
from .custom_metric_mutation import custom_metric_mutation_schema


SELECTORS = {
    "list": "custom_metric.list",
    "create": "custom_metric.create",
    "update": "custom_metric.update",
    "delete": "custom_metric.delete",
}
_CUSTOM_TERMS = ("custom metric", "custom metrics", "自定义指标", "口径指标")
_VERBS = {
    "list": ({"list", "read", "show", "view"}, ("查看", "列出", "读取", "列表")),
    "create": ({"create", "add", "new"}, ("创建", "新建", "添加")),
    "update": ({"update", "edit", "change"}, ("更新", "编辑", "修改")),
    "delete": ({"delete", "remove"}, ("删除", "移除")),
}


def custom_metric_cards(
    query: str, *, domain: str | None, platform: str | None
) -> list[dict[str, Any]]:
    if platform is not None or domain not in {None, "report", "metadata"}:
        return []
    action = _action(query)
    return [] if action is None else [_card(query, action)]


def custom_metric_capability_inventory() -> tuple[dict[str, Any], ...]:
    return tuple(
        custom_metric_cards(selector, domain=None, platform=None)[0]
        for selector in SELECTORS.values()
    )


def is_custom_metric_card(card: Any) -> bool:
    return isinstance(card, dict) and (
        card.get("kind") in {"custom_metric_list", "custom_metric_mutation"}
        and card.get("selector") in SELECTORS.values()
        and card.get("plan_executable") is True
        and card.get("natural_language_auto_execute") is False
    )


def _action(query: str) -> str | None:
    selected = affirmative_intent_text(query)
    exact = [action for action, selector in SELECTORS.items() if selected == selector]
    if exact:
        return exact[0]
    if not any(term in selected for term in _CUSTOM_TERMS):
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
    if action == "list":
        plan_node = {
            "id": "custom-metric-list", "kind": "run",
            "request": {
                "selector": CUSTOM_METRIC_LIST,
                "inputs": {"filters": [], "page": 1, "page_size": 5_000},
                "all_pages": True,
            },
        }
        return _base(query, action, selector) | {
            "kind": "custom_metric_list", "effect": "read",
            "operation_id": CUSTOM_METRIC_LIST,
            "input_schema": {"max_pages": {"type": "integer"}, "max_items": {"type": "integer"}},
            "required_inputs": [], "missing_inputs": [],
            "next": {
                "ready_without_input": True,
                "argv": ["gravity", "reports", "custom-metrics", "list"],
                "plan_node": plan_node, "call_count_after_discovery": 1,
            },
        }
    plan_inputs = {"action": action, "inputs": "<exact-input-object>"}
    preview = {"name": "custom_metric_mutation", "mode": "preview", "inputs": plan_inputs}
    argv = ["gravity", "reports", "custom-metrics", action, "<exact-options>"]
    return _base(query, action, selector) | {
        "kind": "custom_metric_mutation", "effect": "mutation",
        "operation_id": CUSTOM_METRIC_DELETE if action == "delete" else CUSTOM_METRIC_UPSERT,
        "operation_ids": [CUSTOM_METRIC_DELETE if action == "delete" else CUSTOM_METRIC_UPSERT],
        "mutation_action": action, "confirmation_required": True,
        "execution_mode": "explicit_plan_or_cli_after_human_review",
        "input_schema": custom_metric_mutation_schema()["actions"][action],
        "required_inputs": ["action", "inputs"], "missing_inputs": ["inputs"],
        "input_template": plan_inputs,
        "next": {
            "ready_without_input": False,
            "argv": [*argv, "--dry-run"], "then_argv": [*argv, "--execute"],
            "plan_node": {"id": f"custom-metric-{action}-preview", "kind": "composite", "request": preview},
            "then_plan_node": {"id": f"custom-metric-{action}-execute", "kind": "composite", "request": {**preview, "mode": "execute"}},
            "call_count_after_discovery": 2,
        },
    }


def _base(query: str, action: str, selector: str) -> dict[str, Any]:
    descriptions = {
        "list": "读取当前 turbo confmetric 自定义指标目录，并交付可复制的 raw/Plan 输入。",
        "create": "创建带 GSDK marker 的自定义指标，创建后必须读回并可供 Multidim 查询引用。",
        "update": "更新 marker-or-owner 已验证的自定义指标，并逐字段读回定义。",
        "delete": "删除前重新读回 marker-or-owner，删除后证明指标 ID 已不存在。",
    }
    mutation_auth = (
        "Selection is read-only; preview and execute still require the governed user authorization flow.",
    )
    boundaries = {
        "list": (
            "只列目录，不创建、更新或删除自定义指标。",
            "不执行 Multidim 查询。",
        ),
        "create": (
            "自然语言永不自动写入。",
            *mutation_auth,
        ),
        "update": (
            "自然语言永不自动写入。",
            *mutation_auth,
        ),
        "delete": (
            "删除前重新读回 marker-or-owner，删除后证明指标 ID 已不存在。",
            *mutation_auth,
        ),
    }
    return {
        "selector": selector, "domain": "report", "description": descriptions[action],
        "boundaries": boundaries[action],
        "executable": True, "plan_executable": True,
        "natural_language_auto_execute": False, "offline": False,
        "network_called": False,
        "match": {
            "confidence": "strong", "coverage": 1.0,
            "exact_selector": affirmative_intent_text(query) == selector,
            "matched_terms": [action], "missing_terms": [],
        },
    }


__all__ = [
    "SELECTORS", "custom_metric_capability_inventory", "custom_metric_cards",
    "is_custom_metric_card",
]
