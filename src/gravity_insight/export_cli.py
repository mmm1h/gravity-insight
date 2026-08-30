"""Agent-facing CLI helpers for governed exports."""
from __future__ import annotations

import argparse
from typing import Any, Callable, Mapping

from .errors import (
    ErrorCategory,
    ErrorCode,
    ErrorDetail,
    InputValidationError,
    error_envelope,
    exit_code_for_category,
    exit_code_for_error,
)
from .result_source import GOVERNED_PRODUCT, result_source
from .actionable_error_values import actual_value


def add_export_commands(
    commands: Any,
    add_input: Callable[..., None],
    positive_int: Callable[[str], int],
) -> Any:
    export = commands.add_parser(
        "export",
        help=(
            "Discover, describe, create, monitor, download, or cancel governed "
            "exports. Start with `export list-capabilities`."
        ),
    )
    subcommands = export.add_subparsers(dest="export_command", required=True)
    listing_capabilities = subcommands.add_parser(
        "list-capabilities",
        help="List every governed export effect and whether it is callable.",
    )
    listing_capabilities.set_defaults(network_required=False)
    describe = subcommands.add_parser(
        "describe",
        help="Show one export input schema, example, columns, scale, and workflow.",
    )
    describe.add_argument("operation_id")
    describe.set_defaults(network_required=False)
    evaluate = subcommands.add_parser(
        "evaluate",
        help="Estimate rows for one evaluate export route without creating a job.",
    )
    evaluate.add_argument("operation_id")
    add_input(evaluate, required=True)
    evaluate.add_argument("--timeout", type=float, default=120.0)
    evaluate.set_defaults(network_required=True)
    types = subcommands.add_parser(
        "task-types",
        help="List verified export task types from the supporting catalog route.",
    )
    types.add_argument("--timeout", type=float, default=120.0)
    types.set_defaults(network_required=True)
    start = subcommands.add_parser(
        "start",
        help="Create one job using the exact schema returned by `export describe`.",
    )
    start.add_argument("operation_id")
    add_input(start, required=True)
    start.add_argument("--columns", required=True)
    start.add_argument("--idempotency-key", required=True)
    start.add_argument("--timeout", type=float, default=120.0)
    run = subcommands.add_parser(
        "run",
        help=(
            "Create, wait for, verify, and atomically download one governed export."
        ),
    )
    run.add_argument("operation_id")
    add_input(run, required=True)
    run.add_argument("--columns", required=True)
    run.add_argument("--idempotency-key", required=True)
    run.add_argument("--output", required=True)
    run.add_argument("--timeout", type=float, default=300.0)
    for name in ("status", "wait", "download", "cancel"):
        item = subcommands.add_parser(name)
        item.add_argument("job_id")
        item.add_argument("--operation-id", required=True)
        if name in {"status", "wait", "download"}:
            item.add_argument("--timeout", type=float, default=300.0)
        if name == "wait":
            item.add_argument("--interval", type=float, default=2.0)
        if name == "download":
            item.add_argument("--output", required=True)
    listing = subcommands.add_parser("list")
    listing.add_argument("--page", type=positive_int, default=1)
    listing.add_argument("--page-size", type=positive_int, default=100)
    return commands


