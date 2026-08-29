"""Thin CLI surface for reusable Journey inspection and execution."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

def add_journey_commands(commands: Any, add_input: Callable[..., None]) -> Any:
    journey = commands.add_parser(
        "journey", help="Describe, assess, or run an exact governed Journey."
    )
    actions = journey.add_subparsers(dest="journey_command", required=True)
    listed = actions.add_parser("list")
    listed.set_defaults(network_required=False, _gravity_handler=dispatch)
    verify = actions.add_parser("verify")
    verify.set_defaults(network_required=False, _gravity_handler=dispatch)
    describe = actions.add_parser("describe")
    describe.add_argument("journey_id")
    describe.set_defaults(network_required=False, _gravity_handler=dispatch)
    can_run = actions.add_parser("can-run")
    can_run.add_argument("journey_id")
    add_input(can_run)
    can_run.set_defaults(network_required=False, _gravity_handler=dispatch)
    impact = actions.add_parser("impact")
    add_input(impact, required=True)
    impact.set_defaults(network_required=False, _gravity_handler=dispatch)
    run = actions.add_parser("run")
    run.add_argument("journey_id")
    add_input(run, required=True)
    run.set_defaults(network_required=False, _gravity_handler=dispatch)
    return journey


def dispatch(
    args: Any, object_input: Callable[[Any], Mapping[str, Any]]
) -> dict[str, Any]:
    from .sdk import GravitySDK
    from .workspace import load_workspace

    workspace = load_workspace(getattr(args, "workspace", None))
    sdk = (
        GravitySDK.from_env(workspace=workspace, attempts=1)
        if args.journey_command in {"can-run", "run"}
        else GravitySDK(workspace=workspace)
    )
    service = sdk.journeys
    if args.journey_command == "list":
        return service.list()
    if args.journey_command == "verify":
        return service.verify()
    if args.journey_command == "describe":
        return service.describe(args.journey_id)
    inputs = object_input(args.input)
    if args.journey_command == "impact":
        return service.impact(inputs)
    if args.journey_command == "can-run":
        return service.can_run(args.journey_id, inputs)
    return service.run(args.journey_id, inputs)


__all__ = ["add_journey_commands", "dispatch"]
