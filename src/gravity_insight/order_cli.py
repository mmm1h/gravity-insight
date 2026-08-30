"""Thin registration for the governed Analysis order product family."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .errors import InputValidationError
from .order_directory_cli import add_order_directory_command
from .order_trace_cli import add_order_trace_command


def add_order_commands(
    analysis_commands: Any,
    concurrency_parser: Callable[[str], int],
    positive_int_parser: Callable[[str], int],
) -> None:
    """Register bounded order products without growing the root CLI."""

    order = analysis_commands.add_parser(
        "order", help="Run bounded governed order products."
    )
    commands = order.add_subparsers(dest="order_command", required=True)
    add_order_directory_command(commands, concurrency_parser, positive_int_parser)
    add_order_trace_command(commands, concurrency_parser, positive_int_parser)


def reject_order_dry_run(args: Any) -> None:
    """Reject the root compatibility flag; order products have no preview mode."""

    if bool(getattr(args, "dry_run", False)):
        raise InputValidationError(
            "--dry-run cannot be combined with a command", field="dry_run", next_action="Omit --dry-run or omit the conflicting command, then retry."
        )


__all__ = ["add_order_commands", "reject_order_dry_run"]
