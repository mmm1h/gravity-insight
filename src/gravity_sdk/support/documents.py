"""Read and write the repository's JSON-compatible YAML manifests.

JSON is a strict subset of YAML 1.2.  Using that subset gives manifests nested
maps and lists while keeping the governance gate on the Python standard library.
Legacy hand-authored YAML files continue to use their existing purpose-built
parsers; this module is only for the v3.2 manifest contracts.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


class DocumentError(ValueError):
    """A manifest cannot be decoded as the repository's YAML subset."""


def load_document(path: Path) -> Any:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise DocumentError(f"{path}: cannot read manifest: {exc}") from exc
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise DocumentError(
            f"{path}:{exc.lineno}:{exc.colno}: expected JSON-compatible YAML: {exc.msg}"
        ) from exc


def render_document(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=False) + "\n"


def replace_atomic_durable(source: Path, target: Path) -> None:
    """Atomically replace *target* and persist the directory entry on POSIX."""

    os.replace(source, target)
    _fsync_directory(target.parent)


def write_document_atomic(path: Path, value: Any) -> None:
    """Atomically replace a generated manifest without leaving a partial file."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(render_document(value))
            handle.flush()
            os.fsync(handle.fileno())
        replace_atomic_durable(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
