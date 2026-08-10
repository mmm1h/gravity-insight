"""Unified command line for the standalone Gravity SDK."""

from __future__ import annotations

import sys
from collections.abc import Sequence

from . import cli as insight_cli
from .census import cli as census_cli
from .onboarding import command_requires_credentials, ensure_first_run_credentials
from .sql import __main__ as sql_cli


_HELP = """Gravity SDK

Usage:
  gravity insight <command> [options]
  gravity metadata sync --all-apps
  gravity metadata search|events|properties [query]
  gravity find <query>
  gravity recipe validate|check <name>
  gravity run @<recipe> [options]
  gravity run <operation-id> [options]
  gravity sql <command> [options]
  gravity census <command> [options]

Compatibility:
  Existing Insight commands may omit the `insight` namespace.

Run `gravity insight --help`, `gravity sql --help`, or
`gravity census --help` for command-specific help.
"""


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        if not ensure_first_run_credentials(requires_credentials=True):
            return 4
        print(_HELP, end="")
        return 0
    if args == ["--help"] or args == ["-h"]:
        print(_HELP, end="")
        return 0

    namespace, *remaining = args
    if namespace == "insight":
        command, command_args = insight_cli.main, remaining
        requires_credentials = command_requires_credentials(
            remaining, insight_cli.build_parser
        )
    elif namespace == "sql":
        command, command_args = sql_cli.main, remaining
        requires_credentials = command_requires_credentials(
            remaining, sql_cli.build_parser
        )
    elif namespace == "census":
        command, command_args = census_cli.main, remaining
        requires_credentials = False
    else:
        # The pre-split Insight CLI remains source-compatible.
        command, command_args = insight_cli.main, args
        requires_credentials = command_requires_credentials(args, insight_cli.build_parser)

    if any(value in {"-h", "--help", "--dry-run"} for value in command_args):
        requires_credentials = False

    if not ensure_first_run_credentials(
        requires_credentials=requires_credentials
    ):
        return 4
    return command(command_args)


if __name__ == "__main__":
    raise SystemExit(main())
