"""CLI registration and routing for governed Multidim reads."""

from __future__ import annotations

import argparse
import copy
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from . import runtime
from .domains import (
    DOMAIN_OPERATIONS,
    MULTIDIM_METADATA_OPERATIONS,
    MULTIDIM_TEMPLATE_SCOPES,
)
from .errors import InputValidationError
from .multidim import parse_multi_days
from .pagination_cli import page_options
from .workspace import load_workspace
from .workspace_app import resolve_workspace_app


def add_multidim_commands(
    commands: Any,
    add_input: Callable[..., None],
    add_pagination: Callable[[argparse.ArgumentParser], None],
) -> None:
    """Register catalog reads plus the single App-bound product query."""

    multidim = commands.add_parser(
        "multidim", help="Read Multidim catalogs or execute a governed report query."
    )
    subcommands = multidim.add_subparsers(dest="multidim_command", required=True)
    templates = subcommands.add_parser("templates")
    template_commands = templates.add_subparsers(
        dest="template_command", required=True
    )
    template_list = template_commands.add_parser("list")
    template_list.add_argument(
        "--scope", choices=sorted(MULTIDIM_TEMPLATE_SCOPES), default="preset"
    )
    add_input(template_list)
    add_pagination(template_list)
    template_get = template_commands.add_parser("get")
    add_input(template_get)

    metadata = subcommands.add_parser("metadata")
    add_input(metadata)

    query = subcommands.add_parser("query")
    add_input(query)
    add_pagination(query)
    query._option_string_actions["--output"].type = _output_path
    query.add_argument(
        "--include-total",
        action="store_true",
        help="Validate live metric metadata and calculate totals in the same command.",
    )
    _add_product_shortcuts(query)
    query.add_argument(
        "--app",
        help="Required for execution: workspace App alias or positive id.",
    )
    query.add_argument(
        "--workspace",
        help="gravity.toml or its directory used to resolve --app.",
    )
    offline = query.add_mutually_exclusive_group()
    offline.add_argument(
        "--dry-run",
        dest="multidim_dry_run",
        action="store_true",
        help="Validate and bind the product request without constructing a client.",
    )
    offline.add_argument(
        "--input-schema",
        dest="multidim_input_schema",
        action="store_true",
        help="Print the closed Multidim product input schema without network access.",
    )

    handler = _handler()
    for parser in (
        template_list,
        template_get,
        metadata,
        query,
    ):
        parser.set_defaults(_gravity_handler=handler)


def _handler() -> Callable[[Any, Any], Any]:
    def dispatch(args: Any, object_input: Callable[[Any], Mapping[str, Any]]) -> Any:
        return dispatch_multidim(args, object_input)

    return dispatch


def dispatch_multidim(
    args: Any,
    object_input: Callable[[Any], Mapping[str, Any]],
) -> Any:
    """Dispatch one Multidim command while keeping product preflight client-free."""

    if bool(getattr(args, "dry_run", False)):
        raise InputValidationError(
            "global --dry-run cannot be combined with a Multidim command; "
            "place --dry-run after `multidim query`",
            field="dry_run",
        )
    _enforce_output_policy(args)
    command = args.multidim_command
    if command == "metadata":
        return _metadata(args, object_input)
    if command == "templates":
        key = (
            f"multidim.templates.{args.scope}"
            if args.template_command == "list"
            else "multidim.templates.get"
        )
        return _catalog_read(args, object_input, DOMAIN_OPERATIONS[key])
    if bool(getattr(args, "multidim_input_schema", False)):
        from .multidim_product import multidim_input_schema

        return multidim_input_schema()
    return _product_query(args, object_input)


def _enforce_output_policy(args: Any) -> None:
    if bool(getattr(args, "multidim_dry_run", False)) or bool(
        getattr(args, "multidim_input_schema", False)
    ):
        return
    if not bool(getattr(args, "all_pages", False)):
        return
    if getattr(args, "output", None) or getattr(args, "format", "json") == "ndjson":
        return
    raise InputValidationError(
        "--all-pages requires --output <path> or --format ndjson",
        field="all_pages",
    )


def _product_query(args: Any, object_input: Callable[[Any], Mapping[str, Any]]) -> Any:
    from .multidim_product import (
        bind_multidim_app,
        normalize_multidim_inputs,
        prepare_multidim_query,
        run_multidim_query,
    )

    if getattr(args, "app", None) is None:
        raise InputValidationError(
            "multidim query requires explicit --app",
            field="app",
            next_action="Retry with `gravity multidim query --app <name|id> ...`.",
        )
    supplied = _product_shortcuts(args, object_input(args.input))
    normalized = normalize_multidim_inputs(supplied)
    workspace = load_workspace(getattr(args, "workspace", None))
    app_id = resolve_workspace_app(workspace, getattr(args, "app", None))
    bound = bind_multidim_app(normalized, app_id)
    all_pages = bool(getattr(args, "all_pages", False))
    _product_switches(args)
    options = _product_bounds(args, all_pages)
    preview = prepare_multidim_query(None, bound, app_id=app_id)
    if bool(getattr(args, "multidim_dry_run", False)):
        return preview
    client = runtime.build_client()
    return run_multidim_query(
        client,
        bound,
        app_id=app_id,
        include_total=bool(getattr(args, "include_total", False)),
        read_all=all_pages,
        **options,
    )


