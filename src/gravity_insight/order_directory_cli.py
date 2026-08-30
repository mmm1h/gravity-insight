"""CLI boundary for the bounded Order Directory product."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import runtime
from .errors import InputValidationError
from .workspace import load_workspace
from .workspace_app import resolve_workspace_app
from .actionable_error_values import actual_value


def add_order_directory_command(
    order_commands: Any,
    concurrency_parser: Callable[[str], int],
    positive_int_parser: Callable[[str], int],
) -> None:
    """Register ``analysis order directory`` as a JSON-only product."""

    directory = order_commands.add_parser(
        "directory", help="Read one complete bounded daily order directory."
    )
    directory.add_argument("--app", required=True)
    directory.add_argument("--date", required=True)
    directory.add_argument("--concurrency", type=concurrency_parser, default=6)
    directory.add_argument("--max-pages", type=positive_int_parser, default=1_000)
    directory.add_argument("--max-items", type=positive_int_parser, default=100_000)
    directory.add_argument(
        "--output", type=_output_file,
        help="Write the complete JSON result to a local file.",
    )
    directory.set_defaults(_gravity_handler=dispatch_order_directory)


def prepare_order_directory_request(args: Any) -> tuple[str, str]:
    """Validate and resolve a request without constructing a client."""

    from .order_directory import validate_order_directory_request

    if not isinstance(args.app, str) or not args.app.strip():
        raise InputValidationError(
            f"actual value: {actual_value(args.app)}; " + ("--app must be a non-empty workspace alias or positive id"), field="app"
        )
    if getattr(args, "output", None) is not None:
        _output_file(args.output)
    options = {
        "max_workers": args.concurrency,
        "max_pages": args.max_pages,
        "max_items": args.max_items,
    }
    validate_order_directory_request(1, args.date, **options)
    app_id = resolve_workspace_app(load_workspace(), args.app)
    canonical = validate_order_directory_request(app_id, args.date, **options)
    return canonical[0], canonical[1]


def dispatch_order_directory(args: Any, _object_input: Any) -> dict[str, Any]:
    """Execute only after local input and workspace preflight succeeds."""

    from .order_cli import reject_order_dry_run

    reject_order_dry_run(args)
    app_id, date = prepare_order_directory_request(args)
    from .order_directory import order_directory

    return order_directory(
        runtime.build_client(),
        app_id,
        date,
        max_workers=args.concurrency,
        max_pages=args.max_pages,
        max_items=args.max_items,
    )


def _output_file(value: str) -> str:
    """Validate a local JSON destination without creating it."""

    selected = value.strip()
    if not selected or selected == "-" or "\x00" in selected:
        raise ValueError("output must be a non-empty local file path")
    path = Path(selected)
    if path.exists() and path.is_dir():
        raise ValueError("output must be a local file path, not a directory")
    ancestor = path.parent
    while not ancestor.exists() and ancestor != ancestor.parent:
        ancestor = ancestor.parent
    if ancestor.exists() and not ancestor.is_dir():
        raise ValueError("output parent must be a local directory")
    return selected


__all__ = [
    "add_order_directory_command",
    "dispatch_order_directory",
    "prepare_order_directory_request",
]
