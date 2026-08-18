"""Output projections kept outside the size-ratcheted Agent router."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def ndjson_metadata(value: Any) -> dict[str, Any]:
    """Preserve the Agent protocol when candidates become NDJSON rows."""

    from .agent import SCHEMA_VERSION

    if not isinstance(value, Mapping) or value.get("schema_version") != SCHEMA_VERSION:
        return {}
    return {
        "payload_schema_version": SCHEMA_VERSION,
        "ok": value.get("ok"),
        "offline": value.get("offline"),
        "network_called": value.get("network_called"),
        "mode": value.get("mode"),
        "routing_mode": value.get("routing_mode"),
        "routing": value.get("routing"),
        "count": value.get("count"),
        "total": value.get("total"),
        "query": value.get("query"),
        "continuation_token": value.get("continuation_token"),
        "next_action": value.get("next_action"),
        "execution": value.get("execution"),
        "scope": value.get("scope"),
        "fallbacks": value.get("fallbacks"),
        "catalog_warnings": value.get("catalog_warnings"),
        "capability_gaps": value.get("capability_gaps"),
        "match_policy": value.get("match_policy"),
    }


__all__ = ["ndjson_metadata"]
