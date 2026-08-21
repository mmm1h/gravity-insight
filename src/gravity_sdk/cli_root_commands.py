"""Small registration router for independent root command families."""

from __future__ import annotations

from typing import Any, Callable

from .agent import add_agent_command
from .agent_catalog import add_agent_catalog_command
from .find import add_operation_commands
from .find_input import add_input
from .journey_cli import add_journey_commands
from .receipt_cli import add_receipt_commands
from .derived_metrics_cli import add_derived_metrics_command


def add_root_commands(
    commands: Any,
    agent_limit: Callable[[str], int],
    operation_limit: Callable[[str], int],
    catalog_limit: Callable[[str], int],
    client_factory: Callable[[Any], Any],
) -> None:
    add_agent_command(commands, agent_limit)
    add_agent_catalog_command(commands, catalog_limit, client_factory)
    add_operation_commands(commands, operation_limit)
    add_receipt_commands(commands)
    add_derived_metrics_command(commands)
    add_journey_commands(commands, add_input)


def dispatch_root_command(args: Any) -> Any:
    handler = getattr(args, "local_command_handler", None)
    if callable(handler):
        return handler(args)
    raise ValueError("choose --dry-run or a command")


__all__ = ["add_root_commands", "dispatch_root_command"]
