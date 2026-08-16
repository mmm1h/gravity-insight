"""Small shared lifecycle primitives for governed mutation domains."""

from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Mapping
from typing import Any

from .actionable_error_values import actual_value
from .errors import InputValidationError


MARKER_PREFIX = "GSDK-"
WRITE_LOCK = threading.Lock()


def mutation_marker(
    create_kind: str,
    semantic_request: Mapping[str, Any],
    *,
    idempotency_key: str | None = None,
) -> str:
    """Return a deterministic source/idempotency marker for one create."""

    selected_kind = _text(create_kind, "create_kind", 64)
    key = "" if idempotency_key is None else _text(
        idempotency_key, "idempotency_key", 128
    )
    payload = json.dumps(
        {
            "create_kind": selected_kind,
            "idempotency_key": key,
            "request": semantic_request,
        },
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return MARKER_PREFIX + hashlib.sha256(payload).hexdigest()[:12]


def mutation_digest(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _text(value: Any, field: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise InputValidationError(
            f"actual value: {actual_value(value)}; allowed range: 1 through {maximum} characters",
            field=field,
            next_action=f"Use a non-empty {field} of at most {maximum} characters, then run the dry-run again.",
        )
    return value


__all__ = ["MARKER_PREFIX", "WRITE_LOCK", "mutation_digest", "mutation_marker"]
