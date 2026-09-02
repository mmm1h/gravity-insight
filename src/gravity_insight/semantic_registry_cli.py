"""Offline CLI for versioned Business Semantic sources."""

from __future__ import annotations

from typing import Any, Callable, Mapping

from .actionable_error_values import actual_value
from .errors import ErrorCategory, InputValidationError, exit_code_for_category
from .semantic_contract import SemanticContractError, load_semantic_source
from .semantic_registry import SemanticRegistry


_KINDS = (
    "metric",
    "dimension",
    "entity",
    "cohort",
    "event",
    "sku",
    "activity",
    "release",
    "schema",
)
_LOCAL_EXIT = exit_code_for_category(ErrorCategory.LOCAL)


def add_semantic_registry_commands(commands: Any, add_input: Callable[..., None]) -> Any:
    semantics = commands.add_parser(
        "semantics",
        help="Inspect and validate exact local Business Semantic contracts.",
    )
    actions = semantics.add_subparsers(dest="semantics_command", required=True)

    listed = actions.add_parser("list", help="List compiled Semantic Definitions.")
    _add_sources(listed)
    listed.add_argument("--kind", choices=_KINDS)

    describe = actions.add_parser(
        "describe", help="Describe one exact versioned Semantic URI."
    )
    describe.add_argument("uri")
    _add_sources(describe)

    resolve = actions.add_parser(
        "resolve", help="Resolve one Definition and project Binding for a time scope."
    )
    resolve.add_argument("uri")
    _add_sources(resolve)
    resolve.add_argument("--project-id")
    resolve.add_argument("--app-alias")
    resolve.add_argument("--at")
    resolve.add_argument("--start")
    resolve.add_argument("--end")

    validate = actions.add_parser(
        "validate", help="Validate one JSON/TOML Semantic Source offline."
    )
    add_input(validate)
    validate.add_argument("--source", dest="semantic_validate_source")

    for parser in (listed, describe, resolve, validate):
        parser.set_defaults(network_required=False, _gravity_handler=dispatch)
    return semantics


def dispatch(
    args: Any, object_input: Callable[[Any], Mapping[str, Any]]
) -> dict[str, Any]:
    command = args.semantics_command
    if command == "validate":
        return _validate(args, object_input)
    registry = SemanticRegistry.from_paths(getattr(args, "semantic_sources", ()))
    if command == "list":
        return registry.list(kind=args.kind)
    if command == "describe":
        return registry.describe(args.uri)
    return registry.resolve(
        args.uri,
        project_id=args.project_id,
        app_alias=args.app_alias,
        at=args.at,
        start=args.start,
        end=args.end,
    )


def _add_sources(parser: Any) -> None:
    parser.add_argument(
        "--source",
        dest="semantic_sources",
        action="append",
        default=[],
        help="Local gravity.semantic-source.v1 JSON/TOML file; may be repeated.",
    )


def _validate(
    args: Any, object_input: Callable[[Any], Mapping[str, Any]]
) -> dict[str, Any]:
    source_path = getattr(args, "semantic_validate_source", None)
    inline = getattr(args, "input", None)
    if (source_path is None) == (inline is None):
        raise InputValidationError(
            f"actual value: {actual_value({'source': source_path, 'input': inline})}; "
            "provide exactly one of --source or --input",
            field="source/input",
            next_action="Retry with `gravity semantics validate --source <file.json|file.toml>`.",
        )
    try:
        source = (
            load_semantic_source(source_path)["source"]
            if source_path is not None
            else dict(object_input(inline))
        )
    except SemanticContractError as exc:
        return {
            "schema_version": "gravity.semantic-validation.v1",
            "status": "invalid",
            "ok": False,
            "exit_code": _LOCAL_EXIT,
            "reason_codes": [exc.reason_code],
            "network_called": False,
        }
    return SemanticRegistry().validate(source)


__all__ = ["add_semantic_registry_commands", "dispatch"]
