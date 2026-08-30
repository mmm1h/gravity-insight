"""Natural-language Agent discovery for Segment member rows."""

from __future__ import annotations

from collections.abc import Mapping
import re
from typing import Any

from .intent_text import affirmative_intent_text


SEGMENT_MEMBERS_NAME = "segment_members"
SEGMENT_MEMBERS_SELECTOR = f"composite:{SEGMENT_MEMBERS_NAME}"
_EXACT = frozenset({SEGMENT_MEMBERS_NAME, SEGMENT_MEMBERS_SELECTOR})
_WORDS = re.compile(r"[a-z0-9_]+", re.IGNORECASE)
_SUBJECTS = frozenset({"segment", "audience", "cohort"})
_MEMBERS = frozenset({"member", "members", "user", "users", "people"})
_ACTIONS = frozenset({"list", "show", "who", "export", "get"})
_AGGREGATES = frozenset({"count", "size", "share", "ratio", "history", "daily"})


SEGMENT_MEMBERS_CAPABILITY: Mapping[str, Any] = {
    "name": SEGMENT_MEMBERS_NAME,
    "domain": "analysis",
    "accepted_domains": ("analysis", "segment"),
    "aliases": (
        "segment member directory with per-user properties",
        "show users in an exact audience",
        "分群成员名单与逐人属性",
        "查看精确人群中的用户",
    ),
    "description": (
        "按精确 ID 或精确名称返回分群成员及逐人属性；固定字段直接选择，"
        "动态字段先从 live user-property metadata 发现，历史成员使用 segment_version_id。"
    ),
    "boundaries": (
        "不读取分群详情、历史版本或单日计算结果。",
        "不评估规则命中人数。",
    ),
    "required_inputs": ("app", "ref"),
    "input_schema": {
        "app": {"type": "string|integer", "required": True, "nullable": False},
        "ref": {"type": "string|integer", "required": True, "nullable": False},
        "fields": {
            "type": "array[string]", "required": False,
            "description": "Registered fixed fields or live user-property names.",
        },
        "segment_version_id": {
            "type": "string|integer", "required": False,
            "description": "Optional historical Segment version id.",
        },
    },
}


def segment_members_query(query: str) -> bool:
    selected = affirmative_intent_text(query)
    if selected in _EXACT:
        return True
    if selected.isascii():
        words = frozenset(_WORDS.findall(selected))
        return (
            bool(words & _SUBJECTS)
            and bool(words & _MEMBERS)
            and bool(words & _ACTIONS)
            and not bool(words & _AGGREGATES)
        )
    compact = "".join(selected.split())
    full = "".join(query.strip().casefold().split())
    return _chinese_member_intent(compact, full) and not any(
        term in compact for term in ("人数", "规模", "占比", "比例", "历史", "单日")
    )


def segment_members_intent(query: str) -> bool:
    selected = affirmative_intent_text(query)
    if selected in _EXACT:
        return True
    if selected.isascii():
        words = frozenset(_WORDS.findall(selected))
        return bool(words & _SUBJECTS) and bool(words & _MEMBERS) and bool(words & _ACTIONS)
    compact = "".join(selected.split())
    full = "".join(query.strip().casefold().split())
    return _chinese_member_intent(compact, full)


def _chinese_member_intent(compact: str, full: str) -> bool:
    subject = any(term in compact for term in ("分群", "人群", "受众"))
    contextual_subject = any(term in full for term in ("分群", "人群", "受众"))
    members = any(term in compact for term in ("成员", "名单", "哪些人", "都有谁"))
    return subject and members or "成员名单" in compact and contextual_subject


def segment_members_plan_request(card: Mapping[str, Any]) -> dict[str, Any]:
    request: dict[str, Any] = {
        "name": SEGMENT_MEMBERS_NAME,
        "app": card.get("app", "<workspace-app-alias-or-positive-id>"),
        "ref": card.get("ref", "<segment-id-or-exact-name>"),
    }
    for field in ("fields", "segment_version_id"):
        if field in card:
            request[field] = card[field]
    return request


__all__ = [
    "SEGMENT_MEMBERS_CAPABILITY",
    "SEGMENT_MEMBERS_NAME",
    "segment_members_intent",
    "segment_members_plan_request",
    "segment_members_query",
]
