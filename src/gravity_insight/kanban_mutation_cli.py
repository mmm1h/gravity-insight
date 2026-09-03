"""CLI registration for governed Kanban writes."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
from typing import Any

from . import runtime
from .kanban_mutation import kanban_mutation_schema, run_kanban_mutation
from .kanban_limits import PREPARE_MAX_ITEMS, PREPARE_MAX_PAGES, PREPARE_MAX_WORKERS
from .workspace import load_workspace


def add_kanban_commands(commands: Any, add_input: Callable[..., Any]) -> None:
    kanban = commands.add_parser(
        "kanban", help="Preview or execute marker-governed Kanban workspace and report-association writes."
    )
    actions = kanban.add_subparsers(dest="kanban_command", required=True)
    schema = actions.add_parser("schema", help="Print the offline Kanban mutation contract.")
    schema.set_defaults(network_required=False, _gravity_handler=_schema)
    prepare = actions.add_parser(
        "prepare",
        help="Read and admit one complete desired board before its first write.",
    )
    add_input(prepare, required=True)
    prepare.add_argument("--max-pages", type=_pages, default=PREPARE_MAX_PAGES)
    prepare.add_argument("--max-items", type=_items, default=PREPARE_MAX_ITEMS)
    prepare.add_argument("--concurrency", type=_workers, default=6)
    # The dashboard parent recomputes credential needs from legacy fields after
    # nested parsing; this non-public sentinel keeps this read command online.
    prepare.set_defaults(
        kind="kanban_prepare",
        network_required=True,
        _gravity_handler=_prepare,
    )
    mutate = actions.add_parser(
        "mutate", help="Run one exact Kanban action from a JSON input object."
    )
    mutate.add_argument("--action", required=True, choices=sorted(kanban_mutation_schema()["actions"]))
    add_input(mutate, required=True)
    mode = mutate.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", dest="kanban_dry_run", action="store_true")
    mode.add_argument("--execute", dest="kanban_execute", action="store_true")
    mutate.set_defaults(_gravity_handler=_mutate)


def _schema(_args: Any, _object_input: Any) -> dict[str, Any]:
    return kanban_mutation_schema()


def _prepare(
    args: Any, object_input: Callable[[Any], Mapping[str, Any]]
) -> dict[str, Any]:
    from .kanban_board_plan import prepare_kanban_board

    return prepare_kanban_board(
        runtime.build_client(),
        object_input(args.input),
        workspace=load_workspace(getattr(args, "workspace", None)),
        max_pages=args.max_pages,
        max_items=args.max_items,
        max_workers=args.concurrency,
    )


def _mutate(
    args: Any, object_input: Callable[[Any], Mapping[str, Any]]
) -> dict[str, Any]:
    return run_kanban_mutation(
        runtime.build_client(),
        args.action,
        object_input(args.input),
        execute=bool(args.kanban_execute),
    )


def _bounded(value: str, maximum: int, label: str) -> int:
    parsed = int(value)
    if not 1 <= parsed <= maximum:
        raise argparse.ArgumentTypeError(
            f"{label} must be between 1 and {maximum}"
        )
    return parsed


def _pages(value: str) -> int:
    return _bounded(value, PREPARE_MAX_PAGES, "max pages")


def _items(value: str) -> int:
    return _bounded(value, PREPARE_MAX_ITEMS, "max items")


def _workers(value: str) -> int:
    return _bounded(value, PREPARE_MAX_WORKERS, "concurrency")


__all__ = ["add_kanban_commands"]