def run_export_command(
    args: argparse.Namespace,
    client: Any,
    object_input: Callable[[str | None], dict[str, Any]],
) -> Any:
    if args.export_command == "list-capabilities":
        return client.export_capabilities()
    if args.export_command == "describe":
        return client.export_describe(args.operation_id)
    if args.export_command == "evaluate":
        return client.export_evaluate(
            args.operation_id,
            object_input(args.input),
            timeout_seconds=args.timeout,
        )
    if args.export_command == "task-types":
        return client.export_task_types(timeout_seconds=args.timeout)
    if args.export_command == "start":
        columns = _requested_columns(args.columns)
        return client.export_start(
            args.operation_id,
            object_input(args.input),
            requested_columns=columns,
            idempotency_key=args.idempotency_key,
            timeout_seconds=args.timeout,
        )
    if args.export_command == "run":
        return client.export_run(
            args.operation_id,
            object_input(args.input),
            args.output,
            requested_columns=_requested_columns(args.columns),
            idempotency_key=args.idempotency_key,
            timeout_seconds=args.timeout,
        )
    if args.export_command == "status":
        return client.export_status(
            args.operation_id,
            args.job_id,
            timeout_seconds=args.timeout,
        )
    if args.export_command == "wait":
        return client.export_wait(
            args.operation_id,
            args.job_id,
            interval_seconds=args.interval,
            timeout_seconds=args.timeout,
        )
    if args.export_command == "download":
        return client.export_download(
            args.operation_id,
            args.job_id,
            args.output,
            timeout_seconds=args.timeout,
        )
    if args.export_command == "cancel":
        return client.export_cancel(args.operation_id, args.job_id)
    return client.export_list(page=args.page, page_size=args.page_size)


def dispatch_command(
    args: argparse.Namespace,
    client_factory: Callable[[argparse.Namespace], Any],
    object_input: Callable[[str | None], dict[str, Any]],
    fallback: Callable[[argparse.Namespace], Any],
) -> Any:
    local_handler = getattr(args, "local_command_handler", None)
    if callable(local_handler):
        result = local_handler(args)
    elif args.command == "export":
        result = run_export_command(args, client_factory(args), object_input)
    else:
        result = fallback(args)
    from .relative_dates import attach_resolved_window

    return attach_resolved_window(result, getattr(args, "resolved_date_window", None))


def output_argument(args: argparse.Namespace) -> str | None:
    if bool(getattr(args, "product_file_output", False)):
        return None
    if (
        getattr(args, "command", None) == "export"
        and getattr(args, "export_command", None) in {"download", "run"}
    ):
        return None
    return getattr(args, "output", None)


def _requested_columns(value: Any) -> tuple[str, ...]:
    columns = tuple(
        item.strip()
        for item in str(value).split(",")
        if item.strip()
    )
    if not columns:
        raise InputValidationError(
            f"actual value: {actual_value(columns)}; " + ("--columns must contain at least one contracted column"),
            field="columns",
        )
    return columns


def export_cli_error(
    args: argparse.Namespace,
    error: BaseException,
) -> dict[str, Any]:
    operation_id = str(getattr(args, "operation_id", "")) or None
    job_id = str(getattr(args, "job_id", "")) or "<job-id>"
    code = _public_error_code(error)
    if code is None:
        fallback_action = (
            "Run `gravity export describe "
            f"{operation_id}` and retry with the documented input."
            if getattr(args, "export_command", None) in {"start", "run"}
            and operation_id
            else "Run `gravity export list --page 1 "
            "--page-size 100` and retry only a job stage that exists."
        )
        return error_envelope(
            error,
            operation_id=operation_id,
            next_action=getattr(error, "next_action", None) or fallback_action,
        )
    next_action = _next_action(
        code,
        str(getattr(args, "export_command", "status")),
        job_id,
        operation_id,
    )
    detail = ErrorDetail.create(
        code,
        error,
        operation_id=operation_id,
        category=(
            ErrorCategory.LOCAL
            if str(getattr(error, "code", "")) == "EXPORT_PRIVACY_DENIED"
            else None
        ),
        field=_export_error_field(error),
        retryable=bool(getattr(error, "retryable", False)),
        next_action=next_action,
    )
    return {
        "schema_version": "gravity-insight.error.v1",
        "result_source": result_source(GOVERNED_PRODUCT),
        "ok": False,
        "status": "error",
        "operation_id": operation_id,
        "error": detail.to_dict(),
    }


