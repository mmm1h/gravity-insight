"""CLI surface for compiling and executing registered semantic members."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
from typing import Any

from . import runtime
from .errors import InputValidationError
from .semantic_compose import (
    actual_value,
    compile_semantic_compose,
    run_semantic_compose,
    semantic_compose_input_schema,
)
from .workspace import load_workspace
from .workspace_app import resolve_workspace_app


def add_semantic_compose_commands(
    commands: Any,
    add_input: Callable[..., None],
) -> None:
    semantic = commands.add_parser(
        "semantic", help="Compile or execute registered semantic compositions."
    )
    subcommands = semantic.add_subparsers(dest="semantic_command", required=True)
    compose = subcommands.add_parser(
        "compose", help="Compile registered members to the governed Multidim product."
    )
    add_input(compose)
    compose.add_argument("--app", help="Workspace App alias or positive App id.")
    compose.add_argument("--workspace", help="gravity.toml or its directory.")
    offline = compose.add_mutually_exclusive_group()
    offline.add_argument(
        "--dry-run",
        dest="semantic_compose_dry_run",
        action="store_true",
        help="Compile and validate without constructing a client.",
    )
    offline.add_argument(
        "--input-schema",
        dest="semantic_compose_input_schema",
        action="store_true",
        help="Print registered definition and member references offline.",
    )
    compose.set_defaults(_gravity_handler=_handler())


def _handler() -> Callable[[Any, Any], Any]:
    def dispatch(args: Any, object_input: Callable[[Any], Mapping[str, Any]]) -> Any:
        return dispatch_semantic_compose(args, object_input)

    return dispatch


def dispatch_semantic_compose(
    args: Any,
    object_input: Callable[[Any], Mapping[str, Any]],
) -> dict[str, Any]:
    if bool(getattr(args, "dry_run", False)):
        raise _cli_error(
            "global --dry-run cannot be combined with semantic compose",
            "dry_run",
            actual_value(True),
            next_action="Place --dry-run after `gravity semantic compose` and retry.",
        )
    if bool(getattr(args, "semantic_compose_input_schema", False)):
        return semantic_compose_input_schema()
    app = getattr(args, "app", None)
    if app is None:
        raise _cli_error(
            "semantic compose requires an explicit App",
            "app",
            actual_value(app),
            next_action="Retry with `gravity semantic compose --app <name|id> ...`.",
        )
    workspace = load_workspace(getattr(args, "workspace", None))
    app_id = resolve_workspace_app(workspace, app)
    inputs = object_input(args.input)
    compiled = compile_semantic_compose(inputs, app_id=app_id)
    if bool(getattr(args, "semantic_compose_dry_run", False)):
        return compiled
    return run_semantic_compose(runtime.build_client(), inputs, app_id=app_id)


def _cli_error(
    message: str, field: str, actual: str, *, next_action: str
) -> InputValidationError:
    return InputValidationError(
        f"{message}; actual value {actual}", field=field, next_action=next_action
    )


__all__ = ["add_semantic_compose_commands", "dispatch_semantic_compose"]
