"""Deterministic Unicode transport for public CLI entry points."""

from __future__ import annotations

import sys
from typing import Any

from . import json_output


_ENTRY_ERRORS = (OSError, RuntimeError, UnicodeError, ValueError, TypeError)


def configure_utf8_stdio() -> None:
    """Use strict UTF-8 on standard text streams that support reconfiguration.

    Native Windows Python otherwise inherits the active ANSI code page even when
    a CLI is writing machine-readable JSON.  In-memory streams used by embedding
    callers and tests have no ``reconfigure`` method and are intentionally left
    unchanged.
    """

    for stream in (sys.stdout, sys.stderr):
        reconfigure: Any = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="strict")


def insight_main() -> int:
    """Configure transport before entering the standalone Insight CLI script."""

    configure_utf8_stdio()
    try:
        from .cli import main

        return main()
    except _ENTRY_ERRORS as exc:
        return emit_entry_error(exc)


def sql_main() -> int:
    """Configure transport before importing the standalone SQL CLI."""

    configure_utf8_stdio()
    try:
        from .sql.__main__ import main

        return main()
    except _ENTRY_ERRORS as exc:
        return emit_entry_error(exc)


def emit_entry_error(error: BaseException) -> int:
    """Emit a classified machine error for failures before a CLI owns control."""

    from .errors import error_envelope, exit_code_for_error

    next_action = None
    if isinstance(error, RuntimeError) and "home directory" in str(error).casefold():
        next_action = (
            "Set GRAVITY_CACHE_HOME to an existing writable directory, then retry "
            "the same command."
        )
    print(
        json_output.dumps(
            error_envelope(error, next_action=next_action),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ),
        file=sys.stderr,
    )
    return exit_code_for_error(error)


__all__ = [
    "configure_utf8_stdio",
    "emit_entry_error",
    "insight_main",
    "sql_main",
]
