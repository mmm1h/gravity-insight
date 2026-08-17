"""Canonical Agent product card for caller-bound public App metadata."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any


APP_PUBLIC_INFO_SELECTOR = ".".join(("app", "app_info", "get"))
APP_PUBLIC_INFO_CAPABILITY: Mapping[str, Any] = {
    "kind": "operation",
    "selector": APP_PUBLIC_INFO_SELECTOR,
    "operation_id": APP_PUBLIC_INFO_SELECTOR,
    "domain": "app",
    "description": (
        "读取调用方提供的 App Store 或 Google Play 公开下载链接，返回已登记的公开 App 信息；"
        "当前账号 OneLink 目录明确为空，本产品不把空 OneLink 样本伪装成绑定。"
    ),
    "effect": "read",
    "executable": True,
    "plan_executable": True,
    "natural_language_auto_execute": False,
    "input_schema": {
        "url": {
            "type": "string",
            "required": True,
            "description": "Caller-supplied public App Store or Google Play URL.",
            "max_length": 4096,
        }
    },
    "required_inputs": ("url",),
    "missing_inputs": ["url"],
    "match": {
        "confidence": "strong",
        "coverage": 1.0,
        "matched_terms": ["public app-store information"],
        "missing_terms": [],
        "score": 100,
        "exact_selector": True,
    },
    "next": {
        "ready_without_input": False,
        "argv": ["gravity", "run", APP_PUBLIC_INFO_SELECTOR, "--input", "<json-object-or-file>"],
        "call_count_after_discovery": 1,
    },
}


def app_public_info_capability_inventory() -> tuple[dict[str, Any], ...]:
    """Return the single canonical card backed by the stable operation."""

    return (copy.deepcopy(dict(APP_PUBLIC_INFO_CAPABILITY)),)


__all__ = [
    "APP_PUBLIC_INFO_CAPABILITY",
    "APP_PUBLIC_INFO_SELECTOR",
    "app_public_info_capability_inventory",
]
