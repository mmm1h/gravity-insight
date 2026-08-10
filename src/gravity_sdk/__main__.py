"""Unified command line for the standalone Gravity SDK."""

from __future__ import annotations

import sys
from collections.abc import Sequence

from . import cli as insight_cli
from .census import cli as census_cli
from .sql import __main__ as sql_cli


_HELP = """Gravity SDK

Usage:
  gravity insight <command> [options]
  gravity sql <command> [options]
  gravity census <command> [options]

Compatibility:
  Existing Insight commands may omit the `insight` namespace.

Run `gravity insight --help`, `gravity sql --help`, or
`gravity census --help` for command-specific help.
"""


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args == ["--help"] or args == ["-h"]:
        print(_HELP, end="")
        return 0

    namespace, *remaining = args
    if namespace == "insight":
        return insight_cli.main(remaining)
    if namespace == "sql":
        return sql_cli.main(remaining)
    if namespace == "census":
        return census_cli.main(remaining)

    # The pre-split Insight CLI remains source-compatible.
    return insight_cli.main(args)


if __name__ == "__main__":
    raise SystemExit(main())
