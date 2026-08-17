"""Canonical Agent product card for D28 monetization aggregate reads."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any


MONETIZATION_AGGREGATE_SELECTOR = ".".join(("report", "get", "query"))
MONETIZATION_AGGREGATE_CAPABILITY: Mapping[str, Any] = {
    "kind": "operation",
    "selector": MONETIZATION_AGGREGATE_SELECTOR,
    "operation_id": MONETIZATION_AGGREGATE_SELECTOR,
    "domain": "report",
    "description": (
        "按变现平台、广告位和日期汇总已观察变现指标；App 由调用方以 EQUALS 过滤提供，"
        "服务端一次返回完整 list 与 page_info.total，不接受 page/page_size。"
    ),
    "effect": "read",
    "executable": True,
    "plan_executable": True,
    "natural_language_auto_execute": False,
    "input_schema": {
        "date_list": {
            "type": "array",
            "item_type": "string",
            "required": True,
            "min_items": 2,
            "max_items": 2,
            "description": "Closed [start, end] YYYY-MM-DD window.",
        },
        "metrics_list": {
            "type": "array",
            "item_type": "string",
            "required": True,
            "min_items": 1,
            "description": "Observed monetization metric names.",
        },
        "filters": {
            "type": "array",
            "item_type": "object",
            "required": False,
            "description": "Must include app_id EQUALS one catalog App.",
        },
    },
    "required_inputs": ("date_list", "metrics_list"),
    "missing_inputs": ["date_list", "metrics_list"],
    "match": {
        "confidence": "strong",
        "coverage": 1.0,
        "matched_terms": ["monetization platform and ad placement"],
        "missing_terms": [],
        "score": 100,
        "exact_selector": True,
    },
    "next": {
        "ready_without_input": False,
        "argv": [
            "gravity",
            "run",
            MONETIZATION_AGGREGATE_SELECTOR,
            "--input",
            "<json-object-or-file>",
        ],
        "call_count_after_discovery": 1,
    },
}


def monetization_aggregate_capability_inventory() -> tuple[dict[str, Any], ...]:
    """Return the single canonical card backed by the stable operation."""

    return (copy.deepcopy(dict(MONETIZATION_AGGREGATE_CAPABILITY)),)


__all__ = [
    "MONETIZATION_AGGREGATE_CAPABILITY",
    "MONETIZATION_AGGREGATE_SELECTOR",
    "monetization_aggregate_capability_inventory",
]
