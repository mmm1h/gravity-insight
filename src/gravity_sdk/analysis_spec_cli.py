"""Thin CLI bridge for compact Analysis query specs."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from .analysis_spec import (
    analysis_query_spec_schema,
    prepare_query_spec,
    validate_query_spec,
)
from .domains import ANALYSIS_QUERY_OPERATIONS, new_analysis_query_id
from .errors import InputValidationError


def add_analysis_query_arguments(
    parser: Any,
    add_input: Callable[..., Any],
    add_shortcuts: Callable[[Any], None],
) -> None:
    parser.add_argument(
        "--kind", choices=sorted(ANALYSIS_QUERY_OPERATIONS)
    )
    parser.add_argument(
        "--experimental",
        action="store_true",
        help="allow the operation only when the registry marks it experimental",
    )
    add_input(parser)
    add_shortcuts(parser)
    parser.add_argument(
        "--spec",
        help="compact Analysis spec as inline JSON, file path, or '-' for stdin",
    )
    parser.add_argument("--app", help="workspace App alias or positive id for --spec")
    parser.add_argument("--workspace", help="gravity.toml or its directory for --spec")
    parser.add_argument(
        "--dry-run",
        dest="query_spec_dry_run",
        action="store_true",
        help="compile and validate --spec offline without sending a request",
    )
    parser.add_argument(
        "--spec-schema",
        action="store_true",
        help="print the compact Analysis Spec v1 contract without a client",
    )


def run_analysis_query_command(
    args: Any,
    build_client: Callable[[], Any],
    parse_object: Callable[[str], Mapping[str, Any]],
    merge_shortcuts: Callable[..., tuple[dict[str, Any], list[str]]],
    call_read: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    if args.kind is None:
        raise InputValidationError(
            "analysis query requires --kind unless the batch subcommand is used",
            field="kind",
            next_action=(
                "Run `gravity analysis query --kind <kind> --help`, or use "
                "`gravity analysis query batch --input <queries.json>`."
            ),
        )
    if bool(getattr(args, "spec_schema", False)):
        if args.spec is not None or args.input is not None:
            raise InputValidationError(
                "--spec-schema cannot be combined with --spec or --input",
                field="spec_schema",
            )
        result = analysis_query_spec_schema()
        result["requested_kind"] = args.kind
        return result
    if args.spec is None and bool(getattr(args, "query_spec_dry_run", False)):
        raise InputValidationError(
            "--dry-run requires --spec; raw --input cannot be executed in dry-run mode",
            field="dry_run",
        )
    client = build_client()
    operation_id = ANALYSIS_QUERY_OPERATIONS[args.kind]
    stability = client.schema(operation_id).get("stability", "stable")
    if stability != "stable":
        if not bool(getattr(args, "experimental", False)):
            raise InputValidationError(
                "experimental analysis reads require explicit --experimental",
                field="experimental",
            )
        client = build_client(allow_experimental=True)
    if args.spec is None:
        inputs, _ = merge_shortcuts(
            client, operation_id, args, parse_object(args.input)
        )
        inputs.setdefault("query_id", new_analysis_query_id())
        return call_read(client, operation_id, inputs)
    if args.input is not None:
        raise InputValidationError(
            "--spec cannot be combined with raw --input", field="spec"
        )
    _reject_unrelated_shortcuts(args)
    spec = parse_object(args.spec)
    options = {
        "workspace": getattr(args, "workspace", None),
        "app": getattr(args, "app", None) or getattr(args, "app_id", None),
        "start": getattr(args, "start", None),
        "end": getattr(args, "end", None),
    }
    if bool(getattr(args, "dry_run", False)) or bool(
        getattr(args, "query_spec_dry_run", False)
    ):
        return prepare_query_spec(client, args.kind, spec, **options)
    compiled, _validation = validate_query_spec(
        client, args.kind, spec, **options
    )
    return call_read(
        client,
        compiled.operation_id,
        compiled.inputs,
    )


def _reject_unrelated_shortcuts(args: Any) -> None:
    unsupported = {
        "media": getattr(args, "media", None),
        "time_dim": getattr(args, "time_dim", None),
        "dimensions": getattr(args, "dimensions", None),
        "metrics": getattr(args, "metrics", None),
        "multi_days": getattr(args, "multi_days", None),
        "parent_id": getattr(args, "parent_id", None),
    }
    selected = sorted(name for name, value in unsupported.items() if value is not None)
    if selected:
        raise InputValidationError(
            "--spec does not accept unrelated raw-query shortcuts: "
            + ", ".join(selected),
            field="spec",
        )
