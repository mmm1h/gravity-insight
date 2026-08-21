"""Thin CLI surface for the single R01 Journey service."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from .actionable_error_values import actual_value
from .errors import InputValidationError
from .reference_journey_contract import JOURNEY_ID


def add_journey_commands(commands: Any, add_input: Callable[..., None]) -> Any:
    journey = commands.add_parser(
        "journey", help="Describe, assess, or run an exact governed Journey."
    )
    actions = journey.add_subparsers(dest="journey_command", required=True)
    describe = actions.add_parser("describe")
    describe.add_argument("journey_id")
    describe.set_defaults(network_required=False, _gravity_handler=dispatch)
    can_run = actions.add_parser("can-run")
    can_run.add_argument("journey_id")
    add_input(can_run, required=True)
    can_run.set_defaults(network_required=False, _gravity_handler=dispatch)
    run = actions.add_parser("run")
    run.add_argument("journey_id")
    add_input(run, required=True)
    run.set_defaults(network_required=False, _gravity_handler=dispatch)
    return journey


def dispatch(
    args: Any, object_input: Callable[[Any], Mapping[str, Any]]
) -> dict[str, Any]:
    if args.journey_id != JOURNEY_ID:
        raise InputValidationError(
            f"actual value: {actual_value(args.journey_id)}; journey_id must "
            "name the current exact R01 Journey",
            field="journey_id",
            next_action=(
                "Run `gravity journey describe " + JOURNEY_ID + "` and retry."
            ),
        )
    from .sdk import GravitySDK
    from .workspace import load_workspace

    workspace = load_workspace(getattr(args, "workspace", None))
    sdk = (
        GravitySDK.from_env(workspace=workspace, attempts=1)
        if args.journey_command == "run"
        else GravitySDK(workspace=workspace)
    )
    service = sdk.journeys
    if args.journey_command == "describe":
        return service.describe()
    inputs = object_input(args.input)
    return service.can_run(inputs) if args.journey_command == "can-run" else service.run(inputs)


__all__ = ["add_journey_commands", "dispatch"]
