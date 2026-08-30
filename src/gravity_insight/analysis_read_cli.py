"""Parser registration for Analysis catalogs, reads, and local products."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .analysis_query_batch_cli import add_analysis_query_commands
from .capability_cli import add_deepening_commands
from .dashboard_snapshot_cli import add_dashboard_commands
from .domains import (
    ANALYSIS_AUXILIARY_OPERATIONS,
    ANALYSIS_DETAIL_OPERATIONS,
    ANALYSIS_REPORT_CONFIG_OPERATIONS,
    ANALYSIS_TEMPLATE_OPERATIONS,
    ANALYSIS_VALUE_OPERATIONS,
)
from .metadata_cli import add_metadata_commands
from .saved_analysis_cli import add_saved_analysis_commands
from .segment_spec_cli import add_segment_commands
from .user_detail_aggregate_cli import add_user_detail_aggregate_command
from .user_journey_cli import add_user_journey_command


def add_analysis_commands(
    commands: Any,
    add_input: Callable[..., None],
    add_pagination: Callable[..., None],
    concurrency: Callable[[str], int],
    positive_int: Callable[[str], int],
    add_query_shortcuts: Callable[..., None],
) -> None:
    apps_commands, _ = add_metadata_commands(
        commands, concurrency, add_input, add_pagination
    )
    analysis_commands = add_saved_analysis_commands(commands, positive_int)
    _add_metadata_commands(
        apps_commands,
        analysis_commands,
        add_input,
        add_pagination,
        concurrency,
    )
    add_analysis_query_commands(
        analysis_commands, add_input, add_query_shortcuts, concurrency
    )
    add_user_journey_command(analysis_commands, concurrency, positive_int)
    add_user_detail_aggregate_command(analysis_commands, add_input, concurrency)
    add_segment_commands(analysis_commands, add_input, add_pagination)
    _add_read_commands(
        analysis_commands,
        add_input,
        add_pagination,
        concurrency,
        positive_int,
    )


def _add_metadata_commands(
    apps_commands: Any,
    analysis_commands: Any,
    add_input: Callable[..., None],
    add_pagination: Callable[..., None],
    concurrency: Callable[[str], int],
) -> None:
    analysis_metadata = analysis_commands.add_parser("metadata")
    analysis_metadata.add_argument("--app-id", required=True)
    add_input(analysis_metadata)
    add_deepening_commands(apps_commands, analysis_commands, concurrency)
    analysis_segments = analysis_commands.add_parser("segments")
    analysis_segments.add_argument("--app-id", required=True)
    analysis_segments.add_argument(
        "--experimental",
        action="store_true",
        help="allow the operation only when the registry marks it experimental",
    )
    add_input(analysis_segments)
    add_pagination(analysis_segments)


def _add_typed_read_command(
    commands: Any,
    name: str,
    help_text: str,
    choices: Any,
    add_input: Callable[..., None],
    add_pagination: Callable[..., None],
    *,
    required_input: bool,
    paginated: bool,
    fields: bool = False,
) -> None:
    command = commands.add_parser(name, help=help_text)
    command.add_argument("--kind", required=True, choices=sorted(choices))
    if fields:
        command.add_argument(
            "--fields",
            action="append",
            help="Comma-separated contracted response fields; may be repeated.",
        )
    add_input(command, required=required_input)
    if paginated:
        add_pagination(command)


def _add_read_commands(
    analysis_commands: Any,
    add_input: Callable[..., None],
    add_pagination: Callable[..., None],
    concurrency: Callable[[str], int],
    positive_int: Callable[[str], int],
) -> None:
    _add_typed_read_command(
        analysis_commands,
        "report-config",
        "List or read a saved Analysis configuration.",
        ANALYSIS_REPORT_CONFIG_OPERATIONS,
        add_input,
        add_pagination,
        required_input=True,
        paginated=True,
    )
    add_dashboard_commands(
        analysis_commands, add_input, add_pagination, concurrency, positive_int
    )
    _add_typed_read_command(
        analysis_commands,
        "values",
        "Read enumerable user or event property values.",
        ANALYSIS_VALUE_OPERATIONS,
        add_input,
        add_pagination,
        required_input=True,
        paginated=False,
    )
    analysis_users = analysis_commands.add_parser(
        "users", help="Read the account member directory."
    )
    add_input(analysis_users)
    add_pagination(analysis_users)
    for name, help_text, choices, required_input, fields in (
        (
            "templates",
            "Read Analysis template subjects or template rows.",
            ANALYSIS_TEMPLATE_OPERATIONS,
            False,
            False,
        ),
        (
            "auxiliary",
            "Read hidden properties or task event catalogs.",
            ANALYSIS_AUXILIARY_OPERATIONS,
            True,
            False,
        ),
        (
            "detail",
            "Read order, monetization, user, event, or postback detail.",
            ANALYSIS_DETAIL_OPERATIONS,
            True,
            True,
        ),
    ):
        _add_typed_read_command(
            analysis_commands,
            name,
            help_text,
            choices,
            add_input,
            add_pagination,
            required_input=required_input,
            paginated=True,
            fields=fields,
        )


__all__ = ["add_analysis_commands"]
