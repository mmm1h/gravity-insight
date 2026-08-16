"""CLI registration and dispatch for governed local metadata products."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .actionable_error_values import actual_value
from .cli_limits import metadata_limit, nonnegative_int
from .domains import ANALYSIS_METADATA_OPERATIONS, ANALYSIS_PAGINATED_OPERATIONS
from .errors import InputValidationError
from .find_metadata import search_metadata
from .metadata_lineage import (
    add_table_lineage_commands,
    search_table_lineage,
)
from .metadata_onboarding import (
    DEFAULT_MAX_PAGES,
    app_sync_pages,
    estimate_app_sync,
    sync_app,
)
from .metadata_status import max_age_hours, metadata_status
from . import metadata_sync
from . import metadata_vocabulary as vocabulary
from .runtime import call_batch


def add_metadata_commands(
    commands: Any,
    concurrency_parser: Any,
    input_adder: Any,
    all_pages_adder: Any,
) -> tuple[Any, Any]:
    apps = commands.add_parser("apps")
    apps_commands = apps.add_subparsers(dest="apps_command", required=True)
    apps_list = apps_commands.add_parser("list")
    input_adder(apps_list)
    all_pages_adder(apps_list)
    metadata = commands.add_parser(
        "metadata", help="Synchronize and search governed local Gravity metadata."
    )
    metadata_commands = metadata.add_subparsers(
        dest="metadata_command", required=True
    )
    sync = metadata_commands.add_parser(
        "sync", help="Download application metadata into a local SQLite catalog."
    )
    scope = sync.add_mutually_exclusive_group(required=True)
    scope.add_argument(
        "--all-apps", action="store_true",
        help="Synchronize every application visible to the current account.",
    )
    scope.add_argument(
        "--app-id",
        help="Synchronize only this App's four Analysis metadata object kinds.",
    )
    sync.add_argument(
        "--database", type=Path, default=None,
        help="Override the private per-user SQLite catalog path.",
    )
    sync.add_argument("--concurrency", type=concurrency_parser, default=8)
    sync.add_argument(
        "--max-pages", type=app_sync_pages, default=None,
        help=(
            "Single-App page cap per paginated operation (1..8; default 2). "
            "The logical request bound is 3*max-pages+1."
        ),
    )
    sync.add_argument(
        "--dry-run", dest="metadata_sync_dry_run", action="store_true",
        help=(
            "Report the single-App request bound without reading Gravity or "
            "writing SQLite."
        ),
    )
    _add_status_command(metadata_commands)
    _add_search_commands(metadata_commands)
    vocabulary.add_vocabulary_command(
        metadata_commands, metadata_limit, nonnegative_int
    )
    add_table_lineage_commands(metadata_commands, sync)
    return apps_commands, metadata_commands


def run_metadata_command(args: Any, client_builder: Any) -> dict[str, Any]:
    if args.metadata_command == "sync":
        return _run_sync(args, client_builder)
    if args.metadata_command == "status":
        return metadata_status(
            database=args.database,
            app_id=args.app_id,
            max_age_hours=args.max_age_hours,
        )
    if args.metadata_command == "tables":
        return search_table_lineage(
            args.query,
            database=args.database,
            limit=args.limit,
            offset=args.offset,
        )
    if args.metadata_command == "vocabulary":
        return vocabulary.run_vocabulary_search(args)
    kind = getattr(args, "kind", None) or {
        "search": "all", "events": "event", "properties": "property"
    }[args.metadata_command]
    return search_metadata(
        args.query,
        database=args.database,
        app_id=getattr(args, "app_id", None),
        kind=kind,
        limit=args.limit,
        offset=args.offset,
    )


def run_analysis_metadata(
    args: Any,
    client_builder: Any,
    object_input: Any,
) -> Any:
    client = client_builder(args)
    supplied = object_input(args.input)
    keyed_input = any(
        operation_id in supplied for operation_id in ANALYSIS_METADATA_OPERATIONS
    )
    requests: list[dict[str, Any]] = []
    for operation_id in ANALYSIS_METADATA_OPERATIONS:
        operation_input = supplied.get(operation_id, {}) if keyed_input else supplied
        if not isinstance(operation_input, Mapping):
            raise InputValidationError(
                f"analysis metadata input for {operation_id} must be an object"
            )
        inputs = {"app_id": str(args.app_id), **dict(operation_input)}
        if operation_id in ANALYSIS_PAGINATED_OPERATIONS:
            inputs.setdefault("page", 1)
            inputs.setdefault("page_size", 2_000)
        inputs["app_id"] = str(args.app_id)
        requests.append(
            {"operation_id": operation_id, "inputs": inputs, "read_all": True}
        )
    return call_batch(client, requests, concurrency=4)


def _add_status_command(metadata_commands: Any) -> None:
    status = metadata_commands.add_parser(
        "status",
        help="Inspect local metadata coverage and freshness without network access.",
    )
    status.set_defaults(network_required=False)
    status.add_argument("--app-id")
    status.add_argument("--database", type=Path, default=None)
    status.add_argument(
        "--max-age-hours", type=max_age_hours, default=24,
        help="Mark App snapshots older than this threshold stale (default: 24).",
    )


def _add_search_commands(metadata_commands: Any) -> None:
    for name, help_text in (
        ("search", "Search applications, events, and properties offline."),
        ("events", "List or search synchronized events offline."),
        ("properties", "List or search synchronized properties offline."),
    ):
        query = metadata_commands.add_parser(name, help=help_text)
        query.set_defaults(network_required=False)
        query.add_argument("query", nargs="?", default="")
        query.add_argument("--app-id")
        query.add_argument("--database", type=Path, default=None)
        query.add_argument("--limit", type=metadata_limit, default=20)
        query.add_argument("--offset", type=nonnegative_int, default=0)


def _run_sync(args: Any, client_builder: Any) -> dict[str, Any]:
    if args.app_id is not None:
        pages = args.max_pages if args.max_pages is not None else DEFAULT_MAX_PAGES
        if bool(args.include_table_lineage):
            raise InputValidationError(
                "single-App metadata sync actual value cannot include account table lineage: "
                f"{actual_value(args.include_table_lineage)}",
                field="include_table_lineage",
                next_action=(
                    "Remove --include-table-lineage, or replace --app-id with --all-apps "
                    "for the existing account-scoped lineage sync."
                ),
            )
        if bool(args.metadata_sync_dry_run):
            return estimate_app_sync(
                args.app_id,
                database=args.database,
                max_pages=pages,
            )
        return sync_app(
            client_builder(args),
            args.app_id,
            database=args.database,
            max_pages=pages,
            concurrency=args.concurrency,
        )
    if args.max_pages is not None:
        raise InputValidationError(
            "all-App metadata max_pages actual value is not a bounded single-App option: "
            f"{actual_value(args.max_pages)}",
            field="max_pages",
            next_action=(
                "Remove --max-pages for the existing all-App sync, or replace "
                "--all-apps with --app-id <app-id>."
            ),
        )
    if bool(args.metadata_sync_dry_run):
        raise InputValidationError(
            "all-App metadata dry_run actual value has no pre-discovery App bound: "
            f"{actual_value(args.metadata_sync_dry_run)}",
            field="dry_run",
            next_action=(
                "Replace --all-apps with --app-id <app-id> to obtain a zero-network "
                "bound, or remove --dry-run to run the existing all-App sync."
            ),
        )
    options = {"database": args.database, "concurrency": args.concurrency}
    if bool(args.include_table_lineage):
        options["include_table_lineage"] = True
    return metadata_sync.sync_all_apps(client_builder(args), **options)


__all__ = ["add_metadata_commands", "run_analysis_metadata", "run_metadata_command"]
