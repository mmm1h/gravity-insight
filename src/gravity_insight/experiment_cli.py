"""Offline CLI for Experiment Proposal, Outcome Handoff, and evaluation."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any


def add_experiment_commands(commands: Any, add_input: Callable[..., None]) -> Any:
    experiment = commands.add_parser(
        "experiment",
        help="Compile an Experiment Proposal, independent Outcome Handoff, or evaluation.",
    )
    actions = experiment.add_subparsers(dest="experiment_command", required=True)
    propose = actions.add_parser("propose")
    add_input(propose, required=True)
    propose.set_defaults(network_required=False, _gravity_handler=dispatch)
    outcome = actions.add_parser("outcome-handoff")
    add_input(outcome, required=True)
    outcome.set_defaults(network_required=False, _gravity_handler=dispatch)
    evaluate = actions.add_parser("evaluate")
    add_input(evaluate, required=True)
    evaluate.set_defaults(network_required=False, _gravity_handler=dispatch)
    return experiment


def dispatch(
    args: Any, object_input: Callable[[Any], Mapping[str, Any]]
) -> dict[str, Any]:
    from .experiment_handoff import ExperimentHandoffService

    request = object_input(args.input)
    service = ExperimentHandoffService()
    if args.experiment_command == "propose":
        return service.propose(request)
    if args.experiment_command == "outcome-handoff":
        return service.outcome_handoff(request)
    return service.evaluate(request)


__all__ = ["add_experiment_commands", "dispatch"]
