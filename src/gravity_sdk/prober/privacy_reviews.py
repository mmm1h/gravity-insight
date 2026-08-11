"""Load reviewed route-specific response field classifications."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping


_REVIEW_PATH = Path(__file__).resolve().parents[1] / "governance" / "privacy-reviews.json"


def _review_map(document: Mapping[str, Any], key: str) -> Mapping[str, frozenset[str]]:
    section = document.get(key)
    if not isinstance(section, Mapping):
        raise RuntimeError(f"privacy review section is not an object: {key}")
    result: dict[str, frozenset[str]] = {}
    for operation_id, fields in section.items():
        if not isinstance(fields, list) or not all(
            isinstance(field, str) and field for field in fields
        ):
            raise RuntimeError(f"privacy review fields are invalid: {operation_id}")
        result[str(operation_id)] = frozenset(fields)
    return result


_DOCUMENT = json.loads(_REVIEW_PATH.read_text(encoding="utf-8"))
REVIEWED_SAFE_FIELDS = _review_map(_DOCUMENT, "reviewed_safe_fields")
ROUTE_REVIEWED_SENSITIVE_FIELDS = _review_map(
    _DOCUMENT, "reviewed_sensitive_fields"
)


__all__ = ["REVIEWED_SAFE_FIELDS", "ROUTE_REVIEWED_SENSITIVE_FIELDS"]
