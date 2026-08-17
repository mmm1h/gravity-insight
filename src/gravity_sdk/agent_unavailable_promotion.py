"""Natural-language gaps owned by unavailable promotion/material journeys."""

from __future__ import annotations

import re
from typing import Any

from .agent_gap import unavailable_gap
from .agent_intent_text import affirmative_intent_text


def unavailable_promotion_gap(query: str) -> dict[str, Any] | None:
    selected = affirmative_intent_text(query)
    words = frozenset(re.findall(r"[a-z0-9_]+", selected))
    if _non_bytedance_hierarchy(selected, words):
        return unavailable_gap(
            query, code="NON_BYTEDANCE_HIERARCHY_PARENT_MISSING",
            journey="non_bytedance_campaign_group_creative",
            reason=(
                "Tencent advertiser, ad-group filter and medium ad-group roots are now non-empty, "
                "but campaign/ad-group/creative performance drafts still lack confirmed-read "
                "semantics and cannot be probed or promoted."
            ),
            next_action=(
                "Review frontend control flow for Tencent campaign/ad-group/ad report POSTs, "
                "add a confirmed_read record if they are reads, then probe one page with the "
                "already-returned Tencent parent IDs; do not treat Kuaishou company IDs as delivery rows."
            ),
        )
    if _platform_specific_creatives(selected, words):
        return unavailable_gap(
            query, code="PLATFORM_SPECIFIC_CREATIVE_CONTRACT_MISSING",
            journey="platform_specific_creatives",
            reason=(
                "Tencent asset-material list now has a non-empty platform-specific contract, "
                "but Tencent medium creative and other non-Bytedance creative drafts still "
                "lack confirmed-read semantics or non-empty item schema."
            ),
            next_action=(
                "Review frontend control flow for Tencent medium creative POST, add a "
                "confirmed_read record if it is a read, then probe one page with a returned "
                "Tencent advertiser_id; do not substitute the common material catalog."
            ),
        )
    return None


def _non_bytedance_hierarchy(selected: str, words: frozenset[str]) -> bool:
    english = (
        (bool(words & {"kuaishou", "tencent"}) or {"non", "bytedance"} <= words)
        and len(words & {"campaign", "campaigns", "creative", "creatives", "group", "groups"}) >= 2
        and bool(words & {"performance", "drill"})
    )
    chinese = (
        any(term in selected for term in ("快手", "腾讯", "非巨量"))
        and (
            sum(term in selected for term in ("计划", "广告组", "组", "创意", "层级")) >= 2
            or "层级" in selected and "下钻" in selected
        )
        and any(term in selected for term in ("表现", "下钻"))
    )
    return english or chinese


def _platform_specific_creatives(selected: str, words: frozenset[str]) -> bool:
    english = (
        bool(words & {"platform", "platforms"}) and "specific" in words
        and bool(words & {"creative", "creatives"})
        and bool(words & {"asset", "assets", "field", "fields"})
    )
    chinese = (
        "平台" in selected and "专属" in selected
        and any(term in selected for term in ("素材", "创意"))
        and any(term in selected for term in ("字段", "深查", "详情", "创意"))
    )
    return english or chinese


__all__ = ["unavailable_promotion_gap"]
