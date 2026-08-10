"""CLI registration and dispatch for the Resolver pipeline."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Mapping

from . import runtime
from .resolver import parse_parameter_assignments, resolve_and_run
from .workspace import load_workspace


def add_resolver_command(
    commands: Any,
    add_input: Callable[..., None],
    add_all_pages: Callable[[Any], None],
) -> None:
    command = commands.add_parser(
        "run", help="Resolve a recipe or operation and execute it in one process."
    )
    command.add_argument("selector", help="@recipe or operation_id")
    add_input(command)
    command.add_argument(
        "--param",
        dest="parameters",
        action="append",
        default=[],
        metavar="NAME=VALUE",
        help="Bind a declared recipe parameter; JSON values are typed.",
    )
    command.add_argument("--app", help="Workspace app alias or literal app id.")
    command.add_argument("--start")
    command.add_argument("--end")
    command.add_argument(
        "--database", type=Path, default=None, help="Metadata catalog for diagnostics."
    )
    add_all_pages(command)
    command.set_defaults(_gravity_handler=dispatch)


def dispatch(args: Any, object_input: Callable[[Any], Mapping[str, Any]]) -> Any:
    all_pages = bool(args.all_pages)
    max_pages = int(args.max_pages or (1_000 if all_pages else 5))
    max_items = int(args.max_items or (100_000 if all_pages else 200))
    return resolve_and_run(
        args.selector,
        client=runtime.build_client(),
        workspace=load_workspace(),
        supplied_input=object_input(args.input),
        parameters=parse_parameter_assignments(args.parameters),
        app=args.app,
        start=args.start,
        end=args.end,
        read=runtime.call_read,
        read_all=all_pages,
        max_pages=max_pages,
        max_items=max_items,
        metadata_database=args.database,
    )


__all__ = ["add_resolver_command", "dispatch"]
