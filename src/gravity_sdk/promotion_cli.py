"""CLI registration and dispatch for governed promotion reads."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from . import runtime
from .cli_limits import validate_date_pair
from .domains import (
    PROMOTION_EQUALS_OPERATOR,
    PROMOTION_PARENT_FILTER_FIELDS,
    PROMOTION_PLATFORMS,
    PROMOTION_PRIMARY_OPERATIONS,
    promotion_operation,
)
from .errors import InputValidationError
from .find_input import date_range_input, without_filter
from .multidim import parse_multi_days
from .pagination_cli import page_options
from .workspace import load_workspace
from .workspace_app import resolve_workspace_app


def add_promotion_commands(
    commands: Any,
    add_input: Callable[..., None],
    add_pagination: Callable[[Any], None],
    concurrency_parser: Callable[[str], int],
    positive_int: Callable[[str], int],
) -> None:
    """Register compatible promotion commands and Performance v1."""

    promotion = commands.add_parser("promotion")
    subcommands = promotion.add_subparsers(
        dest="promotion_command", required=True
    )
    subcommands.add_parser("platforms")
    query = subcommands.add_parser("query")
    query.add_argument(
        "--platform", required=True, choices=sorted(PROMOTION_PLATFORMS)
    )
    query.add_argument("--level")
    add_input(query)
    add_pagination(query)
    add_query_shortcuts(query)
    snapshot = subcommands.add_parser("snapshot")
    snapshot.add_argument(
        "--platform", required=True,
        choices=("all", *sorted(PROMOTION_PLATFORMS)),
    )
    snapshot.add_argument("--level")
    snapshot.add_argument("--concurrency", type=concurrency_parser, default=6)
    add_input(snapshot)
    add_query_shortcuts(snapshot)

    performance = subcommands.add_parser(
        "performance",
        help="Read governed physical metrics across selected platforms.",
    )
    performance.add_argument(
        "--app", required=True,
        help="One workspace App alias or positive id.",
    )
    performance.add_argument("--start", required=True)
    performance.add_argument("--end", required=True)
    performance.add_argument(
        "--platform", action="append", required=True,
        help="Platform; repeat or comma-separate.",
    )
    performance.add_argument(
        "--metric", action="append", required=True,
        help="Physical metric name; repeat or comma-separate.",
    )
    performance.add_argument(
        "--concurrency", type=concurrency_parser, default=6,
    )
    performance.add_argument("--max-pages", type=positive_int, default=1_000)
    performance.add_argument("--max-items", type=positive_int, default=100_000)
    performance.add_argument(
        "--output", type=_output_file,
        help="Write the complete JSON result to a local file.",
    )


def add_query_shortcuts(parser: Any) -> None:
    """Register the preserved schema-aware promotion shortcut flags."""

    parser.add_argument("--app-id")
    parser.add_argument("--media")
    parser.add_argument("--start")
    parser.add_argument("--end")
    parser.add_argument("--time-dim", action="append")
    parser.add_argument("--dimensions", action="append")
    parser.add_argument("--metrics", action="append")
    parser.add_argument("--multi-days", action="append")
    parser.add_argument("--parent-id")


def dispatch_promotion_command(
    args: Any,
    object_input: Callable[[Any], dict[str, Any]],
) -> Any:
    """Dispatch one promotion command without changing legacy behavior."""

    if args.promotion_command == "performance":
        return _performance(args)
    if args.promotion_command == "platforms":
        client = runtime.build_client()
        available = runtime.operation_ids(client.operations())
        return {
            "platforms": [
                {
                    "platform": platform,
                    "levels": {
                        level: operation_id
                        for level, operation_id in levels.items()
                        if not available or operation_id in available
                    },
                }
                for platform, levels in PROMOTION_PLATFORMS.items()
            ]
        }
    client = runtime.build_client()
    if args.promotion_command == "snapshot" and args.platform == "all":
        if args.level is not None:
            raise ValueError("--level cannot be combined with --platform all")
        supplied = object_input(args.input)
        requests: list[dict[str, Any]] = []
        ignored: dict[str, list[str]] = {}
        for platform, operation_id in PROMOTION_PRIMARY_OPERATIONS.items():
            inputs, skipped = merge_query_shortcuts(
                client, operation_id, args, supplied, strict=False
            )
            requests.append(
                {"operation_id": operation_id, "inputs": inputs, "read_all": True}
            )
            if skipped:
                ignored[platform] = skipped
        results = runtime.call_batch(
            client, requests, concurrency=args.concurrency
        )
        return {
            "platform_count": len(requests),
            "concurrency": args.concurrency,
            "ignored_shortcuts": ignored,
            "results": results,
        }
    operation_id = runtime.resolve_operation_id(
        client, promotion_operation(args.platform, args.level)
    )
    inputs, _ = merge_query_shortcuts(
        client, operation_id, args, object_input(args.input)
    )
    read_all = args.promotion_command == "snapshot" or bool(
        getattr(args, "all_pages", False)
    )
    return runtime.call_read(
        client,
        operation_id,
        inputs,
        read_all=read_all,
        **page_options(
            args,
            all_pages=True,
            active=bool(getattr(args, "all_pages", False)),
        ),
    )


def merge_query_shortcuts(
    client: Any,
    operation_id: str,
    args: Any,
    supplied: Mapping[str, Any],
    *,
    strict: bool = True,
) -> tuple[dict[str, Any], list[str]]:
    """Merge shortcut flags only into fields accepted by an operation."""

    fields, allowed, result, ignored = _prepare_shortcuts(
        client, operation_id, supplied, strict=strict
    )
    _merge_app_shortcut(
        operation_id, args, fields, allowed, result, ignored, strict=strict
    )
    _merge_date_shortcuts(
        operation_id, args, allowed, result, ignored, strict=strict
    )
    _merge_dimension_shortcuts(
        operation_id, args, allowed, result, ignored, strict=strict
    )
    _merge_parent_shortcut(
        operation_id, args, fields, allowed, result, ignored, strict=strict
    )
    return result, ignored


def _prepare_shortcuts(
    client: Any,
    operation_id: str,
    supplied: Mapping[str, Any],
    *,
    strict: bool,
) -> tuple[Mapping[str, Any], set[str], dict[str, Any], list[str]]:
    schema = runtime.to_jsonable(client.schema(operation_id))
    raw_fields = schema.get("input_fields", {}) if isinstance(schema, Mapping) else {}
    fields = raw_fields if isinstance(raw_fields, Mapping) else {}
    allowed = set(fields)
    unknown = sorted(set(supplied) - allowed)
    if unknown and strict:
        raise ValueError(
            f"{operation_id} does not accept input fields: " + ", ".join(unknown)
        )
    result = {key: value for key, value in supplied.items() if key in allowed}
    ignored = [] if strict else [f"input:{key}" for key in unknown]
    return fields, allowed, result, ignored


def _assign_shortcut(
    operation_id: str,
    allowed: set[str],
    result: dict[str, Any],
    ignored: list[str],
    flag: str,
    candidates: Sequence[str],
    value: Any,
    *,
    strict: bool,
) -> None:
    if value is None:
        return
    target = next((name for name in candidates if name in allowed), None)
    if target:
        result[target] = value
    elif strict:
        raise ValueError(
            f"{operation_id} does not accept --{flag.replace('_', '-')}"
        )
    else:
        ignored.append(flag)


def _merge_app_shortcut(
    operation_id: str,
    args: Any,
    fields: Mapping[str, Any],
    allowed: set[str],
    result: dict[str, Any],
    ignored: list[str],
    *,
    strict: bool,
) -> None:
    app_id = getattr(args, "app_id", None)
    if app_id is None:
        pass
    elif "app_id" in allowed:
        result["app_id"] = str(app_id)
    elif _accepts_array_field(fields, "filters"):
        result["filters"] = _replacement_filter(
            result.get("filters", []), "app_id", app_id
        )
    elif strict:
        raise ValueError(f"{operation_id} does not accept --app-id")
    else:
        ignored.append("app_id")
    _assign_shortcut(
        operation_id, allowed, result, ignored, "media",
        ("media_type", "media"), getattr(args, "media", None), strict=strict,
    )


def _merge_date_shortcuts(
    operation_id: str,
    args: Any,
    allowed: set[str],
    result: dict[str, Any],
    ignored: list[str],
    *,
    strict: bool,
) -> None:
    start, end = getattr(args, "start", None), getattr(args, "end", None)
    validate_date_pair(start, end)
    _assign_shortcut(
        operation_id, allowed, result, ignored, "start/end", ("date_list",),
        date_range_input(operation_id, start if start and end else None, end),
        strict=strict,
    )


def _merge_dimension_shortcuts(
    operation_id: str,
    args: Any,
    allowed: set[str],
    result: dict[str, Any],
    ignored: list[str],
    *,
    strict: bool,
) -> None:
    time_dims = split_values(getattr(args, "time_dim", None))
    if time_dims and len(time_dims) != 1:
        raise ValueError("--time-dim accepts exactly one value")
    values = (
        ("time_dim", ("time_dims",), time_dims[0] if time_dims else None),
        (
            "dimensions", ("data_dims", "dims_list"),
            split_values(getattr(args, "dimensions", None)),
        ),
        (
            "metrics", ("metrics_list", "query_fields"),
            split_values(getattr(args, "metrics", None)),
        ),
        (
            "multi_days", ("multi_keys",),
            parse_multi_days(split_values(getattr(args, "multi_days", None))),
        ),
    )
    for flag, candidates, value in values:
        _assign_shortcut(
            operation_id, allowed, result, ignored, flag, candidates, value,
            strict=strict,
        )


def _merge_parent_shortcut(
    operation_id: str,
    args: Any,
    fields: Mapping[str, Any],
    allowed: set[str],
    result: dict[str, Any],
    ignored: list[str],
    *,
    strict: bool,
) -> None:
    parent = getattr(args, "parent_id", None)
    if parent is None:
        return
    direct = next(
        (
            name for name in (
                "parent_id", "advertiser_id", "account_id", "campaign_id",
                "group_id", "developer_id",
            ) if name in allowed
        ),
        None,
    )
    filter_field = PROMOTION_PARENT_FILTER_FIELDS.get(operation_id)
    if direct:
        result[direct] = str(parent)
    elif filter_field and _accepts_array_field(fields, "filters"):
        result["filters"] = _replacement_filter(
            result.get("filters", []), filter_field, parent
        )
    elif strict:
        raise ValueError(f"{operation_id} does not accept --parent-id")
    else:
        ignored.append("parent_id")


def _replacement_filter(values: Any, field: str, value: Any) -> list[Any]:
    filters = without_filter(values, field)
    filters.append(
        {
            "field": field,
            "operator": PROMOTION_EQUALS_OPERATOR,
            "values": [str(value)],
        }
    )
    return filters


def split_values(values: Sequence[str] | None) -> list[str] | None:
    """Split repeatable comma-separated CLI values without inventing defaults."""

    if not values:
        return None
    selected = [
        part.strip() for value in values for part in value.split(",")
        if part.strip()
    ]
    return selected or None


def _performance(args: Any) -> dict[str, Any]:
    app_id, platforms, metrics = prepare_promotion_performance_request(args)
    from .promotion_performance import promotion_performance

    return promotion_performance(
        runtime.build_client(),
        app_id,
        args.start,
        args.end,
        platforms=platforms,
        metrics=metrics,
        max_workers=args.concurrency,
        max_pages=args.max_pages,
        max_items=args.max_items,
    )


def prepare_promotion_performance_request(
    args: Any,
) -> tuple[int, tuple[str, ...], tuple[str, ...]]:
    """Close a CLI product request without constructing a network client."""

    from .promotion_performance import (
        validate_promotion_performance_request,
    )

    platforms = _required_values(args.platform, "platform")
    metrics = _required_values(args.metric, "metric")
    if getattr(args, "output", None) is not None:
        _output_file(args.output)
    if not isinstance(args.app, str) or not args.app.strip():
        raise InputValidationError(
            "--app must be a non-empty workspace alias or positive id", field="app"
        )
    # Close the product request before workspace loading or client onboarding.
    validate_promotion_performance_request(
        1,
        args.start,
        args.end,
        platforms=platforms,
        metrics=metrics,
        max_workers=args.concurrency,
        max_pages=args.max_pages,
        max_items=args.max_items,
    )
    app_id = resolve_workspace_app(load_workspace(), args.app)
    validate_promotion_performance_request(
        app_id,
        args.start,
        args.end,
        platforms=platforms,
        metrics=metrics,
        max_workers=args.concurrency,
        max_pages=args.max_pages,
        max_items=args.max_items,
    )
    return app_id, platforms, metrics


def _required_values(values: Sequence[str] | None, field: str) -> tuple[str, ...]:
    selected = split_values(values)
    if not selected:
        raise InputValidationError(
            f"--{field} must select at least one value", field=field
        )
    return tuple(selected)


def _accepts_array_field(fields: Any, name: str) -> bool:
    if not isinstance(fields, Mapping):
        return False
    specification = fields.get(name)
    return (
        isinstance(specification, Mapping)
        and specification.get("type") == "array"
    )


def _output_file(value: str) -> str:
    selected = value.strip()
    if not selected or selected == "-":
        raise ValueError("output must be a non-empty local file path")
    path = Path(selected)
    if path.exists() and path.is_dir():
        raise ValueError("output must be a local file path, not a directory")
    return selected


# Preserve private imports used by older tests and callback wiring.
_merge_query_shortcuts = merge_query_shortcuts


__all__ = [
    "add_promotion_commands",
    "add_query_shortcuts",
    "dispatch_promotion_command",
    "merge_query_shortcuts",
    "prepare_promotion_performance_request",
    "split_values",
]
