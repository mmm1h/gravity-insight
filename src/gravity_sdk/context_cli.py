"""Offline CLI for the built-in project Repo Context Provider."""

from __future__ import annotations

import argparse
from typing import Any, Callable, Mapping

from .actionable_error_values import actual_value
from .errors import InputValidationError
from .repo_context_provider import RepoContextProvider


def add_context_commands(commands: Any, add_input: Callable[..., None]) -> Any:
    context = commands.add_parser(
        "context", help="Discover and assemble bounded local Context Packs."
    )
    providers = context.add_subparsers(dest="context_provider", required=True)
    project = providers.add_parser(
        "project", help="Use the built-in Git-backed project Repo Provider."
    )
    actions = project.add_subparsers(dest="context_command", required=True)

    describe = actions.add_parser("describe")
    index = actions.add_parser("index")
    search = actions.add_parser("search")
    search.add_argument("query")
    search.add_argument("--maximum", type=_positive_integer)
    search.add_argument("--excerpt-lines", type=_positive_integer)
    get = actions.add_parser("get")
    get.add_argument("uri")
    get.add_argument("--maximum-lines", type=_positive_integer)
    pack = actions.add_parser("pack")
    add_input(pack, required=True)
    verify = actions.add_parser("verify")
    add_input(verify, required=True)

    for parser in (describe, index, search, get, pack, verify):
        parser.add_argument("--root", default=".")
        parser.add_argument("--project-id", required=True)
        parser.set_defaults(network_required=False, _gravity_handler=dispatch)
    return context


def dispatch(
    args: Any, object_input: Callable[[Any], Mapping[str, Any]]
) -> dict[str, Any]:
    provider = RepoContextProvider(args.root, project_id=args.project_id)
    command = args.context_command
    if command == "describe":
        return provider.describe()
    if command == "index":
        return provider.index()
    if command == "search":
        return provider.search(
            args.query,
            maximum=args.maximum,
            excerpt_lines=args.excerpt_lines,
        )
    if command == "get":
        return provider.get(args.uri, maximum_lines=args.maximum_lines)
    payload = object_input(args.input)
    if command == "verify":
        return provider.verify(payload)
    request = _pack_request(payload)
    return provider.pack(
        request["requirement"],
        requested_time=request["requested_time"],
        entity_aliases=request.get("entity_aliases"),
    )


def _pack_request(value: Mapping[str, Any]) -> dict[str, Any]:
    required = {"requirement", "requested_time"}
    allowed = {*required, "entity_aliases"}
    if not isinstance(value, Mapping) or not required.issubset(value) or set(value) - allowed:
        shape = sorted(value) if isinstance(value, Mapping) else type(value).__name__
        raise InputValidationError(
            f"actual value: {actual_value(shape)}; Context Pack input must contain requirement and requested_time only, with optional entity_aliases",
            field="input",
            next_action="Pass one explicit Context Requirement and its requested time windows.",
        )
    if not isinstance(value["requirement"], Mapping) or not isinstance(
        value["requested_time"], Mapping
    ):
        shape = {
            "requirement": type(value["requirement"]).__name__,
            "requested_time": type(value["requested_time"]).__name__,
        }
        raise InputValidationError(
            f"actual value: {actual_value(shape)}; Context Pack requirement and requested_time must be objects",
            field="input",
            next_action="Pass the formal Context Requirement and named time-window objects.",
        )
    aliases = value.get("entity_aliases")
    if aliases is not None and not isinstance(aliases, Mapping):
        raise InputValidationError(
            f"actual value: {actual_value(type(aliases).__name__)}; Context Pack entity_aliases must be an object",
            field="input.entity_aliases",
            next_action="Pass a JSON object mapping declared aliases to Semantic entity URIs.",
        )
    return dict(value)


def _positive_integer(value: str) -> int:
    selected = int(value)
    if selected < 1:
        raise argparse.ArgumentTypeError("value must be positive")
    return selected


__all__ = ["add_context_commands", "dispatch"]
