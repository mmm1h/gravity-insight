"""Natural-language gaps owned by unavailable promotion/material journeys."""

from __future__ import annotations

import re
from typing import Any

from .agent_gap import unavailable_gap
from .agent_intent_text import affirmative_intent_text


def unavailable_promotion_gap(query: str) -> dict[str, Any] | None:
    selected = affirmative_intent_text(query)
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
        (bool(words & {"asset", "assets"}) or (
            "creative" in words and bool(words & {"platform", "reference"})
        ))
        and bool(words & {"binary", "download", "fetch", "file", "image", "media", "preview", "video"})
        and bool(words & {"binary", "download", "fetch", "file", "preview"})
    )
    chinese = (
        any(term in selected for term in ("平台素材", "平台创意", "素材id", "素材 id", "创意引用", "精确素材"))
        and any(term in selected for term in ("预览", "下载", "文件", "二进制"))
        and any(term in selected for term in ("图片", "视频", "媒体", "文件", "二进制"))
    )
    return english or chinese


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
