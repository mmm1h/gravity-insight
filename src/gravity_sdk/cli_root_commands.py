"""Small registration router for independent root command families."""

from __future__ import annotations

from typing import Any, Callable

from .agent import add_agent_command
from .find import add_operation_commands
from .receipt_cli import add_receipt_commands


def add_root_commands(
    commands: Any,
    agent_limit: Callable[[str], int],
    operation_limit: Callable[[str], int],
) -> None:
    add_agent_command(commands, agent_limit)
    add_operation_commands(commands, operation_limit)
    add_receipt_commands(commands)


__all__ = ["add_root_commands"]