def _product_switches(args: Any) -> None:
    for field in ("include_total", "all_pages"):
        if not isinstance(getattr(args, field, False), bool):
            raise InputValidationError(f"{field} must be a boolean", field=field)


def _product_bounds(args: Any, all_pages: bool) -> dict[str, int]:
    from .pagination_cli import page_limits

    max_pages, max_items = page_limits(args, all_pages=all_pages)
    max_workers = getattr(args, "concurrency", 6)
    for field, value, maximum in (
        ("max_pages", max_pages, 1_000),
        ("max_items", max_items, 100_000),
        ("concurrency", max_workers, 24),
    ):
        if type(value) is not int or not 1 <= value <= maximum:
            raise InputValidationError(
                f"{field} must be between 1 and {maximum}", field=field
            )
    return {
        "max_pages": max_pages,
        "max_items": max_items,
        "max_workers": max_workers,
    }


def _product_shortcuts(
    args: Any, supplied: Mapping[str, Any]
) -> dict[str, Any]:
    result = copy.deepcopy(dict(supplied))
    start, end = getattr(args, "start", None), getattr(args, "end", None)
    from .cli_limits import validate_date_pair

    validate_date_pair(start, end)
    if start is not None and end is not None:
        result["date_list"] = [start, end]
    time_dims = _split_values(getattr(args, "time_dim", None))
    if time_dims and len(time_dims) != 1:
        raise InputValidationError(
            "--time-dim accepts exactly one value", field="time_dim"
        )
    if time_dims:
        result["time_dims"] = time_dims[0]
    for argument, field in (("dimensions", "data_dims"), ("metrics", "metrics_list")):
        values = _split_values(getattr(args, argument, None))
        if values is not None:
            result[field] = values
    multi_days = parse_multi_days(_split_values(getattr(args, "multi_days", None)))
    if multi_days is not None:
        result["multi_keys"] = multi_days
    filters = result.get("filters", [])
    if not isinstance(filters, list):
        raise InputValidationError("multidim filters must be an array", field="filters")
    media = getattr(args, "media", None)
    if media is not None:
        filters = [
            item
            for item in filters
            if not isinstance(item, Mapping) or item.get("field") != "click_company"
        ]
        filters.append(
            {"field": "click_company", "operator": "IN", "values": [media]}
        )
        result["filters"] = filters
    return result


def _catalog_read(
    args: Any,
    object_input: Callable[[Any], Mapping[str, Any]],
    candidates: Sequence[str],
) -> Any:
    client = runtime.build_client()
    operation_id = runtime.resolve_operation_id(client, candidates)
    all_pages = bool(getattr(args, "all_pages", False))
    return runtime.call_read(
        client,
        operation_id,
        object_input(args.input),
        read_all=all_pages,
        **page_options(args, all_pages=all_pages, active=all_pages),
    )


def _add_product_shortcuts(parser: argparse.ArgumentParser) -> None:
    """Expose only shortcuts that map into the closed product input schema."""

    parser.add_argument("--media")
    parser.add_argument("--start")
    parser.add_argument("--end")
    parser.add_argument("--time-dim", action="append")
    parser.add_argument("--dimensions", action="append")
    parser.add_argument("--metrics", action="append")
    parser.add_argument("--multi-days", action="append")


def _metadata(args: Any, object_input: Callable[[Any], Mapping[str, Any]]) -> Any:
    supplied = object_input(args.input)
    requests: list[dict[str, Any]] = []
    for operation_id in MULTIDIM_METADATA_OPERATIONS:
        per_operation = supplied.get(
            operation_id, supplied.get(operation_id.rsplit(".", 2)[-2], {})
        )
        if not isinstance(per_operation, Mapping):
            raise InputValidationError(
                f"metadata input for {operation_id} must be an object",
                field="input",
            )
        requests.append(
            {
                "operation_id": operation_id,
                "inputs": dict(per_operation),
                "read_all": True,
            }
        )
    return runtime.call_batch(runtime.build_client(), requests)


def _split_values(values: Sequence[str] | None) -> list[str] | None:
    if not values:
        return None
    selected = [
        part.strip()
        for value in values
        for part in value.split(",")
        if part.strip()
    ]
    return selected or None


def _output_path(value: str) -> str:
    selected = value.strip()
    if not selected or selected == "-":
        raise argparse.ArgumentTypeError(
            "output must be a non-empty file path; use --format ndjson for stdout"
        )
    return selected


def multidim_ndjson_view(value: Mapping[str, Any]) -> tuple[Any, dict[str, Any]]:
    """Return the primary query rows and bounded stream metadata."""

    if value.get("schema_version") != "gravity-insight.composite.multidim.v1":
        return value.get("data", value), {}
    query = value.get("query")
    if not isinstance(query, Mapping):
        return None, {}
    page = query.get("page") if isinstance(query.get("page"), Mapping) else {}
    data = query.get("data")
    rows = data.get("list", data.get("items")) if isinstance(data, Mapping) else None
    total_items = page.get("total_items")
    if type(total_items) is not int or total_items < 0:
        total_items = len(rows) if isinstance(rows, list) else None
    return data, {
        "operation_id": query.get("operation_id"),
        "status": value.get("status", query.get("status")),
        "truncated": query.get("truncated", False),
        "next_page_input": None,
        "total": total_items,
    }


__all__ = ["add_multidim_commands", "dispatch_multidim", "multidim_ndjson_view"]
