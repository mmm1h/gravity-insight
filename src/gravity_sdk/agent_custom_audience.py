"""Strict Agent handoff for custom-audience coverage and status."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any


CUSTOM_AUDIENCE_NAME = "custom_audience"
CUSTOM_AUDIENCE_SELECTOR = f"composite:{CUSTOM_AUDIENCE_NAME}"
_EXACT = frozenset({
    CUSTOM_AUDIENCE_NAME,
    CUSTOM_AUDIENCE_SELECTOR,
    "custom audience coverage status",
    "custom audience coverage and status",
    "自定义人群覆盖与状态",
    "查看自定义人群覆盖与状态",
    "可投人群覆盖与状态",
})


CUSTOM_AUDIENCE_CAPABILITY: Mapping[str, Any] = {
    "name": CUSTOM_AUDIENCE_NAME,
    "domain": "promotion",
    "aliases": (
        "custom audience coverage status",
        "custom audience coverage and status",
        "自定义人群覆盖与状态",
        "查看自定义人群覆盖与状态",
        "可投人群覆盖与状态",
    ),
    "description": "完整读取可投自定义人群的覆盖数、上传数、来源和状态。",
    "required_inputs": (),
    "input_schema": {},
}


def custom_audience_query(query: str) -> bool:
    selected = " ".join(query.strip().casefold().split())
    if selected in _EXACT:
        return True
    if not selected:
        return False
    words = frozenset(re.findall(r"[a-z0-9_]+", selected))
    if words & {"not", "without", "exclude", "export", "create", "update", "delete"}:
        return False
    english = (
        "custom" in words
        and "audience" in words
        and bool(words & {
            "coverage", "cover", "covers", "covered", "upload", "source",
            "status", "ready", "syncing", "failed",
        })
    )
    chinese = bool(
        ("自定义人群" in selected or "可投人群" in selected)
        and any(term in selected for term in ("覆盖", "上传", "来源", "状态"))
    )
    return english or chinese


def custom_audience_intent(query: str) -> bool:
    return custom_audience_query(query)


def custom_audience_plan_request(_card: Mapping[str, Any]) -> dict[str, str]:
    return {"name": CUSTOM_AUDIENCE_NAME}


__all__ = [
    "CUSTOM_AUDIENCE_CAPABILITY",
    "CUSTOM_AUDIENCE_NAME",
    "CUSTOM_AUDIENCE_SELECTOR",
    "custom_audience_intent",
    "custom_audience_plan_request",
    "custom_audience_query",
]
