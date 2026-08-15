"""Atomic JSON result publication shared by CLI product surfaces."""

from __future__ import annotations

import os
import tempfile
from contextlib import contextmanager
from collections.abc import Mapping
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from .errors import (
    ErrorCategory,
    InputValidationError,
    LocalIOError,
    exit_code_for_category,
)
from .support.documents import replace_atomic_durable
from .support.process_lock import (
    LOCK_RECOVERY_GUIDANCE,
    FileLockTimeout,
    advisory_file_lock,
)


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


def _resolved_destination(output: str) -> Path:
    """Expand a user-relative destination and recheck its filesystem shape."""

    selected = output.strip()
    if not selected or selected == "-" or "\x00" in selected:
        raise InputValidationError(
            "output must be a non-empty local file path", field="output"
        )
    try:
        path = Path(selected).expanduser()
    except RuntimeError as exc:
        raise LocalIOError(
            "cannot resolve '~' because the user home directory is unavailable",
            field="output",
            next_action=(
                "Set HOME or USERPROFILE to the user home directory, or retry "
                "with an absolute --output path."
            ),
        ) from exc
    if path.exists() and path.is_dir():
        raise InputValidationError(
            "output must be a local file path, not a directory", field="output"
        )
    ancestor = path.parent
    while not ancestor.exists() and ancestor != ancestor.parent:
        ancestor = ancestor.parent
    if ancestor.exists() and not ancestor.is_dir():
        raise InputValidationError(
            "output parent must be a local directory", field="output"
        )
    return path


def _lock_path(path: Path) -> Path:
    return path.with_name(f".{path.name}.gravity-output.lock")


@contextmanager
def _exclusive_output(path: Path) -> Iterator[None]:
    """Fail closed while another process owns the same result destination."""

    lock = _lock_path(path)
    try:
        with advisory_file_lock(
            lock,
            owner=f"result output {path}",
            timeout=0,
        ):
            yield
    except FileLockTimeout as exc:
        raise LocalIOError(
            f"another process is writing output {path}",
            field="output",
            next_action=LOCK_RECOVERY_GUIDANCE,
        ) from exc


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
    return exit_code_for_category(str(category), default=ErrorCategory.LOCAL)


def write_rendered_result(
    output: str,
    rendered: str,
    *,
    output_format: str = "json",
) -> dict[str, Any]:
    """Atomically publish rendered UTF-8 text and return the standard receipt."""

    path = _resolved_destination(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = rendered.encode("utf-8")
    temporary: Path | None = None
    with _exclusive_output(path):
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
