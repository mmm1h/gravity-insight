"""Stable access to contracts distributed inside the gravity-insight wheel."""

from __future__ import annotations

import json
from importlib.resources import files
from typing import Any


RELEASE_COMPATIBILITY_SCHEMA_VERSION = "gravity.release-compatibility.v1"
_RELEASE_COMPATIBILITY_RESOURCE = "generated/release-compatibility.v1.json"


def load_release_compatibility() -> dict[str, Any]:
    """Load the packaged release compatibility contract."""
    resource = files(__package__).joinpath(_RELEASE_COMPATIBILITY_RESOURCE)
    try:
        payload = json.loads(resource.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("packaged release compatibility contract is unreadable") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != RELEASE_COMPATIBILITY_SCHEMA_VERSION
    ):
        raise RuntimeError(
            "packaged release compatibility contract has an unsupported schema"
        )
    return payload


__all__ = [
    "RELEASE_COMPATIBILITY_SCHEMA_VERSION",
    "load_release_compatibility",
]
