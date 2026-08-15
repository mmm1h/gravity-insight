"""Thin CLI registration for fixed analysis and App composite products."""

from __future__ import annotations

from typing import Any, Callable

from . import runtime
from .analysis_context import analysis_context
from .analysis_default_dictionary import analysis_default_dictionary
from .app_snapshot import app_snapshot
from .cli_limits import positive_int
from .order_cli import add_order_commands
from .monetization_detail_cli import add_monetization_detail_command
from .workspace import load_workspace
from .workspace_app import resolve_workspace_app


def add_deepening_commands(
    apps_commands: Any,
    analysis_commands: Any,
    concurrency_parser: Callable[[str], int],
) -> None:
    apps = apps_commands.add_parser(
        "snapshot", help="Read the fixed App governance snapshot concurrently."
    )
    _add_app_and_concurrency(apps, concurrency_parser)
    apps.set_defaults(_gravity_handler=_dispatch_app_snapshot)

    context = analysis_commands.add_parser(
        "context", help="Read the fixed Analysis vocabulary concurrently."
    )
    _add_app_and_concurrency(context, concurrency_parser)
    context.set_defaults(_gravity_handler=_dispatch_analysis_context)
    defaults = analysis_commands.add_parser(
        "defaults", help="Read the registered Analysis SDK default-value dictionary."
    )
    defaults.add_argument("--app", required=True)
    defaults.set_defaults(_gravity_handler=_dispatch_analysis_defaults)
    add_order_commands(analysis_commands, concurrency_parser, positive_int)
    add_monetization_detail_command(
        analysis_commands, concurrency_parser, positive_int
    )


def _add_app_and_concurrency(parser: Any, concurrency_parser: Any) -> None:
    parser.add_argument("--app", required=True)
    parser.add_argument("--concurrency", type=concurrency_parser, default=6)


def _dispatch_analysis_context(args: Any, _object_input: Any) -> dict[str, Any]:
    workspace = load_workspace()
    return analysis_context(
        runtime.build_client(),
        resolve_workspace_app(workspace, args.app),
        max_workers=args.concurrency,
    )


def _dispatch_analysis_defaults(args: Any, _object_input: Any) -> dict[str, Any]:
    workspace = load_workspace()
    return analysis_default_dictionary(
        runtime.build_client(), resolve_workspace_app(workspace, args.app)
    )


def _dispatch_app_snapshot(args: Any, _object_input: Any) -> dict[str, Any]:
    workspace = load_workspace()
    return app_snapshot(
        runtime.build_client(),
        resolve_workspace_app(workspace, args.app),
        max_workers=args.concurrency,
    )


__all__ = ["add_deepening_commands"]
