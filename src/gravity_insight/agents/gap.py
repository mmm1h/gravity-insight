"""Machine-decidable Agent gap construction shared by domain owners."""

from __future__ import annotations

from typing import Any


def unavailable_gap(
    query: str,
    *,
    code: str,
    journey: str,
    reason: str,
    next_action: str,
    argv: list[str] | None = None,
) -> dict[str, Any]:
    gap: dict[str, Any] = {
        "kind": "capability_gap",
        "code": code,
        "journey": journey,
        "query": query,
        "reason": reason,
        "next_action": next_action,
        "weak_matches": [],
        "network_called": False,
    }
    if argv is not None:
        gap["next"] = {"ready_without_input": False, "argv": list(argv)}
    return gap


__all__ = ["unavailable_gap"]
