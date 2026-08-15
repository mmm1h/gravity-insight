"""Small formatting helpers for safe, bounded validation diagnostics."""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from .credential_sanitization import sanitize_credentials


ALTERNATIVE_DISPLAY_LIMIT = 20
_ACTUAL_VALUE_LIMIT = 160


def actual_value(value: Any) -> str:
    """Render one credential-sanitized caller value within the error budget."""

    rendered = json.dumps(
        sanitize_credentials(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    if len(rendered) <= _ACTUAL_VALUE_LIMIT:
        return rendered
    return rendered[: _ACTUAL_VALUE_LIMIT - 3] + "..."


def allowed_values(
    values: Iterable[Any], *, discovery_action: str | None = None
) -> str:
    """Render deterministic alternatives without unbounded error growth."""

    ordered = sorted({actual_value(value) for value in values})
    shown = ordered[:ALTERNATIVE_DISPLAY_LIMIT]
    rendered = ", ".join(shown)
    if len(ordered) > len(shown):
        if not discovery_action:
            raise ValueError("truncated alternatives require a discovery action")
        return (
            f"{rendered} (showing {len(shown)} of {len(ordered)}); discover all with "
            f"`{discovery_action}`"
        )
    return rendered


def live_metadata_miss(
    rendered_value: str, *, noun: str = "values", source: str = "live metadata"
) -> str:
    """Describe a metadata miss without copying upstream values into the error."""

    return (
        f"actual value absent from {source}: {rendered_value}; allowed "
        f"{noun} are not echoed because errors may enter logs"
    )


__all__ = [
    "ALTERNATIVE_DISPLAY_LIMIT",
    "actual_value",
    "allowed_values",
    "live_metadata_miss",
]
