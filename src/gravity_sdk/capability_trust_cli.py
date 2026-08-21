"""Thin CLI surface for offline Capability Trust and impact services."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any


def add_capability_trust_commands(
    commands: Any, add_input: Callable[..., None]
) -> Any:
    capabilities = commands.add_parser(
        "capabilities",
        help="Evaluate current same-layer Capability Trust and dependency impact.",
    )
    actions = capabilities.add_subparsers(
        dest="capabilities_command", required=True
    )
    trust = actions.add_parser("trust")
    trust.add_argument(
        "identity_kind", choices=("operation", "product", "composite")
    )
    trust.add_argument("selector")
    trust.set_defaults(network_required=False, _gravity_handler=dispatch)
    validate = actions.add_parser("validate")
    add_input(validate, required=True)
    validate.set_defaults(network_required=False, _gravity_handler=dispatch)
    impact = actions.add_parser("impact")
    add_input(impact, required=True)
    impact.set_defaults(network_required=False, _gravity_handler=dispatch)
    return capabilities


def dispatch(
    args: Any, object_input: Callable[[Any], Mapping[str, Any]]
) -> dict[str, Any]:
    from .sdk import GravitySDK
    from .workspace import load_workspace

    workspace = load_workspace(getattr(args, "workspace", None))
    sdk = GravitySDK.from_env(workspace=workspace, attempts=1)
    service = sdk.capability_trust
    if args.capabilities_command == "trust":
        return service.trust(args.identity_kind, args.selector)
    request = object_input(args.input)
    if args.capabilities_command == "validate":
        return service.validate(request)
    return service.impact(request)


__all__ = ["add_capability_trust_commands", "dispatch"]
