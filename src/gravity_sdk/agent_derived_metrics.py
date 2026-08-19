"""Agent boundary for generic arithmetic and caller-owned metric bindings."""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping, Sequence
from typing import Any

from .agent_gap import unavailable_gap
from .derived_metrics import SPEC_SCHEMA_VERSION
from .workspace_semantic_context import SCHEMA_VERSION


DERIVED_METRICS_NAME = "derived_metrics"
DERIVED_METRICS_CAPABILITY: Mapping[str, Any] = {
    "name": DERIVED_METRICS_NAME,
    "domain": "analysis",
    "aliases": (
        "derived metrics",
        "derived arithmetic",
        "metric reconciliation",
        "派生指标",
        "算术派生",
        "集合对账",
    ),
    "description": (
        "对已有结果 envelope 执行调用方绑定的比率、占比、变化和声明集合对账；"
        "SDK 不提供任何业务公式；不要用于用同一 Analysis Spec 重跑两个时期，"
        "后者属于 Analysis Query 跨期比较。"
    ),
    "boundaries": (
        "SDK 不提供任何业务公式。",
        "不要用于用同一 Analysis Spec 重跑两个时期，后者属于 Analysis Query 跨期比较。",
    ),
    "required_inputs": ("source", "spec"),
    "input_schema": {
        "source": {"type": "object", "required": True, "nullable": False},
        "spec": {
            "type": "object",
            "required": True,
            "nullable": False,
            "schema_version": SPEC_SCHEMA_VERSION,
        },
    },
}

_ENGLISH_INTENT = re.compile(r"\b(?:ratio|rate|percentage|percent|share)\b", re.I)
_CHINESE_RATE = re.compile(r"[\u3400-\u9fff]{2,16}率(?:是多少|多少|怎么计算|如何计算|怎么算|吗)?")


def derived_metrics_product_query(query: str) -> bool:
    selected = " ".join(query.strip().casefold().split())
    return selected in {
        DERIVED_METRICS_NAME,
        f"composite:{DERIVED_METRICS_NAME}",
        "derived metrics",
        "derived arithmetic",
        "metric reconciliation",
        "派生指标",
        "算术派生",
        "集合对账",
    }


def derived_metric_intent(query: str) -> bool:
    """Recognize a formula-shaped question without inferring its formula."""

    selected = " ".join(query.strip().casefold().split())
    return bool(
        _ENGLISH_INTENT.search(selected)
        or any(term in selected for term in ("占比", "比率", "比例", "变化率", "增长率", "覆盖率"))
        or _CHINESE_RATE.search(selected)
    )


def derived_metric_gap(query: str) -> dict[str, Any]:
    return unavailable_gap(
        query,
        code="DERIVED_METRIC_BINDING_REQUIRED",
        journey="derived_metrics",
        reason=(
            "the SDK can execute arithmetic but the caller has not declared which "
            "columns, alignment keys, and result name define this metric"
        ),
        next_action=(
            "Declare one [[semantic_context.derived_metrics]] binding in gravity.toml, "
            "or supply a gravity.derived-metrics-spec.v1 request to `gravity derive --input`."
        ),
        argv=["gravity", "derive", "--input", "<request.json>"],
    )


def semantic_derived_card(
    declaration: Any,
    phrases: Sequence[str],
) -> dict[str, Any]:
    """Build an executable card only from the caller's validated declaration."""

    matched = list(phrases)
    return {
        "kind": "composite",
        "selector": f"composite:{DERIVED_METRICS_NAME}",
        "composite": DERIVED_METRICS_NAME,
        "domain": "analysis",
        "description": declaration.description or matched[0],
        "description_origin": "caller_workspace",
        "effect": "read",
        "executable": True,
        "plan_executable": True,
        "natural_language_auto_execute": False,
        "spec": copy.deepcopy(dict(declaration.spec)),
        "input_schema": copy.deepcopy(DERIVED_METRICS_CAPABILITY["input_schema"]),
        "required_inputs": ["source"],
        "match": {
            "confidence": "strong",
            "coverage": 1.0,
            "matched_terms": matched,
            "missing_terms": [],
            "score": 0,
            "exact_selector": False,
        },
        "semantic_context": {
            "schema_version": SCHEMA_VERSION,
            "match_kind": "derived_metric",
            "declaration": declaration.name,
            "matched_phrases": matched,
        },
        "next": {
            "ready_without_input": False,
            "argv": ["gravity", "plan", "run", "--input", "<plan.json>"],
        },
    }


def derived_metrics_plan_request(card: Mapping[str, Any]) -> dict[str, Any]:
    request: dict[str, Any] = {"name": DERIVED_METRICS_NAME}
    if isinstance(card.get("spec"), Mapping):
        request["spec"] = copy.deepcopy(dict(card["spec"]))
    return request


__all__ = [
    "DERIVED_METRICS_CAPABILITY",
    "DERIVED_METRICS_NAME",
    "derived_metric_gap",
    "derived_metric_intent",
    "derived_metrics_plan_request",
    "derived_metrics_product_query",
    "semantic_derived_card",
]
