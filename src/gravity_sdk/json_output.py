"""Standards-compliant JSON encoding for public machine outputs."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any


def to_jsonable(value: Any) -> Any:
    """Convert SDK dataclasses/tuples to a JSON-compatible value."""

    if is_dataclass(value):
        return to_jsonable(asdict(value))
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return to_jsonable(value.to_dict())
    if isinstance(value, Mapping):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [to_jsonable(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return value


def dumps(value: Any, **options: Any) -> str:
    """Serialize JSON without JavaScript-only non-finite number literals."""

    return json.dumps(value, allow_nan=False, **options)
