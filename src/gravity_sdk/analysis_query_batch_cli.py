"""Registration and dispatch hooks for the compact Analysis Query Batch v1."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from .analysis_query_batch import run_analysis_query_batch
from .analysis_spec_cli import add_analysis_query_arguments
from .errors import InputValidationError


_SCALAR_QUERY_ARGUMENTS = (
    "dry_run",
    "kind",
    "experimental",
    "app_id",
    "media",
    "start",
    "end",
    "time_dim",
    "dimensions",
    "metrics",
    "multi_days",
    "parent_id",
    "spec",
    "app",
    "apps",
    "query_spec_dry_run",
    "spec_schema",
    "compare_start",
    "compare_end",
    "compare_concurrency",
)


def add_analysis_query_commands(
    analysis_commands: Any,
    add_input: Callable[..., None],
    add_shortcuts: Callable[[Any], None],
    concurrency_type: Callable[[str], int],
) -> Any:
    """Register the compatible scalar query and its compact batch child."""

    parser = analysis_commands.add_parser("query")
    add_analysis_query_arguments(parser, add_input, add_shortcuts, concurrency_type)
    add_analysis_query_batch_subcommand(parser, add_input, concurrency_type)
    return parser


def add_analysis_query_batch_command(
    commands: Any,
    add_input: Callable[..., None],
    concurrency_type: Callable[[str], int],
    *,
    handler: Callable[[Any, Any], Any] | None = None,
) -> Any:
    """Register ``analysis query batch`` under caller-owned subcommands."""

    parser = commands.add_parser(
        "batch",
        help="Execute up to 32 independent compact Analysis specs through Plan v1.",
    )
    add_input(parser, required=True)
    parser.add_argument(
        "--concurrency",
        type=concurrency_type,
        default=6,
        help="Plan outer worker budget (default: 6, maximum: 24).",
    )
    parser.add_argument(
        "--dry-run",
        dest="analysis_query_batch_dry_run",
        action="store_true",
        help="Compile every spec and run complete Plan preflight without execution.",
    )
    if handler is not None:
        parser.set_defaults(_gravity_handler=handler)
    return parser


def add_analysis_query_batch_subcommand(
    query_parser: Any,
    add_input: Callable[..., None],
    concurrency_type: Callable[[str], int],
) -> Any:
    """Attach the batch namespace to the backwards-compatible query parser."""

    commands = query_parser.add_subparsers(dest="analysis_query_command")
    return add_analysis_query_batch_command(
        commands,
        add_input,
        concurrency_type,
        handler=dispatch_analysis_query_batch,
    )


def dispatch_analysis_query_batch(
    args: Any,
    object_input: Callable[[Any], Mapping[str, Any]],
) -> dict[str, Any]:
    """Bind one workspace and lazy SDK facade for the product CLI."""

    from .sdk import GravitySDK
    from .workspace import load_workspace

    workspace = load_workspace(getattr(args, "workspace", None))
    return run_analysis_query_batch_command(
        args,
        sdk=GravitySDK.from_env(workspace=workspace),
        object_input=object_input,
    )


def run_analysis_query_batch_command(
    args: Any,
    *,
    sdk: Any,
    object_input: Callable[[Any], Mapping[str, Any]],
) -> dict[str, Any]:
    """Decode one object, then delegate validation or execution to the SDK facade."""

    selected = [
        name for name in _SCALAR_QUERY_ARGUMENTS if getattr(args, name, None)
    ]
    if selected:
        raise InputValidationError(
            "analysis query batch cannot use scalar query arguments",
            field="batch",
            next_action=(
                "Move batch options after `batch` and remove scalar-only query "
                "flags: " + ", ".join(selected)
            ),
        )
    value = args.input
    if not isinstance(value, Mapping):
        value = object_input(value)
    return run_analysis_query_batch(
        sdk,
        value,
        workspace=sdk.workspace,
        max_workers=args.concurrency,
        dry_run=bool(getattr(args, "analysis_query_batch_dry_run", False)),
    )


__all__ = [
    "add_analysis_query_commands",
    "add_analysis_query_batch_command",
    "add_analysis_query_batch_subcommand",
    "dispatch_analysis_query_batch",
    "run_analysis_query_batch_command",
]
