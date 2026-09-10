"""CLI registration for material catalogs and the performance product."""

from __future__ import annotations

from collections.abc import Callable
import json
from typing import Any

from . import runtime
from .domains import DOMAIN_OPERATIONS
from .errors import InputValidationError
from .material_performance import (
    DEFAULT_PLATFORMS,
    material_performance,
    validate_material_performance_request,
)
from .workspace import load_workspace
from .workspace_app import resolve_workspace_app
from .title_package import OPERATION_IDS, title_packages
from .actionable_error_values import actual_value


def add_material_commands(
    commands: Any,
    add_input: Callable[..., None],
    add_pagination: Callable[[Any], None],
    concurrency_parser: Callable[[str], int],
    positive_int: Callable[[str], int],
) -> None:
    """Register the compatible catalogs plus Material Performance v1."""

    materials = commands.add_parser(
        "materials", help="Read material catalogs or governed performance rows."
    )
    subcommands = materials.add_subparsers(
        dest="materials_command", required=True
    )
    for name in ("list", "tags", "reviews"):
        item = subcommands.add_parser(name)
        add_input(item)
        add_pagination(item)
    _add_material_fetch_command(subcommands, add_input)
    _add_material_game_command(subcommands, positive_int, concurrency_parser)
    performance = subcommands.add_parser(
        "performance",
        help="Read platform material performance through one stable operation.",
    )
    performance.add_argument(
        "--app",
        action="append",
        required=True,
        help="Workspace App alias or positive id; repeat or comma-separate.",
    )
    performance.add_argument("--start", required=True)
    performance.add_argument("--end", required=True)
    performance.add_argument(
        "--platform",
        action="append",
        choices=DEFAULT_PLATFORMS,
        help="Platform; repeat. Defaults to all four supported platforms.",
    )
    performance.add_argument(
        "--concurrency", type=concurrency_parser, default=6,
        help="Concurrent platform workers; actual pool is at most four.",
    )
    performance.add_argument("--max-pages", type=positive_int, default=5)
    performance.add_argument("--max-items", type=positive_int, default=200)
    performance.add_argument(
        "--output", type=_output_file,
        help="Write the complete JSON result to a local file.",
    )
    packages = subcommands.add_parser(
        "title-packages",
        help="Read regular or standard Bytedance title-package summaries.",
    )
    packages.add_argument(
        "--app", required=True, help="Workspace App alias or positive id."
    )
    packages.add_argument(
        "--package-kind", required=True, choices=tuple(OPERATION_IDS)
    )
    packages.add_argument("--max-pages", type=positive_int, default=1_000)
    packages.add_argument("--max-items", type=positive_int, default=100_000)


def _add_material_fetch_command(
    subcommands: Any, add_input: Callable[..., None]
) -> None:
    fetch = subcommands.add_parser(
        "fetch",
        help=(
            "Fetch one allowlisted file from a fresh registered material response; "
            "source URLs remain private."
        ),
    )
    fetch.add_argument(
        "--source", required=True, choices=("local", "bytedance_project")
    )
    add_input(fetch, required=True)
    fetch.add_argument(
        "--ref-field",
        required=True,
        choices=("id", "gravity_material_id", "material_id"),
    )
    fetch.add_argument("--ref", required=True)
    fetch.add_argument("--role", required=True, choices=("file", "thumbnail"))
    fetch.add_argument("--output", required=True, type=_output_file)
    fetch.add_argument(
        "--output-root",
        type=_output_file,
        help="Bind a relative output beneath this existing plain directory.",
    )
    fetch.set_defaults(
        operation_id="material.asset.fetch", product_file_output=True
    )


