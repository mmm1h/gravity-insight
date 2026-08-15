"""Value-free Agent discovery card for the governed single-user journey."""

from __future__ import annotations

from collections.abc import Mapping
import re
from typing import Any


USER_JOURNEY_SELECTOR = "composite:user_journey"
_WORDS = re.compile(r"[a-z0-9_]+", re.IGNORECASE)


def user_journey_capability_cards(
    query: str,
    *,
    domain: str | None = None,
    platform: str | None = None,
) -> list[dict[str, Any]]:
    """Return one card only for an explicit single-user journey intent.

    The card contains placeholders rather than a client identifier.  Discovery
    therefore remains value-free while giving callers the exact Plan product
    to fill after they obtain an explicit user identity and time window.
    """

    if platform is not None or domain not in {None, "analysis"}:
        return []
    match = _journey_match(query)
    if match is None:
        return []
    return [_journey_card(match)]


def is_user_journey_card(card: Mapping[str, Any]) -> bool:
    """Identify the exclusive journey handoff without trusting its position."""

    return (
        card.get("kind") == "composite"
        and card.get("selector") == USER_JOURNEY_SELECTOR
        and card.get("composite") == "user_journey"
    )


def _journey_match(query: str) -> dict[str, Any] | None:
    selected = query.strip().casefold()
    normalized = " ".join(_WORDS.findall(selected.replace("-", " ")))
    words = frozenset(normalized.split())
    exact = selected in {USER_JOURNEY_SELECTOR, "user_journey", "user journey"}
    english_single_journey = (
        bool(words & {"user", "users"})
        and bool(words & {"single", "one", "specific"})
        and bool(words & {"journey", "path"})
    )
    english_events_postbacks = (
        bool(words & {"user", "users"})
        and bool(words & {"event", "events", "journey", "timeline", "profile"})
        and bool(words & {"postback", "postbacks", "callback", "callbacks"})
    )
    chinese = (
        "用户" in selected
        and any(
            term in selected
            for term in ("单用户", "单个用户", "指定用户", "某个用户", "这个用户")
        )
        and any(term in selected for term in ("旅程", "路径", "事件", "行为", "时间线", "画像"))
        and any(term in selected for term in ("回传", "回调", "postback"))
    )
    if not (exact or english_single_journey or english_events_postbacks or chinese):
        return None
    return {
        "confidence": "strong",
        "coverage": 1.0,
        "matched_terms": ["single user journey"],
        "missing_terms": [],
        "score": 100,
        "exact_selector": exact,
        "intent_only": not exact,
    }


def _journey_card(match: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "kind": "composite",
        "selector": USER_JOURNEY_SELECTOR,
        "composite": "user_journey",
        "domain": "analysis",
        "description": "并发读取单用户画像、事件时间线与回传状态。",
        "effect": "read",
        "executable": True,
        "plan_executable": True,
        "natural_language_auto_execute": False,
        "required_inputs": ["app", "client_id", "date"],
        "missing_inputs": ["app", "client_id", "date"],
        "input_schema": {
            "app": {
                "type": "string|integer",
                "required": True,
                "nullable": False,
            },
            "client_id": {
                "type": "string",
                "required": True,
                "nullable": False,
                "sensitive": True,
                "echo": False,
                "source": "caller_explicit",
            },
            "date": {
                "type": "string",
                "format": "date",
                "required": False,
                "alternative": "paired start/end",
            },
            "start": {"type": "string", "format": "date", "required": False},
            "end": {"type": "string", "format": "date", "required": False},
        },
        "input_template": {
            "app": "<workspace-app-alias-or-positive-id>",
            "client_id": "<explicit-client-id>",
            "date": "<YYYY-MM-DD; or replace with explicit start/end>",
        },
        "match": dict(match),
        "next": {
            "ready_without_input": False,
            "argv": ["gravity", "plan", "run", "--input", "<plan.json>"],
            "cli_argv": [
                "gravity",
                "analysis",
                "user",
                "journey",
                "--app",
                "<app>",
                "--client-id",
                "<explicit-client-id>",
                "--date",
                "<YYYY-MM-DD>",
            ],
        },
    }


__all__ = [
    "USER_JOURNEY_SELECTOR",
    "is_user_journey_card",
    "user_journey_capability_cards",
]
