"""Public batch schema, validation, and CLI orchestration."""
from __future__ import annotations

import argparse
from typing import Any, Callable, Mapping, Sequence

from .errors import (
    ErrorCategory,
    InputValidationError,
    exit_code_for_category,
    exit_code_for_status,
)
from .result_source import RAW_OPERATION, result_source
from .actionable_error_values import actual_value


BATCH_ITEM_FIELDS = frozenset(
    {"operation_id", "input", "inputs", "request_id", "read_all"}
)
_SCHEMA_COMMAND = "gravity batch schema"


def add_batch_commands(
    commands: Any,
    add_input: Callable[..., None],
    concurrency_type: Callable[[str], int],
    positive_type: Callable[[str], int],
) -> None:
    batch = commands.add_parser(
        "batch",
        help=(
            "Discover the public batch wrapper or execute registered read "
            "operations. Start with `batch schema`."
        ),
    )
    subcommands = batch.add_subparsers(dest="batch_command", required=True)
    schema = subcommands.add_parser(
        "schema",
        help="Print the complete wrapper, item fields, example, output, and exit rules.",
    )
    schema.set_defaults(network_required=False)
    schema.add_argument("--mode", choices=("read", "run"), default="read")
    read = subcommands.add_parser(
        "read",
        description=f"Execute a batch described by `{_SCHEMA_COMMAND}`.",
    )
    add_input(read, required=True)
    read.add_argument("--concurrency", type=concurrency_type, default=6)
    resolver = subcommands.add_parser(
        "run",
        description="Resolve and execute recipe or operation selectors concurrently.",
    )
    add_input(resolver, required=True)
    resolver.add_argument("--concurrency", type=concurrency_type, default=6)
    resolver.add_argument("--max-pages", type=positive_type, default=5)
    resolver.add_argument("--max-items", type=positive_type, default=200)
    resolver.add_argument(
        "--fields",
        action="append",
        help="Default comma-separated contracted output fields for every item.",
    )


def run_batch_command(
    args: argparse.Namespace,
    client_factory: Callable[[argparse.Namespace], Any],
    load_json_input: Callable[..., Any],
    call_batch: Callable[..., Any],
    example_operation: str,
) -> dict[str, Any]:
    if args.batch_command == "schema":
        if getattr(args, "mode", "read") == "run":
            from .resolver_batch import resolver_batch_schema

            return resolver_batch_schema()
        return batch_schema(example_operation)
    if args.batch_command == "run":
        from .resolver_batch import run_many
        from .workspace import load_workspace

        return run_many(
            load_json_input(args.input, required=True),
            client=client_factory(args),
            workspace=load_workspace(),
            max_workers=args.concurrency,
            max_pages=args.max_pages,
            max_items=args.max_items,
            output_fields=_field_values(args.fields),
        )
    payload = _batch_payload(load_json_input(args.input, required=True))
    results = call_batch(
        client_factory(args), payload, concurrency=args.concurrency
    )
    return batch_envelope(results)


def _field_values(values: Sequence[str] | None) -> tuple[str, ...] | None:
    if not values:
        return None
    fields = tuple(
        part.strip() for value in values for part in value.split(",") if part.strip()
    )
    return fields or None


def batch_schema_version(args: argparse.Namespace) -> str:
    if args.batch_command == "schema":
        return (
            "gravity-insight.resolver-batch-schema.v1"
            if getattr(args, "mode", "read") == "run"
            else "gravity-insight.batch-schema.v1"
        )
    return {
        "read": "gravity-insight.batch.v1",
        "run": "gravity-insight.resolver-batch.v1",
    }[args.batch_command]


def validate_batch_item(value: Any) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise batch_input_error(f"actual value: {actual_value(value)}; " + ("batch requests must be objects"), "requests")
    _reject_unknown_item_fields(value)
    if "input" in value and "inputs" in value:
        raise batch_input_error(
            f"actual value: {actual_value(value)}; " + ("batch input and inputs aliases cannot be combined; allowed fields: "
            + ", ".join(sorted(BATCH_ITEM_FIELDS))),
            "inputs",
        )
    return value


