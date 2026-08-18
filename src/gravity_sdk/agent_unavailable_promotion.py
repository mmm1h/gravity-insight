"""Natural-language gaps owned by unavailable promotion/material journeys."""

from __future__ import annotations

import re
from typing import Any

from .agent_gap import unavailable_gap
from .agent_intent_text import affirmative_intent_text


def unavailable_promotion_gap(query: str) -> dict[str, Any] | None:
    selected = affirmative_intent_text(query)
    if "." in selected and " " not in selected:
        return None
    words = frozenset(re.findall(r"[a-z0-9_]+", selected))
    if _non_bytedance_hierarchy(selected, words):
        return unavailable_gap(
            query, code="NON_BYTEDANCE_HIERARCHY_PARENT_MISSING",
            journey="non_bytedance_campaign_group_creative",
            reason=(
                "Tencent advertiser and ad-group report roots are now non-empty and "
                "promotion.tencent.tencent_adgroup_v2.list is a stable read, but Tencent "
                "creative performance (promotion.tencent.ad.list) still returns "
                "permission_unavailable on the declared parent, and Kuaishou campaign "
                "and creative lists remain empty after confirmed-read probes."
            ),
            next_action=(
                "Call promotion.tencent.tencent_adgroup_v2.list for Tencent ad-group "
                "performance; do not treat Kuaishou company IDs as delivery rows, do "
                "not retry promotion.tencent.ad.list after its declared-parent "
                "permission_unavailable, and do not invent a Kuaishou campaign or "
                "creative item schema from the empty confirmed-read samples."
            ),
        )
    if _platform_specific_creatives(selected, words):
        return unavailable_gap(
            query, code="PLATFORM_SPECIFIC_CREATIVE_CONTRACT_MISSING",
            journey="platform_specific_creatives",
            reason=(
                "Tencent asset-material and medium-creative lists now have non-empty "
                "platform-specific contracts, but Tencent title-library and Kuaishou "
                "creative drafts still lack a non-empty item schema after confirmed-read "
                "probes."
            ),
            next_action=(
                "Call material.tencent.list or material.tencent_medium_creative.list for "
                "Tencent; do not substitute the common material catalog, and do not invent "
                "Tencent title-library or Kuaishou creative item schemas from the empty "
                "confirmed-read samples."
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
            or ("计划" in selected and "组" in selected and "创意" in selected)
        )
        and any(term in selected for term in ("表现", "下钻", "查看"))
    )
    return english or chinese


def _platform_specific_creatives(selected: str, words: frozenset[str]) -> bool:
    english = (
        bool(words & {"platform", "platforms"}) and "specific" in words
        and bool(words & {"creative", "creatives"})
        and bool(words & {"asset", "assets", "field", "fields"})
    )
    chinese = (
        "平台" in selected
        and any(term in selected for term in ("专属", "独有"))
        and any(term in selected for term in ("素材", "创意"))
        and any(term in selected for term in ("字段", "深查", "详情", "创意"))
    )
    return english or chinese


__all__ = ["unavailable_promotion_gap"]
