"""Atomic JSON result publication shared by CLI product surfaces."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .support.documents import replace_atomic_durable


def output_file(value: str) -> str:
    """Validate a local result destination without creating it."""

    selected = value.strip()
    if not selected or selected == "-" or "\x00" in selected:
        raise ValueError("output must be a non-empty local file path")
    path = Path(selected)
    if path.exists() and path.is_dir():
        raise ValueError("output must be a local file path, not a directory")
    ancestor = path.parent
    while not ancestor.exists() and ancestor != ancestor.parent:
        ancestor = ancestor.parent
    if ancestor.exists() and not ancestor.is_dir():
        raise ValueError("output parent must be a local directory")
    return selected


def result_is_persistable(value: Any) -> bool:
    """Keep terminal failures out of files while retaining explicit partial data."""

    if not isinstance(value, Mapping):
        return True
    status = value.get("status")
    if status in {"error", "capability_gap"}:
        return False
    return value.get("ok") is not False or status == "partial"


def terminal_result_exit_code(value: Mapping[str, Any]) -> int:
    """Preserve an aggregate exit code, or classify a terminal error."""

    explicit = value.get("exit_code")
    if type(explicit) is int:
        return explicit
    error = value.get("error")
    category = error.get("category") if isinstance(error, Mapping) else None
    return {"caller": 2, "upstream": 3, "local": 4}.get(str(category), 4)


def write_rendered_result(
    output: str,
    rendered: str,
    *,
    output_format: str = "json",
) -> dict[str, Any]:
    """Atomically publish rendered UTF-8 text and return the standard receipt."""

    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = rendered.encode("utf-8")
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        replace_atomic_durable(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return {
        "ok": True,
        "status": "written",
        "output": str(path),
        "format": output_format,
        "size_bytes": len(encoded),
    }


__all__ = [
    "output_file",
    "result_is_persistable",
    "terminal_result_exit_code",
    "write_rendered_result",
]