def batch_schema(example_operation: str) -> dict[str, Any]:
    item_properties = {
        "operation_id": {"type": "string", "required": True},
        "input": {
            "type": "object", "required": False, "default": {},
            "alias_of": "inputs",
        },
        "inputs": {
            "type": "object", "required": False, "default": {},
            "mutually_exclusive_with": "input",
        },
        "request_id": {"type": "string", "required": False, "default": None},
        "read_all": {"type": "boolean", "required": False, "default": False},
    }
    return {
        "schema_version": "gravity-insight.batch-schema.v1",
        "ok": True,
        "status": "success",
        "command": (
            "gravity batch read --input <batch.json> "
            "--concurrency 1"
        ),
        "wrapper": {
            "type": "object",
            "additional_properties": False,
            "required": ["requests"],
            "properties": {
                "requests": {
                    "type": "array",
                    "min_items": 1,
                    "items": {
                        "type": "object",
                        "additional_properties": False,
                        "required": ["operation_id"],
                        "allowed_fields": sorted(BATCH_ITEM_FIELDS),
                        "properties": item_properties,
                    },
                }
            },
        },
        "example": {
            "requests": [
                {
                    "operation_id": example_operation,
                    "input": {"page": 1, "page_size": 1},
                    "request_id": "apps-page-1",
                },
                {
                    "operation_id": example_operation,
                    "input": {"page": 2, "page_size": 1},
                    "request_id": "apps-page-2",
                },
            ]
        },
        "output": {
            "schema_version": "gravity-insight.batch.v1",
            "fields": [
                "result_source", "ok", "status", "total_count", "success_count",
                "failure_count", "exit_code", "results",
            ],
        },
        "exit_codes": {
            "0": "every item succeeded",
            "2": "at least one caller failure and no upstream/local failure",
            "3": "at least one upstream failure and no local failure",
            "4": "at least one local or unclassified failure",
            "aggregation": (
                "highest item exit code wins: local 4 > upstream 3 > caller 2"
            ),
        },
    }


def batch_envelope(results: Any) -> dict[str, Any]:
    if not isinstance(results, list) or not all(
        isinstance(item, Mapping) for item in results
    ):
        raise RuntimeError("batch client returned an invalid result list")
    failed = [item for item in results if item.get("ok") is not True]
    success_count = len(results) - len(failed)
    exit_code = max((_item_exit_code(item) for item in failed), default=0)
    return {
        "schema_version": "gravity-insight.batch.v1",
        "result_source": result_source(RAW_OPERATION),
        "ok": not failed,
        "status": "success" if not failed else "partial" if success_count else "error",
        "total_count": len(results),
        "success_count": success_count,
        "failure_count": len(failed),
        "exit_code": exit_code,
        "results": [dict(item) for item in results],
    }


def envelope_exit_code(result: Mapping[str, Any]) -> int:
    error = result.get("error")
    return exit_code_for_status(
        result.get("status"), ok=result.get("ok"),
        error=error if isinstance(error, Mapping) else None,
    )


def _batch_payload(payload: Any) -> list[Mapping[str, Any]]:
    if isinstance(payload, Mapping):
        unknown = sorted(set(payload) - {"requests"})
        if unknown:
            raise batch_input_error(
                f"actual value: {actual_value(unknown[0])}; " + ("unknown batch wrapper fields: " + ", ".join(unknown)
                + "; allowed fields: requests"),
                unknown[0],
            )
        payload = payload.get("requests")
    if not isinstance(payload, list) or not all(
        isinstance(item, Mapping) for item in payload
    ):
        raise batch_input_error(
            f"actual value: {actual_value(payload)}; " + ("batch input must be an object containing a requests array"), "requests"
        )
    if not payload:
        raise batch_input_error(
            f"actual value: {actual_value(payload)}; " + ("batch requests must contain at least one item"), "requests"
        )
    return [validate_batch_item(item) for item in payload]


def _reject_unknown_item_fields(item: Mapping[str, Any]) -> None:
    unknown = sorted(set(item) - BATCH_ITEM_FIELDS)
    if unknown:
        raise batch_input_error(
            f"actual value: {actual_value(unknown[0])}; " + ("unknown batch request fields: " + ", ".join(unknown)
            + "; allowed fields: " + ", ".join(sorted(BATCH_ITEM_FIELDS))),
            unknown[0],
        )


def batch_input_error(message: str, field: str) -> InputValidationError:
    return InputValidationError(
        message,
        field=field,
        next_action=(
            f"Run `{_SCHEMA_COMMAND}` and retry with only the documented "
            "wrapper and item fields."
        ),
    )


def _item_exit_code(item: Mapping[str, Any]) -> int:
    error = item.get("error")
    category = error.get("category") if isinstance(error, Mapping) else None
    return _category_exit_code(category)


def _category_exit_code(category: Any) -> int:
    return exit_code_for_category(str(category), default=ErrorCategory.LOCAL)


__all__ = [
    "BATCH_ITEM_FIELDS",
    "add_batch_commands",
    "batch_envelope",
    "batch_schema",
    "batch_schema_version",
    "envelope_exit_code",
    "batch_input_error",
    "run_batch_command",
    "validate_batch_item",
]
