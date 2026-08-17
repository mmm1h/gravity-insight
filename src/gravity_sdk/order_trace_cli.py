"""CLI boundary for the bounded Order Split Trace product."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from . import runtime
from .errors import InputValidationError
from .workspace import load_workspace
from .workspace_app import resolve_workspace_app
from .actionable_error_values import actual_value


def add_order_trace_command(
    order_commands: Any,
    concurrency_parser: Callable[[str], int],
    positive_int_parser: Callable[[str], int],
) -> None:
    """Register the ``trace`` member of the governed order family."""

    trace = order_commands.add_parser(
        "trace", help="Read split-order detail for one exact TraceID."
    )
    trace.add_argument("--app", required=True)
    trace.add_argument("--date", required=True)
    trace.add_argument("--trace-id", required=True)
    trace.add_argument("--concurrency", type=concurrency_parser, default=6)
    trace.add_argument("--max-pages", type=positive_int_parser, default=1_000)
    trace.add_argument("--max-items", type=positive_int_parser, default=100_000)
    trace.set_defaults(_gravity_handler=dispatch_order_trace)


def prepare_order_trace_request(args: Any) -> tuple[str, str, str]:
    """Validate and resolve a CLI request without constructing a client."""

    from .order_trace import validate_order_split_trace_request

    if not isinstance(args.app, str) or not args.app.strip():
        raise InputValidationError(
            f"actual value: {actual_value(args.app)}; " + ("--app must be a non-empty workspace alias or positive id"),
            field="app",
        )
    options = {
        "max_workers": args.concurrency,
        "max_pages": args.max_pages,
        "max_items": args.max_items,
    }
    validate_order_split_trace_request(1, args.date, args.trace_id, **options)
    app_id = resolve_workspace_app(load_workspace(), args.app)
    canonical = validate_order_split_trace_request(
        app_id, args.date, args.trace_id, **options
    )
    return canonical[0], canonical[1], canonical[2]


def dispatch_order_trace(args: Any, _object_input: Any) -> dict[str, Any]:
    """Execute only after local input and workspace preflight succeeds."""

    from .order_cli import reject_order_dry_run

    reject_order_dry_run(args)
    app_id, date, trace_id = prepare_order_trace_request(args)
    from .order_trace import order_split_trace

    return order_split_trace(
        runtime.build_client(),
        app_id,
        date,
        trace_id,
        max_workers=args.concurrency,
        max_pages=args.max_pages,
        max_items=args.max_items,
    )


__all__ = [
    "add_order_trace_command",
    "dispatch_order_trace",
    "prepare_order_trace_request",
]
