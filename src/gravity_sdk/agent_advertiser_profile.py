"""Strict Agent handoff for the Bytedance advertiser profile product."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any


ADVERTISER_PROFILE_NAME = "advertiser_profile"
ADVERTISER_PROFILE_SELECTOR = f"composite:{ADVERTISER_PROFILE_NAME}"
ADVERTISER_PROFILE_REQUIRED_INPUTS = ("start", "end")
_EXACT = frozenset({
    ADVERTISER_PROFILE_NAME,
    ADVERTISER_PROFILE_SELECTOR,
    "advertiser profile",
    "advertiser account profile",
    "advertiser performance",
    "advertiser performance profile",
    "bytedance advertiser profile",
    "巨量广告主画像",
    "巨量广告主账户",
    "巨量广告主表现",
    "广告主账户画像",
})
_BLOCKED = frozenset({
    "cross", "platform", "metric", "metrics", "ranking", "strategy",
    "export", "write", "create", "update", "delete", "material",
})


ADVERTISER_PROFILE_CAPABILITY: Mapping[str, Any] = {
    "name": ADVERTISER_PROFILE_NAME,
    "domain": "promotion",
    "accepted_domains": ("promotion", "report"),
    "aliases": (
        "read governed Bytedance advertiser account profiles",
        "read advertiser spend balance budget mode and status",
        "读取巨量广告主消耗余额预算模式和状态",
        "读取巨量广告主账户画像",
    ),
    "description": (
        "按显式日期读取巨量广告主消耗、余额、预算模式和状态；"
        "这是账户目录，不属于跨平台推广表现。"
    ),
    "required_inputs": ADVERTISER_PROFILE_REQUIRED_INPUTS,
    "input_schema": {
        "start": {
            "type": "string", "format": "date", "required": True,
            "nullable": False,
        },
        "end": {
            "type": "string", "format": "date", "required": True,
            "nullable": False,
        },
    },
    "plan_node_limits": {"max_pages": 1_000, "max_items": 100_000},
}


def advertiser_profile_query(query: str) -> bool:
    selected = " ".join(str(query or "").strip().casefold().split())
    if selected in _EXACT:
        return True
    if not selected:
        return False
    words = frozenset(re.findall(r"[a-z0-9_]+", selected))
    if words & _BLOCKED:
        return False
    english = "advertiser" in words and bool(
        words & {"account", "accounts", "performance", "profile", "profiles"}
    )
    chinese = "广告主" in selected and any(
        term in selected
        for term in ("画像", "账户", "账号", "余额", "预算", "状态", "表现", "消耗")
    )
    return english or chinese


def advertiser_profile_blocks_operation_fallback(query: str) -> bool:
    selected = " ".join(str(query or "").strip().casefold().split())
    words = frozenset(re.findall(r"[a-z0-9_]+", selected))
    return (
        selected in _EXACT
        or "advertiser" in words and bool(
            words & {"account", "performance", "profile"}
        )
        or "广告主" in selected and any(
            term in selected
            for term in ("画像", "账户", "账号", "余额", "预算", "状态", "表现", "消耗")
        )
    )


def advertiser_profile_plan_request(_card: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "name": ADVERTISER_PROFILE_NAME,
        "start": "<start:YYYY-MM-DD>",
        "end": "<end:YYYY-MM-DD>",
    }


__all__ = [
    "ADVERTISER_PROFILE_CAPABILITY",
    "ADVERTISER_PROFILE_NAME",
    "ADVERTISER_PROFILE_REQUIRED_INPUTS",
    "ADVERTISER_PROFILE_SELECTOR",
    "advertiser_profile_blocks_operation_fallback",
    "advertiser_profile_plan_request",
    "advertiser_profile_query",
]
