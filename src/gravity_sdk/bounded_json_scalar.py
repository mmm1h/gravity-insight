"""Shared bounded JSON scalar predicate for governed result rows."""

from __future__ import annotations

import math
from typing import Any


MAX_JSON_STRING_LENGTH = 8_192
MAX_JSON_INTEGER_BITS = 256


def is_bounded_json_scalar(value: Any) -> bool:
    if value is None or isinstance(value, bool):
        return True
    if isinstance(value, str):
        return len(value) <= MAX_JSON_STRING_LENGTH
    if type(value) is int:
        return value.bit_length() <= MAX_JSON_INTEGER_BITS
    return isinstance(value, float) and math.isfinite(value)


__all__ = [
    "MAX_JSON_INTEGER_BITS",
    "MAX_JSON_STRING_LENGTH",
    "is_bounded_json_scalar",
]
