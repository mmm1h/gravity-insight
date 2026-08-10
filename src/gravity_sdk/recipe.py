"""Offline validation and drift checks for workspace-owned recipes."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from typing import Any, Callable

from .workspace import Recipe, Workspace, load_workspace


VALIDATION_SCHEMA = "gravity.recipe-validation.v1"
CHECK_SCHEMA = "gravity.recipe-check.v1"


def add_recipe_commands(commands: Any) -> None:
    recipe = commands.add_parser(
        "recipe", help="Validate or check workspace-owned named queries."
    )
    recipe.set_defaults(network_required=False, _gravity_handler=_dispatch_recipe)
    subcommands = recipe.add_subparsers(dest="recipe_command", required=True)
    for name in ("validate", "check"):
        command = subcommands.add_parser(name)
        command.add_argument("name")


def validate_recipe(workspace: Workspace, name: str) -> dict[str, Any]:
    recipe = workspace.recipe(name)
    return {
        "schema_version": VALIDATION_SCHEMA,
        "ok": True,
        "status": "ok",
        "offline": True,
        "workspace": str(workspace.path) if workspace.path is not None else None,
        "recipe": recipe.name,
        "operation_id": recipe.operation,
        "bindings": _binding_shape(recipe),
        "parameters": sorted(recipe.parameters),
        "required_parameters": list(recipe.required_parameters),
        "input_fields": sorted(recipe.input),
        "output_fields": list(recipe.output_fields),
        "contract_fingerprint": recipe.contract_fingerprint,
    }


def check_recipe(recipe: Recipe, client: Any) -> dict[str, Any]:
    try:
        description = client.describe(recipe.operation)
    except Exception as exc:
        return {
            "schema_version": CHECK_SCHEMA,
            "ok": False,
            "status": "stale",
            "offline": True,
            "recipe": recipe.name,
            "operation_id": recipe.operation,
            "reasons": [
                {
                    "code": "operation_missing",
                    "message": str(exc),
                }
            ],
        }
    reasons = [
        *_availability_reasons(description),
        *_input_reasons(recipe, description.get("input_schema", {})),
        *_output_reasons(recipe, description.get("response_projection", {})),
    ]
    current_fingerprint = _current_fingerprint(description)
    if current_fingerprint != recipe.contract_fingerprint:
        reasons.append({
            "code": "contract_fingerprint_changed",
            "expected": recipe.contract_fingerprint,
            "actual": current_fingerprint,
        })
    stale = bool(reasons)
    return {
        "schema_version": CHECK_SCHEMA,
        "ok": not stale,
        "status": "stale" if stale else "ok",
        "offline": True,
        "recipe": recipe.name,
        "operation_id": recipe.operation,
        "stability": str(description.get("stability", "")),
        "contract_fingerprint": current_fingerprint,
        "reasons": reasons,
    }


def _availability_reasons(description: Mapping[str, Any]) -> list[dict[str, Any]]:
    reasons: list[dict[str, Any]] = []
    stability = str(description.get("stability", ""))
    if stability == "deprecated":
        reasons.append({"code": "operation_deprecated", "actual": stability})
    if description.get("executable") is False:
        reasons.append({
            "code": "operation_not_executable",
            "reason": description.get("block_reason"),
        })
    return reasons


def _input_reasons(recipe: Recipe, input_schema: Any) -> list[dict[str, Any]]:
    if not isinstance(input_schema, Mapping):
        input_schema = {}
    declared = _declared_input_fields(recipe)
    removed = sorted(declared - set(input_schema))
    required = {
        str(field)
        for field, specification in input_schema.items()
        if isinstance(specification, Mapping)
        and specification.get("required") is True
        and "default" not in specification
    }
    unbound = sorted(required - declared)
    reasons: list[dict[str, Any]] = []
    if removed:
        reasons.append({"code": "input_fields_changed", "missing_fields": removed})
    if unbound:
        reasons.append({"code": "required_inputs_unbound", "fields": unbound})
    return reasons


def _output_reasons(recipe: Recipe, projection: Any) -> list[dict[str, Any]]:
    removed = sorted(set(recipe.output_fields) - _projection_fields(projection))
    return (
        [{"code": "output_fields_changed", "missing_fields": removed}]
        if removed
        else []
    )


def _current_fingerprint(description: Mapping[str, Any]) -> str | None:
    health = description.get("health", {})
    value = health.get("contract_fingerprint") if isinstance(health, Mapping) else None
    return value if isinstance(value, str) else None


def run_recipe_command(
    args: argparse.Namespace,
    client_factory: Callable[[argparse.Namespace], Any],
    *,
    workspace: Workspace | None = None,
) -> dict[str, Any]:
    selected = load_workspace() if workspace is None else workspace
    if args.recipe_command == "validate":
        return validate_recipe(selected, args.name)
    return check_recipe(selected.recipe(args.name), client_factory(args))


def _dispatch_recipe(args: argparse.Namespace, _object_input: Callable[[Any], Any]) -> Any:
    from . import runtime

    return run_recipe_command(args, lambda _args: runtime.build_client())


def _binding_shape(recipe: Recipe) -> dict[str, Any]:
    bindings = recipe.bindings
    return {
        "app": {
            "configured": bindings.app_ref is not None,
            "input": bindings.app_input,
        },
        "report": {
            "configured": bindings.report_ref is not None,
            "input": bindings.report_input,
        },
    }


def _declared_input_fields(recipe: Recipe) -> set[str]:
    fields = set(recipe.input)
    fields.update(path.split(".", 1)[0] for path in recipe.parameters.values())
    for path in (recipe.bindings.app_input, recipe.bindings.report_input):
        if path:
            fields.add(path.split(".", 1)[0])
    return fields


def _projection_fields(value: Any) -> set[str]:
    if not isinstance(value, Mapping):
        return set()
    fields: set[str] = set()
    for name in ("data_keys", "item_keys", "dynamic_item_fields"):
        items = value.get(name, [])
        if isinstance(items, list):
            fields.update(str(item).split(".", 1)[0] for item in items)
    return fields


__all__ = [
    "add_recipe_commands",
    "check_recipe",
    "run_recipe_command",
    "validate_recipe",
]
