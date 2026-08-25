"""Bounded row projection for Promotion Performance results."""

from __future__ import annotations

from collections.abc import Mapping
import copy
import json
from typing import Any

from .bounded_json_scalar import (
    MAX_JSON_INTEGER_BITS,
    MAX_JSON_STRING_LENGTH,
    is_bounded_json_scalar,
)

MAX_OPAQUE_JSON_DEPTH = 8
MAX_OPAQUE_JSON_ELEMENTS = 256
MAX_OPAQUE_JSON_BYTES = 32_768

RowFailure = tuple[str, str]


def safe_promotion_rows(
    value: Any,
    *,
    allowed_fields: frozenset[str],
    opaque_fields: frozenset[str],
) -> tuple[list[dict[str, Any]] | None, RowFailure | None]:
    if not isinstance(value, list):
        return None, ("row_collection_type", "$.data.data.list")
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        root = f"$.data.data.list[{index}]"
        if not isinstance(item, Mapping):
            return None, ("row_type", root)
        keys = tuple(item)
        if any(not isinstance(key, str) for key in keys):
            return None, ("row_field_name", f"{root}.<invalid-key>")
        if any(key not in allowed_fields for key in keys):
            return None, ("row_field_registration", f"{root}.<unregistered>")
        row: dict[str, Any] = {}
        for key, field_value in item.items():
            path = f"{root}.{key}"
            if key in opaque_fields:
                copied, failure = _bounded_json_value(field_value)
                if failure is not None:
                    return None, (f"row_field_opaque_json_{failure}", path)
                row[key] = copied
            elif not is_bounded_json_scalar(field_value):
                return None, ("row_field_scalar_rule", path)
            else:
                row[key] = copy.deepcopy(field_value)
        rows.append(row)
    return rows, None


def _bounded_json_value(value: Any) -> tuple[Any, str | None]:
    budget = [0]
    copied, failure = _copy_json_value(value, depth=0, budget=budget)
    if failure is not None:
        return None, failure
    try:
        encoded = json.dumps(
            copied, ensure_ascii=False, allow_nan=False, separators=(",", ":")
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError):
        return None, "rule"
    if len(encoded) > MAX_OPAQUE_JSON_BYTES:
        return None, "bounds"
    return copied, None


def _copy_json_value(
    value: Any, *, depth: int, budget: list[int]
) -> tuple[Any, str | None]:
    if depth > MAX_OPAQUE_JSON_DEPTH:
        return None, "bounds"
    budget[0] += 1
    if budget[0] > MAX_OPAQUE_JSON_ELEMENTS:
        return None, "bounds"
    if is_bounded_json_scalar(value):
        return copy.deepcopy(value), None
    if isinstance(value, Mapping):
        copied: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                return None, "rule"
            if len(key) > MAX_JSON_STRING_LENGTH:
                return None, "bounds"
            nested, failure = _copy_json_value(
                item, depth=depth + 1, budget=budget
            )
            if failure is not None:
                return None, failure
            copied[key] = nested
        return copied, None
    if isinstance(value, (list, tuple)):
        copied_items: list[Any] = []
        for item in value:
            nested, failure = _copy_json_value(
                item, depth=depth + 1, budget=budget
            )
            if failure is not None:
                return None, failure
            copied_items.append(nested)
        return copied_items, None
    return None, "rule"


__all__ = [
    "MAX_JSON_INTEGER_BITS",
    "MAX_JSON_STRING_LENGTH",
    "MAX_OPAQUE_JSON_BYTES",
    "MAX_OPAQUE_JSON_DEPTH",
    "MAX_OPAQUE_JSON_ELEMENTS",
    "safe_promotion_rows",
]
