"""Explicit CLI confirmation surface for the R12-A reference Action."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from .errors import InputValidationError
from .host_effects import host_source


def add_action_commands(commands: Any, add_input: Callable[..., None]) -> Any:
    action = commands.add_parser(
        "action", help="Preview or execute one exact governed Action Plan."
    )
    resources = action.add_subparsers(dest="action_resource", required=True)
    segment = resources.add_parser(
        "segment-update", help="Update Segment name/remark through Action Plan."
    )
    phases = segment.add_subparsers(dest="action_command", required=True)
    preview = phases.add_parser("preview")
    add_input(preview, required=True)
    preview.add_argument("--ttl-seconds", type=int, default=900)
    preview.set_defaults(_gravity_handler=dispatch)
    execute = phases.add_parser("execute")
    execute.add_argument("--plan-id", required=True)
    execute.add_argument("--confirm-plan", required=True)
    execute.add_argument("--preview-fingerprint", required=True)
    add_input(execute, required=True)
    execute.set_defaults(_gravity_handler=dispatch)
    return action


def dispatch(
    args: Any, object_input: Callable[[Any], Mapping[str, Any]]
) -> dict[str, Any]:
    from .sdk import GravitySDK
    from .workspace import load_workspace

    request = object_input(args.input)
    sdk = GravitySDK.from_env(
        workspace=load_workspace(getattr(args, "workspace", None)), attempts=1
    )
    service = sdk.actions
    if args.action_command == "preview":
        authorization = host_source(
            "user", "authorization", service.authorization_value(request)
        )
        return service.preview_segment_update(
            request,
            authorization=authorization,
            ttl_seconds=args.ttl_seconds,
        )
    if args.confirm_plan != args.plan_id:
        raise InputValidationError(
            "actual value: --confirm-plan does not equal --plan-id; allowed value: exact explicit confirmation of the reviewed Action Plan",
            field="confirm_plan",
            code="ACTION_CONFIRMATION_REQUIRED",
            next_action="Review the preview again and pass its exact plan_id to both flags.",
        )
    confirmation = host_source(
        "user",
        "authorization",
        service.confirmation_value(args.plan_id, args.preview_fingerprint),
    )
    return service.execute(
        args.plan_id,
        request,
        confirmation=confirmation,
    )


__all__ = ["add_action_commands", "dispatch"]
