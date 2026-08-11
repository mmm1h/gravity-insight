"""Decision-completeness normalization for promoted contracts."""

from __future__ import annotations

from typing import Any

from .drafts import DEFAULT_REDACT_FIELDS


def complete_privacy_redactions(operation: dict[str, Any]) -> None:
    privacy = operation["privacy_policy"]
    privacy["redact_fields"] = list(
        dict.fromkeys([*DEFAULT_REDACT_FIELDS, *privacy.get("redact_fields", [])])
    )
