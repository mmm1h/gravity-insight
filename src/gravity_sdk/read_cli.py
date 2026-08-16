"""Generic contracted read CLI, including local output selection."""

from __future__ import annotations

from typing import Any, Callable, Mapping

from . import runtime
from .errors import InputValidationError
from .output_projection import project_output, validate_output_fields
from .pagination_audit import pagination_audit
from .pagination_cli import page_limits


def add_read_command(
    commands: Any,
    add_input: Callable[..., None],
    add_all_pages: Callable[[Any], None],
    positive_int: Callable[[str], int],
) -> None:
    command = commands.add_parser("read", help="Execute one registered operation_id.")
    command.add_argument("operation_id")
    add_input(command)
    add_all_pages(command)
    command.add_argument("--limit", type=positive_int, help="Compatibility alias for --max-items.")
    command.add_argument(
        "--fields",
        action="append",
        help="Comma-separated contracted output fields; may be repeated.",
    )
    command.set_defaults(_gravity_handler=dispatch)


def dispatch(args: Any, object_input: Callable[[Any], Mapping[str, Any]]) -> Any:
    _validate_output_mode(args)
    if args.limit is not None and args.max_items is not None:
        raise InputValidationError(
            "--limit and --max-items cannot be combined", field="max_items"
        )
    all_pages = bool(args.all_pages)
    client = runtime.build_client()
    inputs = dict(object_input(args.input))
    fields = _field_values(args.fields)
    schema = client.schema(args.operation_id)
    if fields is not None:
        validate_output_fields(schema, fields, request_inputs=inputs)
    bounded = _bounded(args, all_pages)
    result = _read_result(args, client, inputs, all_pages, bounded)
    if isinstance(result, Mapping):
        result = {**result, "pagination_audit": pagination_audit(
            result, inputs, all_pages=all_pages, bounded=bounded
        )}
    return project_output(
        schema, args.operation_id, result, fields, request_inputs=inputs
    )


def _read_result(
    args: Any, client: Any, inputs: Mapping[str, Any], all_pages: bool, bounded: bool
) -> Any:
    if not bounded:
        return runtime.call_read(client, args.operation_id, inputs)
    max_pages, max_items = page_limits(args, all_pages=all_pages)
    if args.limit is not None:
        max_items = args.limit
    return runtime.call_read(
        client,
        args.operation_id,
        inputs,
        read_all=all_pages,
        max_pages=max_pages,
        max_items=max_items,
        max_workers=args.concurrency,
    )


def _bounded(args: Any, all_pages: bool) -> bool:
    return all_pages or any(
        getattr(args, name, None) is not None for name in ("limit", "max_pages", "max_items")
    )


def _field_values(values: list[str] | None) -> tuple[str, ...] | None:
    if not values:
        return None
    result = tuple(
        part.strip() for value in values for part in value.split(",") if part.strip()
    )
    return result or None


def _validate_output_mode(args: Any) -> None:
    if not bool(args.all_pages):
        return
    if getattr(args, "output", None) or getattr(args, "format", "json") == "ndjson":
        return
    raise InputValidationError(
        "--all-pages requires --output <path> or --format ndjson",
        field="all_pages",
    )


__all__ = ["add_read_command", "dispatch"]
