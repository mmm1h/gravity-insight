"""Unified command line for the standalone Gravity SDK."""

from __future__ import annotations

import os
import sys
from collections.abc import Sequence


_HELP = """Gravity SDK

Usage:
  gravity [--workspace <gravity.toml|directory>] <command> [options]
  gravity agent [query]
  gravity agent --input <questions.json>
  gravity plan schema
  gravity plan run --input <plan.json>
  gravity analysis saved list|get|prepare|run
  gravity analysis template list|prepare|run
  gravity analysis query batch --input <queries.json> [--dry-run]
  gravity analysis dashboard prepare|run --app <alias|id> --ref <id|name> --start <date> --end <date>
  gravity analysis user journey --app <alias|id> --client-id <id> --date <date>
  gravity analysis segment snapshot --app <alias|id> --ref <id|name> --date <date>
  gravity analysis order directory --app <alias|id> --date <date>
  gravity analysis order trace --app <alias|id> --date <date> --trace-id <id>
  gravity analysis monetization detail --app <alias|id> --date <date>
  gravity multidim query --app <alias|id> --input <json|file|->
  gravity reports pulse --app <alias|id> --start <date> --end <date>
  gravity reports usage
  gravity materials performance --app <alias|id> --start <date> --end <date>
  gravity promotion performance --app <alias|id> --start <date> --end <date>
  gravity promotion advertiser-profile --start <date> --end <date>
  gravity export run <operation-id> --input <json|file|-> --output <file>
  gravity insight <command> [options]
  gravity metadata sync --all-apps
  gravity metadata search|events|properties|vocabulary [query]
  gravity metadata tables [query]
  gravity find <query>
  gravity recipe validate|check <name>
  gravity run @<recipe> [options]
  gravity run <operation-id> [options]
  gravity sql <command> [options]
  gravity census <command> [options]

Compatibility:
  Existing Insight commands may omit the `insight` namespace.

For an Agent-ready machine protocol, run `gravity agent`.
Run `gravity insight --help`, `gravity sql --help`, or
`gravity census --help` for command-specific help.
"""


def command_requires_credentials(args: Sequence[str], parser_factory: object) -> bool:
    from .onboarding import command_requires_credentials as implementation

    return implementation(args, parser_factory)


def ensure_first_run_credentials(*, requires_credentials: bool) -> bool:
    from .onboarding import ensure_first_run_credentials as implementation

    return implementation(requires_credentials=requires_credentials)


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = _extract_workspace(list(sys.argv[1:] if argv is None else argv))
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    from . import cli as insight_cli
    from .census import cli as census_cli
    from .sql import __main__ as sql_cli

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


def _extract_workspace(args: list[str]) -> list[str]:
    """Apply the one process-wide workspace selector before SDK imports."""

    selected: str | None = None
    remaining: list[str] = []
    index = 0
    while index < len(args):
        value = args[index]
        if value == "--workspace":
            if index + 1 >= len(args) or args[index + 1].startswith("--"):
                raise ValueError("--workspace requires a gravity.toml file or directory")
            candidate = args[index + 1]
            index += 2
        elif value.startswith("--workspace="):
            candidate = value.partition("=")[2]
            if not candidate:
                raise ValueError("--workspace requires a gravity.toml file or directory")
            index += 1
        else:
            remaining.append(value)
            index += 1
            continue
        if selected is not None:
            raise ValueError("--workspace may be supplied only once")
        selected = candidate
    if selected is not None:
        os.environ["GRAVITY_WORKSPACE"] = selected
    return remaining


if __name__ == "__main__":
    raise SystemExit(main())
