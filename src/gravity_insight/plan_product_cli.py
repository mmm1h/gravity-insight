"""Product CLI bridge for the dependency-injected Plan v1 engine."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def dispatch(args: Any, object_input: Any) -> dict[str, Any]:
    """Bind one workspace and construct only the governed Plan adapters."""

    from .plan import plan_schema

    if args.plan_command == "schema":
        return plan_schema()

    workspace = None
    if getattr(args, "recipe", None) is not None:
        from .workspace import load_workspace
        from .workspace_plan_recipe import (
            PlanRecipeError,
            expand_plan_recipe,
            parse_plan_recipe_parameters,
        )

        workspace = load_workspace()
        if getattr(args, "input_sets", []):
            raise PlanRecipeError(
                "--set must not be combined with --recipe; omit one",
                field="set",
            )
        value = expand_plan_recipe(
            workspace.plan_recipe(args.recipe),
            parse_plan_recipe_parameters(getattr(args, "parameters", [])),
        )
    else:
        if getattr(args, "parameters", []):
            raise ValueError("--param requires --recipe")
        value = args.input
        if not isinstance(value, Mapping):
            value = object_input(value)

    from .plan import PlanAdapters, validate_plan
    from .plan_cli import run_plan_command
    validated = validate_plan(value)
    if all(node.kind == "metadata_search" for node in validated.nodes):
        from .plan_metadata_adapter import build_metadata_plan_adapter

        return run_plan_command(
            args,
            adapters=PlanAdapters(metadata_search=build_metadata_plan_adapter()),
            workspace=workspace,
            resolved_plan=value,
        )

    from .plan_adapters import build_plan_adapters
    from .sdk import GravitySDK

    if workspace is None:
        from .workspace import load_workspace

        workspace = load_workspace()
    sdk = GravitySDK.from_env(workspace=workspace)
    return run_plan_command(
        args,
        adapters=build_plan_adapters(sdk, workspace=workspace),
        workspace=workspace,
        resolved_plan=value,
    )


__all__ = ["dispatch"]
