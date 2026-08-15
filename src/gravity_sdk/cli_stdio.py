"""Deterministic Unicode transport for public CLI entry points."""

from __future__ import annotations

import sys
from typing import Any


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
    from .cli import main

    return main()


__all__ = ["configure_utf8_stdio", "insight_main"]
