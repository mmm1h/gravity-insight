"""CLI boundary for the governed Monetization Detail product."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import runtime
from .errors import InputValidationError
from .workspace import load_workspace
from .workspace_app import resolve_workspace_app


def add_monetization_detail_command(
    analysis_commands: Any,
    concurrency_parser: Callable[[str], int],
    positive_int_parser: Callable[[str], int],
) -> None:
    """Register ``analysis monetization detail`` as a closed JSON product."""

    monetization = analysis_commands.add_parser(
        "monetization", help="Run governed identifier-free monetization reads."
    )
    commands = monetization.add_subparsers(
        dest="monetization_command", required=True
    )
    detail = commands.add_parser(
        "detail", help="Read one complete identifier-free daily monetization detail."
    )
    detail.add_argument("--app", required=True)
    detail.add_argument("--date", required=True)
    detail.add_argument("--concurrency", type=concurrency_parser, default=6)
    detail.add_argument("--max-pages", type=positive_int_parser, default=1_000)
    detail.add_argument("--max-items", type=positive_int_parser, default=100_000)
    detail.add_argument(
        "--output",
        type=_output_file,
        help="Write the complete identifier-free JSON result to a local file.",
    )
    detail.set_defaults(_gravity_handler=dispatch_monetization_detail)


def prepare_monetization_detail_request(args: Any) -> tuple[str, str]:
    """Validate and resolve a request without constructing a client."""

    from .monetization_detail import validate_monetization_detail_request

    if not isinstance(args.app, str) or not args.app.strip():
        raise InputValidationError(
            "--app must be a non-empty workspace alias or positive id", field="app"
        )
    if getattr(args, "output", None) is not None:
        _output_file(args.output)
    options = {
        "max_workers": args.concurrency,
        "max_pages": args.max_pages,
        "max_items": args.max_items,
    }
    validate_monetization_detail_request(1, args.date, **options)
    app_id = resolve_workspace_app(load_workspace(), args.app)
    canonical = validate_monetization_detail_request(app_id, args.date, **options)
    return canonical[0], canonical[1]


def dispatch_monetization_detail(
    args: Any, _object_input: Any
) -> dict[str, Any]:
    """Execute only after local input and workspace preflight succeeds."""

    if bool(getattr(args, "dry_run", False)):
        raise InputValidationError(
            "--dry-run cannot be combined with a command", field="dry_run"
        )
    app_id, date = prepare_monetization_detail_request(args)
    from .monetization_detail import monetization_detail

    return monetization_detail(
        runtime.build_client(),
        app_id,
        date,
        max_workers=args.concurrency,
        max_pages=args.max_pages,
        max_items=args.max_items,
    )


def _output_file(value: str) -> str:
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
    "add_monetization_detail_command",
    "dispatch_monetization_detail",
    "prepare_monetization_detail_request",
]
