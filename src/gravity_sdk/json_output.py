"""Standards-compliant JSON encoding for public machine outputs."""

from __future__ import annotations

import json
from typing import Any


def dumps(value: Any, **options: Any) -> str:
    """Serialize JSON without JavaScript-only non-finite number literals."""

    return json.dumps(value, allow_nan=False, **options)
