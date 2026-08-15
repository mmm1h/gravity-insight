"""Natural-language gaps owned by unavailable promotion/material journeys."""

from __future__ import annotations

import re
from typing import Any

from .agent_gap import unavailable_gap


def unavailable_promotion_gap(query: str) -> dict[str, Any] | None:
    selected = " ".join(query.strip().casefold().split())
    words = frozenset(re.findall(r"[a-z0-9_]+", selected))
    if _platform_asset_download(selected, words):
        return unavailable_gap(
            query, code="PLATFORM_ASSET_BINARY_CONTRACT_MISSING",
            journey="platform_asset_preview_download",
            reason="List contracts expose media references, but binary hosts, redirects, and expiry semantics are unproven.",
            next_action=(
                "Obtain one authorized current media reference, prove the binary host/path and redirect allowlist "
                "without committing bytes or URLs, then add the bounded download effect."
            ),
        )
    if _non_bytedance_hierarchy(selected, words):
        return unavailable_gap(
            query, code="NON_BYTEDANCE_HIERARCHY_PARENT_MISSING",
            journey="non_bytedance_campaign_group_creative",
            reason="Non-Bytedance advertiser/account roots have not produced usable parent candidates for hierarchy reports.",
            next_action=(
                "Use a tenant with Kuaishou or Tencent delivery data, verify one minimal advertiser root, "
                "then follow only returned parent IDs through campaign, group, creative, and report reads."
            ),
        )
    if _platform_specific_creatives(selected, words):
        return unavailable_gap(
            query, code="PLATFORM_SPECIFIC_CREATIVE_CONTRACT_MISSING",
            journey="platform_specific_creatives",
            reason="Outside Bytedance, platform-specific creative fields lack non-empty response contracts.",
            next_action=(
                "Use a tenant with one non-Bytedance creative, capture a single bounded non-empty item, "
                "and register its platform-specific fields without substituting the common material catalog."
            ),
        )
    return None


def _platform_asset_download(selected: str, words: frozenset[str]) -> bool:
    english = (
        bool(words & {"creative", "asset"}) and "exact" in words
        and bool(words & {"preview", "download"})
        and bool(words & {"image", "video"})
    )
    chinese = (
        "平台素材" in selected and "精确引用" in selected
        and any(term in selected for term in ("预览", "下载"))
        and any(term in selected for term in ("图片", "视频"))
    )
    return english or chinese


def _non_bytedance_hierarchy(selected: str, words: frozenset[str]) -> bool:
    english = (
        bool(words & {"kuaishou", "tencent"})
        and bool(words & {"campaign", "campaigns"})
        and bool(words & {"group", "groups"})
        and bool(words & {"creative", "creatives"})
        and bool(words & {"performance", "drill"})
    )
    chinese = (
        any(term in selected for term in ("快手", "腾讯"))
        and "计划" in selected and "广告组" in selected and "创意" in selected
        and any(term in selected for term in ("表现", "下钻"))
    )
    return english or chinese


def _platform_specific_creatives(selected: str, words: frozenset[str]) -> bool:
    english = (
        bool(words & {"platform", "platforms"}) and "specific" in words
        and bool(words & {"creative", "creatives"})
        and bool(words & {"asset", "assets", "field", "fields"})
        and "common" in words
    )
    chinese = (
        "投放平台" in selected and "专属" in selected
        and any(term in selected for term in ("素材", "创意"))
        and "通用素材目录" in selected
    )
    return english or chinese


__all__ = ["unavailable_promotion_gap"]