def command_error(
    args: argparse.Namespace | None,
    error: BaseException,
) -> tuple[dict[str, Any], int]:
    operation_id = (
        str(getattr(args, "operation_id", "")) or None
        if args is not None
        else None
    )
    if args is not None and getattr(args, "command", None) == "export":
        envelope = export_cli_error(args, error)
        detail = envelope.get("error", {})
        category = detail.get("category") if isinstance(detail, Mapping) else None
        code = exit_code_for_category(str(category), default=ErrorCategory.LOCAL)
        return envelope, code
    return error_envelope(error, operation_id=operation_id), exit_code_for_error(error)


def _public_error_code(error: BaseException) -> ErrorCode | str | None:
    value = getattr(error, "code", "")
    raw_code = value.value if isinstance(value, ErrorCode) else str(value)
    if raw_code in {item.value for item in ErrorCode}:
        return raw_code
    if raw_code == "EXPORT_TIMEOUT":
        return ErrorCode.EXPORT_TIMEOUT
    if raw_code in {
        "EXPORT_JOB_INVALID",
        "EXPORT_COLUMNS_INVALID",
        "EXPORT_IDEMPOTENCY_KEY_INVALID",
        "EXPORT_TIMEOUT_INVALID",
    }:
        return ErrorCode.INPUT_INVALID
    if raw_code in {"LOCAL_IO_ERROR", "BLOB_PATH_UNSAFE", "BLOB_PATH_REPARSE"}:
        return ErrorCode.LOCAL_IO_ERROR
    if raw_code.startswith("EXPORT_") or raw_code.startswith("BLOB_"):
        return ErrorCode.CONTRACT_CHANGED
    return None


def _next_action(
    code: ErrorCode | str,
    command: str,
    job_id: str,
    operation_id: str | None,
) -> str:
    if code == ErrorCode.UNKNOWN_OPERATION:
        return (
            "Run `gravity export list-capabilities` and "
            "use an operation_id from the results."
        )
    if code == ErrorCode.EXPORT_TIMEOUT:
        return (
            "Run `gravity export status "
            f"{job_id} --operation-id {operation_id or '<operation-id>'}`."
        )
    if code == ErrorCode.INPUT_INVALID:
        return (
            "Run `gravity export describe "
            f"{operation_id or '<operation-id>'}` and retry with the documented input."
        )
    if code == ErrorCode.LOCAL_IO_ERROR:
        return (
            "Run `gravity export download "
            f"{job_id} --operation-id {operation_id or '<operation-id>'} "
            "--output <writable-file.xlsx> --timeout 300`."
        )
    if code == ErrorCode.CONTRACT_CHANGED:
        return (
            "Run `gravity export describe "
            f"{operation_id or '<operation-id>'}` and stop automation until the "
            "maintainer can re-verify and republish the contract."
        )
    if code in {ErrorCode.UNSUPPORTED, ErrorCode.NOT_IMPLEMENTED}:
        return (
            "Run `gravity export describe "
            f"{operation_id or '<operation-id>'}` and select an operation with "
            "currently_callable=true."
        )
    if command in {"start", "run"}:
        return (
            "Run `gravity export list --page 1 "
            "--page-size 100` to determine whether a job was created; do not "
            "create a duplicate."
        )
    return (
        "Run `gravity export status "
        f"{job_id} --operation-id {operation_id or '<operation-id>'}` and retry "
        "only the failed job stage."
    )


def _export_error_field(error: BaseException) -> str | None:
    explicit = getattr(error, "field", None)
    if explicit:
        return str(explicit)
    value = getattr(error, "code", "")
    code = value.value if isinstance(value, ErrorCode) else str(value)
    return {
        "EXPORT_COLUMNS_INVALID": "columns",
        "EXPORT_JOB_INVALID": "job_id",
        "EXPORT_IDEMPOTENCY_KEY_INVALID": "idempotency_key",
        "EXPORT_TIMEOUT_INVALID": "timeout",
    }.get(code)


__all__ = [
    "add_export_commands",
    "command_error",
    "dispatch_command",
    "export_cli_error",
    "output_argument",
    "run_export_command",
]
