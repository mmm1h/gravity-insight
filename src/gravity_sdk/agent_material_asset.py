"""Direct Agent handoff for the response-bound material file effect."""

from __future__ import annotations

import re
from typing import Any, Mapping

from .agent_intent_text import affirmative_intent_text


SELECTOR = "material.asset.fetch"


def material_asset_capability_cards(
    query: str, *, domain: str | None, platform: str | None
) -> list[dict[str, Any]]:
    if platform is not None or domain not in {None, "material", "promotion"}:
        return []
    selected = affirmative_intent_text(query)
    words = frozenset(re.findall(r"[a-z0-9_]+", selected))
    exact = selected.strip().casefold() == SELECTOR
    if not exact and not _material_asset_intent(selected, words):
        return []
    return [
        {
            "kind": "material_asset",
            "selector": SELECTOR,
            "domain": "material",
            "description": (
                "从刚读取的已登记素材 operation 响应按精确引用取出文件或缩略图 URL，"
                "跟随重定向并原子下载；调用方不能提交 URL。"
            ),
            "boundaries": (
                "调用方不能提交 URL。",
                "不读取素材表现报表。",
            ),
            "effect": "material_file_download",
            "executable": True,
            "currently_callable": True,
            "natural_language_auto_execute": False,
            "plan_executable": False,
            "execution_mode": "direct_material_fetch_after_explicit_inputs",
            "required_inputs": [
                "source", "input", "ref_field", "ref", "role", "output"
            ],
            "missing_inputs": [
                "source", "input", "ref_field", "ref", "role", "output"
            ],
            "input_template": {
                "source": "<local-or-bytedance_project>",
                "input": "<registered-source-operation-input.json>",
                "ref_field": "<documented-reference-field>",
                "ref": "<exact-reference-value>",
                "role": "<file-or-thumbnail>",
                "output": "<new-local-file-path>",
            },
            "optional_inputs": ["output_root"],
            "source_contract": {
                "accepts_caller_url": False,
                "fresh_registered_response_required": True,
                "artifact_schema_version": "gravity.artifact-transfer.v1",
                "redirect_policy": "same_host_only",
                "output_root_bound": True,
                "sources": ["local", "bytedance_project"],
            },
            "match": {
                "confidence": "strong",
                "coverage": 1.0,
                "matched_terms": [SELECTOR if exact else "material asset fetch"],
                "missing_terms": [],
                "exact_selector": exact,
                "specific_intent": True,
            },
            "next": {
                "ready_without_input": False,
                "argv": [
                    "gravity", "materials", "fetch",
                    "--source", "<local-or-bytedance_project>",
                    "--input", "<source-input.json>",
                    "--ref-field", "<reference-field>",
                    "--ref", "<reference-value>",
                    "--role", "<file-or-thumbnail>",
                    "--output", "<new-local-file-path>",
                ],
                "call_count_after_discovery": 1,
            },
        }
    ]


def material_asset_capability_inventory() -> tuple[dict[str, Any], ...]:
    """Materialize the canonical response-bound file card."""

    return tuple(
        material_asset_capability_cards(SELECTOR, domain=None, platform=None)
    )


def is_authoritative_material_asset_card(card: Mapping[str, Any]) -> bool:
    return (
        card.get("kind") == "material_asset"
        and card.get("selector") == SELECTOR
        and card.get("effect") == "material_file_download"
        and card.get("currently_callable") is True
    )


def _material_asset_intent(selected: str, words: frozenset[str]) -> bool:
    english = (
        (bool(words & {"asset", "assets"}) or (
            "creative" in words and bool(words & {"platform", "reference"})
        ))
        and bool(words & {
            "binary", "download", "fetch", "file", "image", "media", "preview", "video"
        })
        and bool(words & {"binary", "download", "fetch", "file", "preview"})
    )
    chinese = (
        any(term in selected for term in (
            "平台素材", "平台创意", "素材id", "素材 id", "创意引用",
            "素材引用", "精确素材",
        ))
        and any(term in selected for term in ("预览", "下载", "文件", "二进制"))
        and any(term in selected for term in ("图片", "视频", "媒体", "文件", "二进制"))
    )
    return english or chinese


__all__ = [
    "SELECTOR",
    "is_authoritative_material_asset_card",
    "material_asset_capability_inventory",
    "material_asset_capability_cards",
]
