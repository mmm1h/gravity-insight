"""CLI registration for governed metadata-template lifecycle actions."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from . import runtime
from .metadata_template_mutation import (
    metadata_template_mutation_schema,
    run_metadata_template_mutation,
)


def add_metadata_template_commands(
    commands: Any, add_input: Callable[..., Any]
) -> None:
    templates = commands.add_parser(
        "property-templates",
        help="Preview or execute marker-or-owner governed metadata-template writes.",
    )
    actions = templates.add_subparsers(
        dest="metadata_template_command", required=True
    )
    schema = actions.add_parser(
        "schema", help="Print the offline metadata-template action contract."
    )
    schema.set_defaults(network_required=False, _gravity_handler=_schema)
    mutate = actions.add_parser(
        "mutate", help="Run one exact template action from a JSON input object."
    )
    mutate.add_argument(
        "--action", required=True,
        choices=sorted(metadata_template_mutation_schema()["actions"]),
    )
    add_input(mutate, required=True)
    mode = mutate.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--dry-run", dest="metadata_template_dry_run", action="store_true"
    )
    mode.add_argument(
        "--execute", dest="metadata_template_execute", action="store_true"
    )
    mutate.set_defaults(network_required=False, _gravity_handler=_mutate)


def _schema(_args: Any, _object_input: Any) -> dict[str, Any]:
    return metadata_template_mutation_schema()


def _mutate(
    args: Any, object_input: Callable[[Any], Mapping[str, Any]]
) -> dict[str, Any]:
    return run_metadata_template_mutation(
        runtime.build_client(), args.action, object_input(args.input),
        execute=bool(args.metadata_template_execute),
    )


__all__ = ["add_metadata_template_commands"]
