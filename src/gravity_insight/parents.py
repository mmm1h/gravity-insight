"""Public CLI surface for resolving declared parent-resource candidates."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from typing import Any

try:
    from gravity_insight.parent_resolution import (
        resolve_declared_parents,
    )
except ModuleNotFoundError:  # source checkout before editable installation
    from gravity_insight.parent_resolution import (
        resolve_declared_parents,
    )


def add_parent_commands(commands: Any) -> None:
    parents = commands.add_parser(
        "parents", help="Resolve declared parent-resource candidates."
    )
    subcommands = parents.add_subparsers(dest="parents_command", required=True)
    resolve = subcommands.add_parser(
        "resolve", help="Read declared stable parents and return candidate IDs."
    )
    resolve.add_argument("operation_id")


def run_parent_command(
    args: argparse.Namespace, client_factory: Callable[[argparse.Namespace], Any]
) -> dict[str, Any]:
    client = client_factory(args)
    description = client.describe(args.operation_id)
    return resolve_declared_parents(description, client.probe)


__all__ = ["add_parent_commands", "run_parent_command"]
