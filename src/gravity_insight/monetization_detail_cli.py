"""CLI boundary for the governed Monetization Detail product."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import runtime
from .errors import InputValidationError
from .find_input import load_json_input
from .workspace import load_workspace
from .workspace_app import resolve_workspace_app
from .actionable_error_values import actual_value


def add_monetization_detail_command(
    analysis_commands: Any,
    concurrency_parser: Callable[[str], int],
    positive_int_parser: Callable[[str], int],
) -> None:
    """Register ``analysis monetization detail`` as a closed JSON product."""

    monetization = analysis_commands.add_parser(
        "monetization", help="Run governed complete monetization reads."
    )
    commands = monetization.add_subparsers(
        dest="monetization_command", required=True
    )
    detail = commands.add_parser(
        "detail", help="Read one complete registered daily monetization detail."
    )
    detail.add_argument("--app", required=True)
    detail.add_argument("--date", required=True)
    detail.add_argument("--field", action="append")
    detail.add_argument("--global-conditions")
    detail.add_argument("--cond-logic", choices=("AND", "OR"), default="AND")
    detail.add_argument("--local-conditions")
    detail.add_argument("--local-cond-logic", choices=("AND", "OR"), default="AND")
    detail.add_argument("--order-by")
    detail.add_argument("--segment-id")
    detail.add_argument("--tmp-segment-id")
    detail.add_argument("--concurrency", type=concurrency_parser, default=6)
    detail.add_argument("--max-pages", type=positive_int_parser, default=1_000)
    detail.add_argument("--max-items", type=positive_int_parser, default=100_000)
    detail.add_argument(
        "--output",
        type=_output_file,
        help="Write the complete registered JSON result to a local file.",
    )
    detail.set_defaults(_gravity_handler=dispatch_monetization_detail)


def prepare_monetization_detail_request(
    args: Any, _object_input: Callable[[Any], Any] | None = None
) -> tuple[str, str, dict[str, Any]]:
    """Validate and resolve a request without constructing a client."""

    from .monetization_detail import validate_monetization_detail_request
    from .monetization_projection import SAFE_ROW_FIELDS
    from .monetization_query import normalize_monetization_query

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
    validate_monetization_detail_request(1, args.date, **options)
    app_id = resolve_workspace_app(load_workspace(), args.app)
    canonical = validate_monetization_detail_request(app_id, args.date, **options)
    query_options = {
        "fields": tuple(args.field or SAFE_ROW_FIELDS),
        "global_conditions": _array_input(args.global_conditions)
        if args.global_conditions else (),
        "cond_logic": args.cond_logic,
        "local_conditions": _array_input(args.local_conditions)
        if args.local_conditions else (),
        "local_cond_logic": args.local_cond_logic,
        "order_by": _array_input(args.order_by) if args.order_by else (),
        "segment_id": args.segment_id,
        "tmp_segment_id": args.tmp_segment_id,
    }
    normalize_monetization_query(**query_options)
    return canonical[0], canonical[1], query_options


def dispatch_monetization_detail(
    args: Any, object_input: Callable[[Any], Any]
) -> dict[str, Any]:
    """Execute only after local input and workspace preflight succeeds."""

    if bool(getattr(args, "dry_run", False)):
        raise InputValidationError(
            f"actual value: {actual_value(getattr(args, 'dry_run', False))}; --dry-run "
            "cannot be combined with a command",
            field="dry_run",
            next_action="Omit --dry-run or omit the conflicting command, then retry.",
        )
    app_id, date, query_options = prepare_monetization_detail_request(
        args, object_input
    )
    from .monetization_detail import monetization_detail

    return monetization_detail(
        runtime.build_client(),
        app_id,
        date,
        **query_options,
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


def _array_input(value: Any) -> list[Any]:
    selected = load_json_input(value)
    if not isinstance(selected, list):
        raise InputValidationError(
            "structured monetization options must be a JSON array",
            field="input",
        )
    return selected


__all__ = [
    "add_monetization_detail_command",
    "dispatch_monetization_detail",
    "prepare_monetization_detail_request",
]
