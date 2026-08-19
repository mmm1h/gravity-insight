"""CLI registration for saved Analysis catalog and strict replay."""

from __future__ import annotations

import argparse
from typing import Any, Callable, Mapping

from . import runtime
from .cli_limits import concurrency
from .errors import InputValidationError
from .saved_analysis import (
    compile_saved_analysis_definition,
    execute_saved_analysis,
    list_saved_analyses,
    prepare_saved_analysis,
)
from .saved_analysis_artifact import preflight_saved_definition, validate_saved_window
from .saved_analysis_support import (
    SUBJECT_KINDS,
    bounds,
    normalize_definition,
    normalize_reference,
    validate_definition_shape,
    workers,
)
from .workspace import load_workspace
from .workspace_app import resolve_workspace_app
from .actionable_error_values import actual_value


def add_saved_analysis_commands(
    commands: Any,
    positive_int: Callable[[str], int],
) -> Any:
    analysis = commands.add_parser("analysis")
    analysis_commands = analysis.add_subparsers(
        dest="analysis_command", required=True
    )
    saved = analysis_commands.add_parser(
        "saved", help="List, prepare, or strictly replay saved Analysis definitions."
    )
    commands = saved.add_subparsers(dest="saved_command", required=True)
    listing = commands.add_parser(
        "list", help="List identities with replay eligibility left unchecked."
    )
    _add_common(
        listing, positive_int, include_reference=False, requires_reference=False,
        window=False,
    )
    prepare = commands.add_parser(
        "prepare", help="Resolve and compile a saved definition without running it."
    )
    _add_common(
        prepare, positive_int, include_reference=True, requires_reference=False,
        window=True,
    )
    prepare.add_argument(
        "--definition",
        action=_OfflineDefinition,
        help="Inline JSON, JSON file, or '-' for a truly offline local definition.",
    )
    execute = commands.add_parser(
        "run", help="Resolve, strictly compile, and execute one saved definition."
    )
    _add_common(
        execute, positive_int, include_reference=True, requires_reference=False,
        window=True,
    )
    execute.add_argument(
        "--definition",
        help="Inline JSON, JSON file, or '-' for a caller-supplied definition.",
    )
    create = commands.add_parser(
        "create", help="Preview or create one marked reusable saved Analysis."
    )
    _add_mutation_definition(create, include_id=False)
    create.add_argument("--idempotency-key")
    update = commands.add_parser(
        "update", help="Preview or replace one saved Analysis full definition."
    )
    _add_mutation_definition(update, include_id=True)
    delete = commands.add_parser(
        "delete", help="Preview or delete one marker-or-owner saved Analysis."
    )
    delete.add_argument("--app", required=True, type=_nonempty_app)
    delete.add_argument("--id", required=True)
    _mutation_mode(delete)
    inspect = commands.add_parser(
        "get", help="Inspect replay eligibility without returning opaque config."
    )
    _add_common(
        inspect, positive_int, include_reference=True, requires_reference=True,
        window=True,
    )
    for parser in (listing, inspect, prepare, execute, create, update, delete):
        parser.set_defaults(_gravity_handler=dispatch_saved_analysis)
    # Only an explicit definition can compile without catalog/detail reads.
    prepare.set_defaults(network_required=True)
    from .template_replay_surface import add_template_commands

    add_template_commands(analysis_commands, positive_int)
    return analysis_commands


def dispatch_saved_analysis(args: Any, object_input: Callable[[Any], Mapping[str, Any]]) -> Any:
    if args.saved_command in {"create", "update", "delete"}:
        return _dispatch_mutation(args, object_input)
    reference, definition = _selected_source(args, object_input)
    start, end = getattr(args, "start", None), getattr(args, "end", None)
    validate_saved_window(start, end)
    bounds(args.max_pages, args.max_items)
    workers(args.concurrency)
    workspace = load_workspace()
    app_id = resolve_workspace_app(workspace, args.app)
    if definition is not None:
        normalized, _metadata = normalize_definition(
            definition, expected_app_id=str(app_id)
        )
        preflight_saved_definition(
            normalized, app=str(app_id), workspace=workspace, start=start, end=end
        )
    client = runtime.build_client()
    options = {
        "app": app_id,
        "workspace": workspace,
        "max_pages": args.max_pages,
        "max_items": args.max_items,
        "max_workers": args.concurrency,
    }
    if args.saved_command == "list":
        return list_saved_analyses(client, **options)
    if args.saved_command == "get":
        from .saved_analysis import inspect_saved_analysis

        return inspect_saved_analysis(
            client,
            args.ref,
            app=app_id,
            workspace=workspace,
            max_pages=args.max_pages,
            max_items=args.max_items,
            max_workers=args.concurrency,
            start=start,
            end=end,
        )
    if definition is not None and args.saved_command == "prepare":
        return compile_saved_analysis_definition(
            client,
            definition,
            app=app_id,
            workspace=workspace,
            start=start,
            end=end,
        )
    function = (
        prepare_saved_analysis
        if args.saved_command == "prepare"
        else execute_saved_analysis
    )
    return function(
        client,
        reference=reference,
        definition=definition,
        start=start,
        end=end,
        **options,
    )


