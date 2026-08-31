"""Entity, time, freshness, and authority alignment for Context Packs."""

from __future__ import annotations

import hashlib
from datetime import date
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .context_contract import ContextContractError, observed_date


def normalize_windows(
    value: Mapping[str, Mapping[str, Any]], required: Sequence[str]
) -> dict[str, dict[str, str]]:
    if not isinstance(value, Mapping) or set(value) != set(required):
        raise ContextContractError(
            "CONTEXT_TIME_INVALID", "Requested Context windows are incomplete"
        )
    result: dict[str, dict[str, str]] = {}
    for name in sorted(required):
        window = value[name]
        if not isinstance(window, Mapping) or set(window) != {
            "start",
            "end",
            "timezone",
        }:
            raise ContextContractError(
                "CONTEXT_TIME_INVALID", "Requested Context window fields are invalid"
            )
        result[name] = _normalize_window(window)
    return result


def _normalize_window(value: Mapping[str, Any]) -> dict[str, str]:
    try:
        start = date.fromisoformat(str(value["start"]))
        end = date.fromisoformat(str(value["end"]))
        ZoneInfo(str(value["timezone"]))
    except (ValueError, ZoneInfoNotFoundError) as exc:
        raise ContextContractError(
            "CONTEXT_TIME_INVALID", "Requested Context window is invalid"
        ) from exc
    if start.isoformat() != value["start"] or end.isoformat() != value["end"] or start > end:
        raise ContextContractError(
            "CONTEXT_TIME_INVALID", "Requested Context window is not canonical"
        )
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "timezone": str(value["timezone"]),
    }


def resolve_entities(
    values: Sequence[str], aliases: Mapping[str, str]
) -> tuple[list[str], list[dict[str, Any]]]:
    resolved: list[str] = []
    gaps: list[dict[str, Any]] = []
    for value in values:
        selected = aliases.get(value, value)
        if value.startswith("app://") and value not in aliases:
            gaps.append(_entity_gap(value))
        elif not isinstance(selected, str) or "://" not in selected:
            gaps.append(_entity_gap("invalid"))
        else:
            resolved.append(selected)
    return sorted(set(resolved)), gaps


def _entity_gap(value: str) -> dict[str, Any]:
    identity = hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
    return {
        "item_id": f"entity:{identity}",
        "required": True,
        "status": "unsupported",
        "reason_code": "CONTEXT_ENTITY_UNRESOLVED",
    }


def context_freshness(
    declaration: Mapping[str, Any],
    requirement: Mapping[str, Any],
    observed_at: str,
) -> str:
    policy = requirement["freshness_policy"]
    maximum = declaration["max_age_days"]
    if maximum is None:
        maximum = policy["max_age_days"]
    if maximum is None:
        return "current"
    as_of = (
        date.fromisoformat(policy["as_of"])
        if policy["as_of"] is not None
        else observed_date(observed_at)
    )
    age = (as_of - observed_date(observed_at)).days
    return "stale" if age > maximum else "current"


def authority_allowed(authority: str, policy: Mapping[str, Any]) -> bool:
    if authority in {"project_authoritative", "canonical"}:
        return True
    if authority == "supporting":
        return bool(policy["allow_supporting"])
    if authority == "declared_intent":
        return bool(policy.get("allow_declared_intent", False))
    return bool(policy["allow_unverified"])


__all__ = [
    "authority_allowed",
    "context_freshness",
    "normalize_windows",
    "resolve_entities",
]
