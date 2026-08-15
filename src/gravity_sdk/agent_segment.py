"""Intent-first Agent handoff for compact Segment Rule Spec v1."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
import re
from typing import Any

from .find import query_match
from .agent_export import is_authoritative_export_card
from .agent_intent_text import affirmative_intent_text
from .segment_spec_schema import segment_rule_spec_schema


_SELECTOR = "analysis.segment.rule.spec"
_MUTATION_SELECTOR = "analysis.segment.mutation"
_COMPOSITE = "segment_evaluate"
_ASCII_WORD = re.compile(r"[a-z0-9_]+", re.IGNORECASE)
_ENGLISH_SUBJECTS = frozenset({"segment", "audience", "cohort", "user", "users"})
_ENGLISH_RULES = frozenset({"rule", "rules", "condition", "conditions"})
_ENGLISH_RESULTS = frozenset(
    {"count", "population", "size", "percent", "percentage", "ratio", "share"}
)
_ENGLISH_ACTIONS = frozenset(
    {
        "evaluate", "evaluation", "estimate", "estimation", "predict",
        "prediction", "match", "matches",
    }
)
_CHINESE_SUBJECTS = ("人群", "受众", "分群")
_CHINESE_RULES = ("规则", "条件")
_CHINESE_RESULTS = (
    "人数", "多少人", "规模", "占比", "比例", "命中", "覆盖", "占全部",
)
_CHINESE_ACTIONS = ("评估", "预估", "估算", "测算", "圈中")
_EXACT_SELECTORS = frozenset(
    {_SELECTOR, f"composite:{_COMPOSITE}", _COMPOSITE}
)
_CONTRACT = segment_rule_spec_schema()


def segment_rule_spec_cards(
    query: str,
    *,
    domain: str | None,
    platform: str | None,
) -> list[dict[str, Any]]:
    """Return one card only for an explicit rule-evaluation intent."""

    if platform is not None or domain not in {None, "analysis", "segment"}:
        return []
    if not _requests_segment_evaluation(query):
        return []
    return [_segment_rule_card(query)]


def segment_mutation_cards(
    query: str,
    *,
    domain: str | None,
    platform: str | None,
) -> list[dict[str, Any]]:
    """Return a direct confirmation handoff, never an executable Plan node."""

    if platform is not None or domain not in {None, "analysis", "segment"}:
        return []
    action = _mutation_action(query)
    if action is None:
        return []
    return [_segment_mutation_card(query, action)]


def segment_evaluate_intent(query: str) -> bool:
    """Return positive Segment Evaluate evidence for central arbitration."""

    return _requests_segment_evaluation(query)


def segment_mutation_intent(query: str) -> bool:
    return _mutation_action(query) is not None


def is_authoritative_direct_card(card: Mapping[str, Any]) -> bool:
    """Identify direct cards that must suppress low-level operation fallback."""

    return is_authoritative_export_card(card) or (
        card.get("kind") == "segment_rule_spec"
        and card.get("selector") == _SELECTOR
        and card.get("composite") == _COMPOSITE
        and card.get("natural_language_auto_execute") is False
    ) or (
        card.get("kind") == "segment_mutation"
        and card.get("selector") == _MUTATION_SELECTOR
        and card.get("plan_executable") is False
        and card.get("natural_language_auto_execute") is False
    )


def segment_rule_plan_request(card: Mapping[str, Any]) -> dict[str, Any]:
    """Render an explicit, copyable composite request with unfilled slots."""

    template = card.get("input_template")
    values = template if isinstance(template, Mapping) else {}
    return {
        "name": _COMPOSITE,
        "app": card.get("app", values.get("app")),
        "spec": card.get("spec", values.get("spec")),
    }


def _requests_segment_evaluation(query: str) -> bool:
    selected = affirmative_intent_text(query)
    if selected in _EXACT_SELECTORS:
        return True
    if re.search(r"[\u3400-\u9fff]", selected) is None:
        words = frozenset(_ASCII_WORD.findall(selected))
        return all(
            words & group
            for group in (
                _ENGLISH_SUBJECTS,
                _ENGLISH_RULES,
                _ENGLISH_RESULTS,
                _ENGLISH_ACTIONS,
            )
        )
    compact = "".join(selected.split())
    full = "".join(query.strip().casefold().split())
    if "规则" in compact and "覆盖" in compact and any(
        term in compact for term in _CHINESE_ACTIONS
    ) and any(term in full for term in _CHINESE_SUBJECTS):
        return True
    return all(
        any(term in compact for term in group)
        for group in (
            _CHINESE_SUBJECTS,
            _CHINESE_RULES,
            _CHINESE_RESULTS,
            _CHINESE_ACTIONS,
        )
    )


def _mutation_action(query: str) -> str | None:
    selected = affirmative_intent_text(query)
    if selected in {_MUTATION_SELECTOR, "segment_mutation"}:
        return "create-from-analysis"
    words = frozenset(_ASCII_WORD.findall(selected))
    has_subject = bool(words & _ENGLISH_SUBJECTS) or any(
        term in selected for term in ("分群", "人群包", "受众")
    )
    if not has_subject:
        return None
    actions = (
        ("delete", ("delete", "remove", "删除")),
        ("refresh", ("refresh", "recalculate", "刷新", "重算")),
        ("update", ("update", "rename", "edit", "更新", "改名", "修改")),
        (
            "create-from-analysis",
            ("create", "save", "persist", "创建", "保存", "存成", "建成", "圈成"),
        ),
    )
    for action, terms in actions:
        if any(term in selected for term in terms):
            return action
    return None


def _segment_mutation_card(query: str, action: str) -> dict[str, Any]:
    command = {
        "create-from-analysis": [
            "create-from-analysis", "--spec", "<funnel-spec.json>", "--app",
            "<workspace-app>", "--name", "<segment-name>", "--step", "<zero-based-step>",
            "--loss",
        ],
        "update": ["update", "--segment-id", "<segment-id>", "--name", "<segment-name>"],
        "refresh": ["refresh", "--segment-id", "<segment-id>"],
        "delete": ["delete", "--segment-id", "<segment-id>"],
    }[action]
    base = ["gravity", "analysis", "segment", *command]
    return {
        "kind": "segment_mutation",
        "selector": _MUTATION_SELECTOR,
        "domain": "analysis",
        "description": (
            "分群写操作只返回显式命令交接：先零网络 dry-run，再由调用方确认执行；"
            "自然语言永不自动发送写请求。"
        ),
        "effect": "mutation",
        "mutation_action": action,
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
            "explicit_inputs": "<fill from authoritative IDs/spec; do not copy values from natural language>",
        },
        "match": _intent_match(query),
        "next": {
            "ready_without_input": False,
            "argv": [*base, "--dry-run"],
            "then_argv": [*base, "--execute"],
            "call_count_after_discovery": 2,
        },
    }


def _segment_rule_card(query: str) -> dict[str, Any]:
    contract = _CONTRACT
    schema = deepcopy(contract["spec_schema"])
    definitions = deepcopy(contract["definitions"])
    required = ["app", "spec"]
    return {
        "kind": "segment_rule_spec",
        "selector": _SELECTOR,
        "compiler": "segment_rule",
        "composite": _COMPOSITE,
        "operation_id": str(contract["operation_id"]),
        "domain": "analysis",
        "description": (
            "使用紧凑 Segment Rule Spec 评估规则命中人数与占比；"
            "自然语言只发现能力，不生成规则字段或值。"
        ),
        "effect": "read",
        "executable": True,
        "compiler_callable": True,
        "plan_executable": True,
        "natural_language_auto_execute": False,
        "execution_mode": "plan_after_explicit_segment_rule_spec",
        "offline": True,
        "network_called": False,
        "input_schema": {
            "app": {
                "type": "string|integer",
                "required": True,
                "nullable": False,
            },
            "spec": {
                "type": "object",
                "required": True,
                "nullable": False,
                "schema_version": contract["schema_version"],
                "schema": schema,
                "definitions": definitions,
            },
        },
        "required_inputs": required,
        "missing_inputs": list(required),
        "input_template": _input_template(schema),
        "spec_schema_version": contract["schema_version"],
        "result_fields": ["part", "percent", "total"],
        "metadata_validation": contract["handoff"]["metadata_validation"],
        "binding_targets": ["/app"],
        "match": _intent_match(query),
        "next": {
            "ready_without_input": False,
            "argv": ["gravity", "plan", "run", "--input", "<plan.json>"],
            "schema_argv": [
                "gravity",
                "analysis",
                "segment",
                "evaluate",
                "--spec-schema",
            ],
            "call_count_after_discovery": 1,
        },
    }


def _input_template(schema: Mapping[str, Any]) -> dict[str, Any]:
    properties = schema.get("properties", {})
    required = schema.get("required", [])
    spec = {
        str(name): _placeholder(str(name), properties.get(name, {}))
        for name in required
    }
    for name in ("property_rules", "event_rules"):
        spec[name] = {"logic": "AND", "groups": []}
    return {
        "app": "<workspace-app-alias-or-positive-id>",
        "spec": spec,
    }


def _placeholder(name: str, field: Any) -> Any:
    if name in {"property_rules", "event_rules"}:
        return {"logic": "AND", "groups": f"<{name}:array>"}
    selected_type = field.get("type") if isinstance(field, Mapping) else "value"
    return f"<{name}:{selected_type or 'value'}>"


def _intent_match(query: str) -> dict[str, Any]:
    selected = query.strip().casefold()
    exact = selected in _EXACT_SELECTORS
    match = query_match(
        query,
        _SELECTOR,
        f"composite:{_COMPOSITE}",
        "segment rule population estimate",
        "audience rule percentage evaluation",
        "分群规则预估人数",
        "受众规则占比评估",
        score=100,
    )
    return {
        **match,
        "confidence": "strong",
        "coverage": 1.0,
        "matched_terms": [_SELECTOR if exact else "segment rule evaluation"],
        "missing_terms": [],
        "score": 100,
        "intent_only": not exact,
        "exact_selector": exact,
    }


__all__ = [
    "is_authoritative_direct_card",
    "segment_evaluate_intent",
    "segment_mutation_cards",
    "segment_mutation_intent",
    "segment_rule_plan_request",
    "segment_rule_spec_cards",
]
