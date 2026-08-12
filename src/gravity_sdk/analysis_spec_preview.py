"""Caller-safe preview projection for compiled Analysis inputs."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def redact_analysis_values(
    value: Any, *, key: str | None = None
) -> tuple[Any, bool]:
    """Preserve executable structure while removing caller-supplied values."""

    if key in {"user_filtering", "user_re_attribute_filtering"} and value:
        return {"redacted": True}, True
    if key in {"value", "values"} and value not in (None, [], (), {}):
        if isinstance(value, (list, tuple)):
            return ["<redacted>" for _ in value], True
        return "<redacted>", True
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        changed = False
        for child_key, child in value.items():
            result[child_key], child_changed = redact_analysis_values(
                child, key=str(child_key)
            )
            changed = changed or child_changed
        return result, changed
    if isinstance(value, (list, tuple)):
        result_list: list[Any] = []
        changed = False
        for child in value:
            projected, child_changed = redact_analysis_values(child)
            result_list.append(projected)
            changed = changed or child_changed
        return result_list, changed
    return value, False


__all__ = ["redact_analysis_values"]
