"""CLI registration for the bounded business reporting composite."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from . import runtime
from .business_pulse import DEFAULT_PLATFORMS, business_pulse
from .company_usage import company_usage
from .errors import InputValidationError
from .result_output import output_file
from .workspace import load_workspace
from .workspace_app import resolve_workspace_app
from .report_cli import add_report_commands
from .actionable_error_values import actual_value


def add_business_pulse_command(
    commands: Any,
    concurrency_parser: Callable[[str], int],
    positive_int: Callable[[str], int],
) -> None:
    reports = commands.add_parser(
        "reports", help="Run bounded, governed reporting composites."
    )
    report_commands = reports.add_subparsers(dest="reports_command", required=True)
    pulse = report_commands.add_parser(
        "pulse", help="Read overview and business trends concurrently."
    )
    pulse.add_argument(
        "--app",
        action="append",
        required=True,
        help="Workspace App alias or positive id; repeat or comma-separate.",
    )
    pulse.add_argument("--start", required=True)
    pulse.add_argument("--end", required=True)
    pulse.add_argument(
        "--platform",
        action="append",
        choices=DEFAULT_PLATFORMS,
        help="Advertising platform; repeat. Defaults to all supported platforms.",
    )
    pulse.add_argument("--include-hourly", action="store_true")
    pulse.add_argument("--concurrency", type=concurrency_parser, default=6)
    pulse.add_argument("--max-pages", type=positive_int, default=5)
    pulse.add_argument("--max-items", type=positive_int, default=200)
    pulse.add_argument(
        "--output", type=output_file,
        help="Atomically write the complete JSON result to a local file.",
    )
    pulse.set_defaults(result_output_fail_closed=True)
    pulse.set_defaults(_gravity_handler=_dispatch_business_pulse)
    usage = report_commands.add_parser(
        "usage", help="Read the company daily resource-usage trend."
    )
    usage.add_argument("--max-pages", type=positive_int, default=1_000)
    usage.add_argument("--max-items", type=positive_int, default=100_000)
    usage.set_defaults(_gravity_handler=_dispatch_company_usage)
    add_report_commands(report_commands, positive_int, concurrency_parser)


def _dispatch_business_pulse(args: Any, _object_input: Any) -> dict[str, Any]:
    workspace = load_workspace()
    aliases = _split_apps(args.app)
    app_ids = [resolve_workspace_app(workspace, value) for value in aliases]
    return business_pulse(
        runtime.build_client(),
        app_ids,
        args.start,
        args.end,
        platforms=args.platform or DEFAULT_PLATFORMS,
        include_hourly=args.include_hourly,
        max_workers=args.concurrency,
        max_pages=args.max_pages,
        max_items=args.max_items,
    )


def _dispatch_company_usage(args: Any, _object_input: Any) -> dict[str, Any]:
    return company_usage(
        runtime.build_client(),
        max_pages=args.max_pages,
        max_items=args.max_items,
    )


def _split_apps(values: list[str]) -> list[str]:
    selected = [part.strip() for value in values for part in value.split(",")]
    result = [value for value in selected if value]
    if not result:
        raise InputValidationError(f"actual value: {actual_value(result)}; " + ("--app must select at least one App"), field="app")
    return result


__all__ = ["add_business_pulse_command"]
