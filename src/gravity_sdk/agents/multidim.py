"""Strict, value-free Agent handoff for governed Multidim queries."""

from __future__ import annotations

import copy
from collections.abc import Mapping
import re
from typing import Any

from ..multidim_product import MULTIDIM_INPUT_SCHEMA_VERSION, multidim_input_schema
from .intent_text import affirmative_intent_text
from ..multidim_contract import (
    MULTIDIM_COHORT_HORIZON_GAP_CODE,
    multidim_multi_key_contract,
)


MULTIDIM_NAME = "multidim"
MULTIDIM_SELECTOR = f"composite:{MULTIDIM_NAME}"

_EXACT_INTENTS = frozenset(
    {
        MULTIDIM_NAME,
        MULTIDIM_SELECTOR,
        "multi dimension",
        "multi dimensions",
        "multidimensional report",
        "cross dimension report",
        "多维查询",
        "多维分析",
        "多维报表",
        "交叉维度查询",
    }
)
_ASCII_WORD = re.compile(r"[a-z0-9_]+", re.IGNORECASE)
_ENGLISH_SUBJECTS = frozenset({"multidim", "multidimensional"})
_ENGLISH_ACTIONS = frozenset(
    {"query", "report", "analysis", "total", "totals"}
)
_ENGLISH_BLOCKED = frozenset(
    {
        "template", "templates", "layout", "layouts", "favourite", "favourites",
        "favorite", "favorites", "permission", "permissions", "member", "members",
        "create", "update", "delete",
    }
)
_CHINESE_SUBJECTS = ("多维", "多个维度", "交叉维度", "维度交叉", "物理维度")
_CHINESE_ACTIONS = ("查询", "报表", "分析", "统计", "合计", "读取")
_CHINESE_BLOCKED = (
    "模板", "布局", "收藏", "权限", "成员", "创建", "更新", "删除",
)
_HORIZON_DAY = re.compile(
    r"(?<![a-z0-9_])d\s*([0-9]{1,4})(?![a-z0-9_])|"
    r"(?<![a-z0-9_])([0-9]{1,4})\s*(?:days?|天)(?![a-z0-9_])",
    re.IGNORECASE,
)
_MULTI_KEY_CONTRACT = multidim_multi_key_contract()


def _agent_input_schema() -> dict[str, Any]:
    raw = multidim_input_schema()
    return {
        "app": {
            "type": "string|integer",
            "required": True,
            "nullable": False,
            "description": "Workspace App alias or positive App id.",
        },
        "inputs": {
            "type": "object",
            "required": True,
            "nullable": False,
            "machine_schema": copy.deepcopy(raw),
        },
        "include_total": {
            "type": "boolean", "required": False, "nullable": False, "default": False,
        },
        "read_all": {
            "type": "boolean", "required": False, "nullable": False, "default": False,
        },
    }


MULTIDIM_CAPABILITY: Mapping[str, Any] = {
    "name": MULTIDIM_NAME,
    "domain": "report",
    "aliases": (
        "run a governed multidimensional report query",
        "query registered metrics across dimensions",
        "执行受治理的多维报表查询",
        "按已登记指标和维度查询多维报表",
    ),
    "description": (
        "使用公开的闭合 Multidim 物理输入合同执行多维报表查询，可显式请求合计或全量分页；"
        "调用方填写 App、指标、维度、日期和筛选，Agent 不推断任何业务值。"
    ),
    "boundaries": (
        "调用方填写 App、指标、维度、日期和筛选，Agent 不推断任何业务值。",
        "不接受 SQL 文本，也不引用语义组合成员名。",
        (
            "Cohort observation days must use the compiled Multidim "
            f"multi_keys item enum ({_MULTI_KEY_CONTRACT.allowed_text}); "
            f"post-D{_MULTI_KEY_CONTRACT.maximum} requests are a registered gap."
        ),
    ),
    "required_inputs": ("app", "inputs"),
    "input_schema": _agent_input_schema(),
}


def multidim_query(query: str) -> bool:
    """Recognize only explicit Multidim product intent, never adjacent Web concepts."""

    selected = affirmative_intent_text(query)
    from .intent_routing import adjacent_product_conflict

    if selected in _EXACT_INTENTS:
        return True
    if adjacent_product_conflict("multidim", selected):
        return False
    return multidim_intent(selected)


def multidim_intent(query: str) -> bool:
    """Return positive Multidim evidence without adjacent-product exclusions."""

    selected = affirmative_intent_text(query)
    if selected in _EXACT_INTENTS:
        return True
    if selected.isascii():
        return _english_multidim_intent(selected)
    compact = "".join(selected.split())
    return (
        any(term in compact for term in _CHINESE_SUBJECTS)
        and any(term in compact for term in _CHINESE_ACTIONS)
        and not any(term in compact for term in _CHINESE_BLOCKED)
    )


def unavailable_multidim_gap(query: str) -> dict[str, Any] | None:
    """Recognize explicit post-contract Multidim cohort horizon requests."""

    selected = affirmative_intent_text(query)
    if not multidim_intent(selected):
        return None
    requested = [
        int(match.group(1) or match.group(2))
        for match in _HORIZON_DAY.finditer(selected)
    ]
    contract = multidim_multi_key_contract()
    if not requested or max(requested) <= contract.maximum:
        return None
    from .gap import unavailable_gap

    return unavailable_gap(
        query,
        code=MULTIDIM_COHORT_HORIZON_GAP_CODE,
        journey="multidim_cohort_horizon",
        reason=contract.reason,
        next_action=contract.next_action,
    )


def _english_multidim_intent(selected: str) -> bool:
    if " " not in selected and "." in selected:
        return False
    words = frozenset(_ASCII_WORD.findall(selected))
    dimensions = {"dimension", "dimensions", "dimensional"}
    has_subject = bool(words & _ENGLISH_SUBJECTS) or bool(
        words & {"multi", "cross", "multiple"}
        and words & dimensions
    )
    return (
        has_subject
        and bool(words & _ENGLISH_ACTIONS)
        and not bool(words & _ENGLISH_BLOCKED)
    )


def multidim_input_template() -> dict[str, Any]:
    """Return literal slots and neutral defaults without selecting query semantics."""

    return {
        "app": "<workspace-app-alias-or-positive-id>",
        "inputs": {
            "date_list": ["<start:YYYY-MM-DD>", "<end:YYYY-MM-DD>"],
            "time_dims": "<hour|day|week|month|total>",
            "metrics_list": ["<registered-metric-name>"],
            "custom_metrics_list": [],
            "data_dims": [],
            "relate_dims": [],
            "filters": [],
        },
        "include_total": False,
        "read_all": False,
    }


def multidim_plan_request(card: Mapping[str, Any]) -> dict[str, Any]:
    """Build a mechanically fillable request; discovery never supplies business values."""

    template = multidim_input_template()
    return {
        "name": MULTIDIM_NAME,
        "input_schema_version": MULTIDIM_INPUT_SCHEMA_VERSION,
        "app": card.get("app", template["app"]),
        "inputs": copy.deepcopy(card.get("inputs", template["inputs"])),
        "include_total": card.get("include_total", False),
        "read_all": card.get("read_all", False),
    }


__all__ = [
    "MULTIDIM_CAPABILITY",
    "MULTIDIM_NAME",
    "multidim_input_template",
    "multidim_intent",
    "multidim_plan_request",
    "multidim_query",
    "unavailable_multidim_gap",
]
