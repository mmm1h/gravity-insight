"""Value-free response schema sketches used by probes and privacy review."""

from __future__ import annotations

import re
from typing import Any, Mapping


def json_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, Mapping):
        return "object"
    return "unknown"


def safe_schema_key(value: Any) -> str:
    key = str(value)
    lowered = key.casefold()
    if (
        len(key) > 64
        or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key)
        or "@" in key
        or re.fullmatch(r"[0-9a-f]{16,}", lowered)
        or re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", lowered)
    ):
        return "{dynamic_key}"
    return key


def response_schema_sketch(value: Any) -> dict[str, Any]:
    """Return path/type observations without retaining response values."""

    observed: dict[str, set[str]] = {}

    def visit(item: Any, path: str, depth: int) -> None:
        observed.setdefault(path, set()).add(json_type(item))
        if depth >= 12:
            return
        if isinstance(item, Mapping):
            for raw_key, child in item.items():
                visit(child, f"{path}.{safe_schema_key(raw_key)}", depth + 1)
        elif isinstance(item, list):
            if not item:
                observed.setdefault(path + "[]", set()).add("unknown")
            for child in item[:200]:
                visit(child, path + "[]", depth + 1)

    visit(value, "$", 0)
    paths = [
        {"path": path, "types": sorted(types), "presence": "observed"}
        for path, types in sorted(observed.items())
    ]
    return {"schema_version": "gravity-insight.raw-schema-sketch.v1", "paths": paths}


__all__ = ["json_type", "response_schema_sketch", "safe_schema_key"]
