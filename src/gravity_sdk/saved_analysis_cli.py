"""CLI registration for saved Analysis catalog and strict replay."""

from __future__ import annotations

import argparse
from typing import Any, Callable, Mapping

from . import runtime
from .errors import InputValidationError
from .saved_analysis import (
    compile_saved_analysis_definition,
    execute_saved_analysis,
    list_saved_analyses,
    prepare_saved_analysis,
)
from .saved_analysis_artifact import validate_saved_window
from .workspace import load_workspace


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
    listing = commands.add_parser("list", help="List safe saved-Analysis identities.")
    _add_common(listing, positive_int, requires_reference=False, window=False)
    prepare = commands.add_parser(
        "prepare", help="Resolve and compile a saved definition without running it."
    )
    _add_common(prepare, positive_int, requires_reference=False, window=True)
    prepare.add_argument(
        "--definition",
        action=_OfflineDefinition,
        help="Inline JSON, JSON file, or '-' for a truly offline local definition.",
    )
    execute = commands.add_parser(
        "run", help="Resolve, strictly compile, and execute one saved definition."
    )
    _add_common(execute, positive_int, requires_reference=False, window=True)
    execute.add_argument(
        "--definition",
        help="Inline JSON, JSON file, or '-' for a caller-supplied definition.",
    )
    inspect = commands.add_parser(
        "get", help="Inspect replay eligibility without returning opaque config."
    )
    _add_common(inspect, positive_int, requires_reference=True, window=True)
    for parser in (listing, inspect, prepare, execute):
        parser.set_defaults(_gravity_handler=dispatch_saved_analysis)
    # Only an explicit definition can compile without catalog/detail reads.
    prepare.set_defaults(network_required=True)
    return analysis_commands


def dispatch_saved_analysis(args: Any, object_input: Callable[[Any], Mapping[str, Any]]) -> Any:
    reference, definition = _selected_source(args, object_input)
    start, end = getattr(args, "start", None), getattr(args, "end", None)
    validate_saved_window(start, end)
    if args.saved_command in {"prepare", "run"} and reference is not None and start is None:
        raise InputValidationError(
            "saved reference prepare/run requires --start and --end",
            field="start/end",
        )
    workspace = load_workspace()
    client = runtime.build_client()
    options = {
        "app": args.app,
        "workspace": workspace,
        "max_pages": args.max_pages,
        "max_items": args.max_items,
    }
    if args.saved_command == "list":
        return list_saved_analyses(client, **options)
    if args.saved_command == "get":
        from .saved_analysis import inspect_saved_analysis

        return inspect_saved_analysis(
            client,
            args.ref,
            app=args.app,
            workspace=workspace,
            max_pages=args.max_pages,
            max_items=args.max_items,
            start=start,
            end=end,
        )
    if definition is not None and args.saved_command == "prepare":
        return compile_saved_analysis_definition(
            client,
            definition,
            app=args.app,
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


def _add_common(
    parser: Any,
    positive_int: Callable[[str], int],
    *,
    requires_reference: bool,
    window: bool,
) -> None:
    parser.add_argument("--app", required=True)
    parser.add_argument("--ref", required=requires_reference)
    parser.add_argument("--max-pages", type=positive_int, default=1_000)
    parser.add_argument("--max-items", type=positive_int, default=100_000)
    if window:
        parser.add_argument("--start", help="Inclusive ISO replay start.")
        parser.add_argument("--end", help="Inclusive ISO replay end (maximum 90 days).")


def _selected_source(
    args: Any, object_input: Callable[[Any], Mapping[str, Any]]
) -> tuple[Any, Mapping[str, Any] | None]:
    if args.saved_command not in {"prepare", "run"}:
        return getattr(args, "ref", None), None
    reference = args.ref
    definition = object_input(args.definition) if args.definition is not None else None
    if (reference is None) == (definition is None):
        raise InputValidationError(
            "saved prepare/run requires exactly one --ref or --definition",
            field="ref/definition",
        )
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


__all__ = ["add_saved_analysis_commands", "dispatch_saved_analysis"]