def _dispatch_mutation(
    args: Any, object_input: Callable[[Any], Mapping[str, Any]]
) -> dict[str, Any]:
    from .saved_analysis_mutation import (
        create_saved_analysis,
        delete_saved_analysis,
        update_saved_analysis,
    )

    workspace = load_workspace()
    app_id = resolve_workspace_app(workspace, args.app)
    options = {
        "app_id": app_id,
        "workspace": workspace,
        "execute": bool(args.saved_execute),
    }
    if args.saved_command == "delete":
        return delete_saved_analysis(
            runtime.build_client(), args.id, **options
        )
    definition = {
        "name": args.name,
        "subject": args.subject,
        "config": object_input(args.config),
        "remark": args.remark,
        "start": args.start,
        "end": args.end,
    }
    if args.saved_command == "create":
        return create_saved_analysis(
            runtime.build_client(),
            **options,
            **definition,
            idempotency_key=args.idempotency_key,
        )
    return update_saved_analysis(
        runtime.build_client(), args.id, **options, **definition
    )


def _add_common(
    parser: Any,
    positive_int: Callable[[str], int],
    *,
    include_reference: bool,
    requires_reference: bool,
    window: bool,
) -> None:
    parser.add_argument("--app", required=True, type=_nonempty_app)
    if include_reference:
        parser.add_argument("--ref", required=requires_reference)
    parser.add_argument("--max-pages", type=positive_int, default=1_000)
    parser.add_argument("--max-items", type=positive_int, default=100_000)
    parser.add_argument(
        "--concurrency", type=concurrency, default=6,
        help="Parallel catalog page workers when totals are known (default: 6, max: 24).",
    )
    if window:
        parser.add_argument("--start", help="Inclusive ISO replay start.")
        parser.add_argument("--end", help="Inclusive ISO replay end (maximum 90 days).")
    parser.add_argument(
        "--output", type=_output_path,
        help="Write JSON or NDJSON to this local path (use omission for stdout).",
    )
    parser.add_argument(
        "--format", choices=("json", "ndjson"), default="json",
        help="Output encoding; NDJSON may stream to stdout.",
    )


def _selected_source(
    args: Any, object_input: Callable[[Any], Mapping[str, Any]]
) -> tuple[Any, Mapping[str, Any] | None]:
    if args.saved_command not in {"prepare", "run"}:
        reference = getattr(args, "ref", None)
        if reference is not None:
            normalize_reference(reference)
        return reference, None
    reference = args.ref
    definition = object_input(args.definition) if args.definition is not None else None
    if (reference is None) == (definition is None):
        raise InputValidationError(
            f"actual value: {actual_value((reference, definition))}; " + ("saved prepare/run requires exactly one --ref or --definition"),
            field="ref/definition",
        )
    if reference is not None:
        normalize_reference(reference)
    if definition is not None:
        validate_definition_shape(definition)
    return reference, definition


class _OfflineDefinition(argparse.Action):
    """Mark explicit-definition preparation as credential-free local work."""

    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: Any,
        option_string: str | None = None,
    ) -> None:
        setattr(namespace, self.dest, values)
        setattr(namespace, "network_required", False)


def _add_mutation_definition(parser: Any, *, include_id: bool) -> None:
    parser.add_argument("--app", required=True, type=_nonempty_app)
    if include_id:
        parser.add_argument("--id", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--subject", required=True, choices=sorted(SUBJECT_KINDS))
    parser.add_argument("--config", required=True, help="Analysis config JSON/file/'-'.")
    parser.add_argument("--remark", default="")
    parser.add_argument("--start", help="Validation window start for a Web artifact.")
    parser.add_argument("--end", help="Validation window end for a Web artifact.")
    _mutation_mode(parser)


def _mutation_mode(parser: Any) -> None:
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", dest="saved_dry_run", action="store_true")
    mode.add_argument("--execute", dest="saved_execute", action="store_true")
    parser.set_defaults(network_required=False)


def _output_path(value: str) -> str:
    if not value.strip() or value == "-":
        raise argparse.ArgumentTypeError(
            "saved Analysis --output must be a local path; omit it for stdout"
        )
    return value


def _nonempty_app(value: str) -> str:
    if not value.strip():
        raise argparse.ArgumentTypeError("saved Analysis --app must not be empty")
    return value


__all__ = ["add_saved_analysis_commands", "dispatch_saved_analysis"]
