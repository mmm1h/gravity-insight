"""Compact pagination contracts for agent-facing operation cards."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def compact_pagination(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {
            "supported": False,
            "kind": "none",
            "completeness": "unknown",
            "pagination_evidence": "none",
        }
    kind = str(value.get("kind", "none"))
    return {
        "supported": kind != "none",
        "kind": kind,
        "completeness": value.get("completeness", "unknown"),
        "pagination_evidence": value.get("pagination_evidence", "none"),
        "page_field": value.get("page_field"),
        "page_size_field": value.get("page_size_field"),
        "max_page_size": value.get("max_page_size"),
    }


__all__ = ["compact_pagination"]
