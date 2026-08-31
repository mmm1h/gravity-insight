"""Small registration router for independent root command families."""

from __future__ import annotations

from typing import Any, Callable

from .agent import add_agent_command
from .agents.catalog import add_agent_catalog_command
from .capability_trust_cli import add_capability_trust_commands
from .context_cli import add_context_commands
from .find import add_operation_commands
from .find_input import add_input
from .journey_cli import add_journey_commands
from .receipt_cli import add_receipt_commands
from .derived_metrics_cli import add_derived_metrics_command
from .skill_cli import add_skill_commands
from .semantic_registry_cli import add_semantic_registry_commands
from .operator_model_cli import add_operator_model_commands
from .trusted_pack_cli import add_trusted_pack_commands
from .action_cli import add_action_commands
from .experiment_cli import add_experiment_commands
from .evidence_cli import add_evidence_commands


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
    add_capability_trust_commands(commands, add_input)
    add_skill_commands(commands)
    add_semantic_registry_commands(commands, add_input)
    add_operator_model_commands(commands, add_input)
    add_context_commands(commands, add_input)
    add_trusted_pack_commands(commands)
    add_action_commands(commands, add_input)
    add_experiment_commands(commands, add_input)
    add_evidence_commands(commands)


def dispatch_root_command(args: Any) -> Any:
    handler = getattr(args, "local_command_handler", None)
    if callable(handler):
        return handler(args)
    raise ValueError("choose --dry-run or a command")


__all__ = ["add_root_commands", "dispatch_root_command"]
