"""CLI registration for governed Kanban writes."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from . import runtime
from .kanban_mutation import kanban_mutation_schema, run_kanban_mutation


def add_kanban_commands(commands: Any, add_input: Callable[..., Any]) -> None:
    kanban = commands.add_parser(
        "kanban", help="Preview or execute marker-governed Kanban workspace writes."
    )
    actions = kanban.add_subparsers(dest="kanban_command", required=True)
    schema = actions.add_parser("schema", help="Print the offline Kanban mutation contract.")
    schema.set_defaults(network_required=False, _gravity_handler=_schema)
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


def _mutate(
    args: Any, object_input: Callable[[Any], Mapping[str, Any]]
) -> dict[str, Any]:
    return run_kanban_mutation(
        runtime.build_client(),
        args.action,
        object_input(args.input),
        execute=bool(args.kanban_execute),
    )


__all__ = ["add_kanban_commands"]