def dispatch_material_command(args: Any, object_input: Callable[[Any], Any]) -> Any:
    """Dispatch old catalog commands unchanged or run the new product."""

    if args.materials_command == "game-performance":
        from .material_game_contract import prepare_material_game_performance
        from .material_game_performance import material_game_performance

        app_id = resolve_workspace_app(load_workspace(), args.app)
        ids = args.material_ids_json if args.material_ids_json is not None else _split_values(args.material_id, field="material-id")
        options = {key: getattr(args, key) for key in (
            "start", "end", "as_of", "lookback_days", "object_type",
            "max_report_pages", "max_user_pages", "max_user_items", "max_days",
        )}
        options["max_workers"] = args.concurrency
        options["metrics"] = object_input(args.metrics) if args.metrics else None
        preview = prepare_material_game_performance(app_id, ids, args.platform, **options)
        if args.material_game_dry_run:
            return preview
        return material_game_performance(runtime.build_client(), app_id, ids, args.platform, **options)
    if args.materials_command in {"list", "tags", "reviews"}:
        client = runtime.build_client()
        operation_id = runtime.resolve_operation_id(
            client, DOMAIN_OPERATIONS[f"materials.{args.materials_command}"]
        )
        all_pages = bool(args.all_pages)
        from .pagination_cli import page_options

        return runtime.call_read(
            client,
            operation_id,
            object_input(args.input),
            read_all=all_pages,
            **page_options(args, all_pages=all_pages, active=all_pages),
        )
    if args.materials_command == "fetch":
        from .material_asset import fetch_material_asset

        return fetch_material_asset(
            runtime.build_client(),
            args.source,
            object_input(args.input),
            args.ref_field,
            args.ref,
            args.role,
            args.output,
            output_root=args.output_root,
        )
    if args.materials_command == "title-packages":
        workspace = load_workspace()
        app_id = resolve_workspace_app(workspace, args.app)
        return title_packages(
            runtime.build_client(),
            app_id,
            args.package_kind,
            max_pages=args.max_pages,
            max_items=args.max_items,
        )
    workspace = load_workspace()
    apps = [
        resolve_workspace_app(workspace, value)
        for value in _split_values(args.app, field="app")
    ]
    platforms = tuple(args.platform or DEFAULT_PLATFORMS)
    validate_material_performance_request(
        apps,
        args.start,
        args.end,
        platforms=platforms,
        max_workers=args.concurrency,
        max_pages=args.max_pages,
        max_items=args.max_items,
    )
    return material_performance(
        runtime.build_client(),
        apps,
        args.start,
        args.end,
        platforms=platforms,
        max_workers=args.concurrency,
        max_pages=args.max_pages,
        max_items=args.max_items,
    )


def _split_values(values: list[str], *, field: str) -> list[str]:
    selected = [part.strip() for value in values for part in value.split(",")]
    result = [value for value in selected if value]
    if not result:
        raise InputValidationError(
            f"actual value: {actual_value(result)}; " + (f"--{field} must select at least one value"), field=field
        )
    return result


def _add_material_game_command(subcommands: Any, positive_int: Any, concurrency: Any) -> None:
    command = subcommands.add_parser("game-performance", help="Join material reports to bounded registration-day aggregates.")
    command.add_argument("--app", required=True)
    ids = command.add_mutually_exclusive_group(required=True)
    ids.add_argument("--material-id", action="append", help="String material ID; repeat or comma-separate.")
    ids.add_argument("--material-ids-json", type=json.loads, help="Explicitly typed JSON array of material IDs.")
    command.add_argument("--platform", choices=DEFAULT_PLATFORMS, required=True)
    command.add_argument("--start")
    command.add_argument("--end")
    command.add_argument("--as-of", help="Auto-window cutoff; defaults to yesterday in the local calendar.")
    command.add_argument("--lookback-days", type=positive_int, default=30)
    command.add_argument("--metrics", help="JSON file with project-owned level/payment/duration aggregate measure bindings.")
    command.add_argument("--object-type", choices=("material", "creative", "campaign"), default="material")
    command.add_argument("--max-report-pages", type=positive_int, default=100)
    command.add_argument("--max-user-pages", type=positive_int, default=1000)
    command.add_argument("--max-user-items", type=positive_int, default=100000)
    command.add_argument("--max-days", type=positive_int, default=90)
    command.add_argument("--concurrency", type=concurrency, default=6)
    command.add_argument("--dry-run", dest="material_game_dry_run", action="store_true")


def _output_file(value: str) -> str:
    selected = value.strip()
    if not selected or selected == "-":
        raise ValueError("output must be a non-empty local file path")
    return selected


__all__ = ["add_material_commands", "dispatch_material_command"]
