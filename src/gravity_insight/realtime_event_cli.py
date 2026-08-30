"""CLI registration for governed realtime-event warehousing writes."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from . import runtime
from .realtime_event_mutation import (
    realtime_event_mutation_schema,
    run_realtime_event_mutation,
)


def add_realtime_event_commands(
    commands: Any, add_input: Callable[..., Any]
) -> None:
    group = commands.add_parser(
        "realtime-event",
        help="Preview or execute the App realtime-event warehousing window.",
    )
    actions = group.add_subparsers(dest="realtime_event_command", required=True)
    schema = actions.add_parser(
        "schema", help="Print the offline realtime-event mutation contract."
    )
    schema.set_defaults(network_required=False, _gravity_handler=_schema)
    mutate = actions.add_parser(
        "update", help="Set one App warehousing window from a JSON input object."
    )
    add_input(mutate, required=True)
    mode = mutate.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", dest="realtime_event_dry_run", action="store_true")
    mode.add_argument("--execute", dest="realtime_event_execute", action="store_true")
    mutate.set_defaults(network_required=False, _gravity_handler=_mutate)


def _schema(_args: Any, _object_input: Any) -> dict[str, Any]:
    return realtime_event_mutation_schema()


def _mutate(
    args: Any, object_input: Callable[[Any], Mapping[str, Any]]
) -> dict[str, Any]:
    return run_realtime_event_mutation(
        runtime.build_client(),
        object_input(args.input),
        execute=bool(args.realtime_event_execute),
    )


__all__ = ["add_realtime_event_commands"]
