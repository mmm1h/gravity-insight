"""Thin CLI bridge for compact Segment Rule Spec v1."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from .domains import ANALYSIS_PAGINATED_OPERATIONS, ANALYSIS_SEGMENT_OPERATIONS
from .errors import InputValidationError
from .output_projection import project_output, validate_output_fields
from .pagination_cli import page_options
from .segment_spec import (
    compile_segment_spec,
    prepare_segment_spec,
    segment_rule_spec_schema,
)


def add_segment_commands(
    commands: Any,
    add_input: Callable[..., Any],
    add_all_pages: Callable[..., Any],
) -> Any:
    """Register legacy reads and the product-shaped rule evaluator together."""

    parser = commands.add_parser(
        "segment", help="Read segment resources or evaluate a compact rule spec."
    )
    parser.add_argument("--kind", choices=sorted(ANALYSIS_SEGMENT_OPERATIONS))
    add_input(parser)
    add_all_pages(parser)
    add_segment_evaluate_command(parser)
    return parser


def add_segment_evaluate_command(parser: Any) -> None:
    """Add the product-shaped path while retaining legacy parser options."""

    commands = parser.add_subparsers(dest="segment_action")
    evaluate = commands.add_parser(
        "evaluate",
        help="Estimate aggregate population and ratio from a compact rule spec.",
    )
    evaluate.add_argument(
        "--spec", help="Compact rule JSON as an inline object, file path, or '-'."
    )
    evaluate.add_argument("--app", help="Workspace App alias or positive id.")
    evaluate.add_argument("--start", help="Override the rule evaluation start date.")
    evaluate.add_argument("--end", help="Override the rule evaluation end date.")
    evaluate.add_argument(
        "--dry-run",
        dest="segment_spec_dry_run",
        action="store_true",
        help="Compile and validate offline without evaluating the rule.",
    )
    evaluate.add_argument(
        "--spec-schema",
        action="store_true",
        help="Print the complete compact Segment Rule Spec contract offline.",
    )
    evaluate.add_argument(
        "--fields",
        action="append",
        help="Comma-separated aggregate fields: part, percent, total.",
    )


def run_segment_command(
    args: Any,
    build_client: Callable[..., Any],
    parse_object: Callable[[Any], Mapping[str, Any]],
    call_read: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    """Dispatch the compact evaluator or one legacy segment resource read."""

    if getattr(args, "segment_action", None) == "evaluate":
        return run_segment_evaluate_command(
            args, build_client, parse_object, call_read
        )
    kind = getattr(args, "kind", None)
    if kind is None:
        raise InputValidationError(
            "analysis segment requires --kind or the evaluate subcommand",
            field="kind",
        )
    if args.input is None:
        raise InputValidationError(
            "analysis segment --kind requires --input", field="input"
        )
    operation_id = ANALYSIS_SEGMENT_OPERATIONS[kind]
    read_all = bool(getattr(args, "all_pages", False))
    if read_all and operation_id not in ANALYSIS_PAGINATED_OPERATIONS:
        raise InputValidationError(
            f"--all-pages is unavailable for {operation_id}", field="all_pages"
        )
    client = build_client()
    stability = client.schema(operation_id).get("stability", "stable")
    if stability != "stable":
        if not bool(getattr(args, "experimental", False)):
            raise InputValidationError(
                "experimental analysis reads require --experimental",
                field="experimental",
            )
        client = build_client(allow_experimental=True)
    return call_read(
        client,
        operation_id,
        parse_object(args.input),
        read_all=read_all,
        **page_options(args, all_pages=True, active=read_all),
    )
def run_segment_evaluate_command(
    args: Any,
    build_client: Callable[[], Any],
    parse_object: Callable[[Any], Mapping[str, Any]],
    call_read: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    """Run schema, offline preview, or one governed aggregate evaluation."""

    if bool(getattr(args, "spec_schema", False)):
        if args.spec is not None:
            raise InputValidationError(
                "--spec-schema cannot be combined with --spec", field="spec_schema"
            )
        return segment_rule_spec_schema()
    if args.spec is None:
        raise InputValidationError(
            "segment evaluate requires --spec", field="spec"
        )
    spec = parse_object(args.spec)
    client = build_client()
    options = {
        "workspace": getattr(args, "workspace", None),
        "app": getattr(args, "app", None),
        "start": getattr(args, "start", None),
        "end": getattr(args, "end", None),
    }
    if bool(getattr(args, "segment_spec_dry_run", False)):
        return prepare_segment_spec(client, spec, **options)
    compiled = compile_segment_spec(spec, **options)
    fields = _selected_fields(getattr(args, "fields", None))
    if fields:
        validate_output_fields(
            client.schema(compiled.operation_id),
            fields,
            request_inputs=compiled.inputs,
        )
    result = call_read(client, compiled.operation_id, compiled.inputs)
    return project_output(
        client,
        compiled.operation_id,
        result,
        fields or None,
        request_inputs=compiled.inputs,
    )


def _selected_fields(values: Sequence[str] | None) -> tuple[str, ...]:
    if values is None:
        return ()
    selected = tuple(
        item.strip()
        for value in values
        for item in str(value).split(",")
        if item.strip()
    )
    if not selected:
        raise InputValidationError("--fields must not be empty", field="fields")
    return tuple(dict.fromkeys(selected))


__all__ = ["add_segment_commands", "run_segment_command"]
