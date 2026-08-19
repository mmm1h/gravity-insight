"""Value-free Agent card for the governed semantic composition contract."""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping
from typing import Any

from .agent_intent_text import affirmative_intent_text
from .semantic_compose import (
    SEMANTIC_COMPOSE_INPUT_SCHEMA_VERSION,
    SEMANTIC_COMPOSE_NAME,
    semantic_compose_input_schema,
)


SEMANTIC_COMPOSE_SELECTOR = f"composite:{SEMANTIC_COMPOSE_NAME}"
_EXACT = frozenset(
    {
        SEMANTIC_COMPOSE_NAME,
        SEMANTIC_COMPOSE_SELECTOR,
        "governed semantic composition",
        "registered semantic query",
        "semantic metric composition",
        "受治理语义组合",
        "已登记语义组合查询",
        "指标维度过滤粒度组合",
    }
)
_ENGLISH_REQUIRED = (
    frozenset({"semantic"}),
    frozenset({"compose", "composition", "query"}),
    frozenset({"governed", "registered"}),
)


SEMANTIC_COMPOSE_CAPABILITY: Mapping[str, Any] = {
    "name": SEMANTIC_COMPOSE_NAME,
    "domain": "report",
    "aliases": tuple(sorted(_EXACT - {SEMANTIC_COMPOSE_NAME, SEMANTIC_COMPOSE_SELECTOR})),
    "description": (
        "只引用已登记且版本化的指标、维度、过滤器、时间粒度和允许连接，"
        "确定性编译到现有 Multidim 产品；返回定义版本、实际成员、生成查询、"
        "验证结果和 allowed_claims，不接受 SQL 文本。"
    ),
    "boundaries": (
        "只引用已登记且版本化的指标、维度、过滤器、时间粒度和允许连接，确定性编译到现有 Multidim 产品。",
        "返回定义版本、实际成员、生成查询、验证结果和 allowed_claims，不接受 SQL 文本。",
    ),
    "required_inputs": ("app", "inputs"),
    "input_schema": {
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
            "machine_schema": semantic_compose_input_schema(),
        },
    },
}


def semantic_compose_query(query: str) -> bool:
    """Recognize only an explicit request for the governed composition product."""

    selected = affirmative_intent_text(query)
    if selected in _EXACT:
        return True
    if selected.isascii():
        words = frozenset(re.findall(r"[a-z0-9_]+", selected))
        return all(bool(words & required) for required in _ENGLISH_REQUIRED)
    compact = "".join(selected.split())
    return (
        "语义" in compact
        and any(term in compact for term in ("组合", "查询"))
        and any(term in compact for term in ("受治理", "已登记", "版本"))
        and not any(term in compact for term in ("sql", "写入", "创建", "删除"))
    )


def semantic_compose_input_template() -> dict[str, Any]:
    """Expose slots without selecting a definition or member for the caller."""

    reference = {
        "definition_id": "<registered-definition-id>",
        "version": "<registered-positive-version>",
    }
    return {
        "app": "<workspace-app-alias-or-positive-id>",
        "inputs": {
            "definition": copy.deepcopy(reference),
            "window": {"start": "<start:YYYY-MM-DD>", "end": "<end:YYYY-MM-DD>"},
            "metric": copy.deepcopy(reference),
            "dimensions": [],
            "filters": [],
            "grain": copy.deepcopy(reference),
            "joins": [],
        },
    }


def semantic_compose_plan_request(card: Mapping[str, Any]) -> dict[str, Any]:
    template = semantic_compose_input_template()
    return {
        "name": SEMANTIC_COMPOSE_NAME,
        "input_schema_version": SEMANTIC_COMPOSE_INPUT_SCHEMA_VERSION,
        "app": card.get("app", template["app"]),
        "inputs": copy.deepcopy(card.get("inputs", template["inputs"])),
    }


__all__ = [
    "SEMANTIC_COMPOSE_CAPABILITY",
    "SEMANTIC_COMPOSE_SELECTOR",
    "semantic_compose_input_template",
    "semantic_compose_plan_request",
    "semantic_compose_query",
]
