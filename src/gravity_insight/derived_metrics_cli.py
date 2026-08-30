"""Offline CLI bridge for the derived-metrics sub-contract."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .derived_metrics import derive_metrics_request


COMMAND = "derive"


def add_derived_metrics_command(commands: Any) -> None:
    from .find_input import add_input

    command = commands.add_parser(
        COMMAND,
        help="Apply caller-bound ratio, share, change, or reconciliation locally.",
    )
    command.set_defaults(
        network_required=False,
        result_output_fail_closed=True,
        local_command_handler=run_derived_metrics_args,
    )
    add_input(command, required=True)


def run_derived_metrics_command(
    value: str,
    parse_object: Any,
) -> dict[str, Any]:
    return derive_metrics_request(parse_object(value))


def run_derived_metrics_args(args: Any) -> dict[str, Any]:
    from .find_input import object_input

    request = (
        dict(args.input)
        if isinstance(args.input, Mapping)
        else object_input(args.input)
    )
    return derive_metrics_request(request)


__all__ = [
    "COMMAND",
    "add_derived_metrics_command",
    "run_derived_metrics_args",
    "run_derived_metrics_command",
]
