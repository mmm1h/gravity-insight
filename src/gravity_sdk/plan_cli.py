"""Registration and dependency-injected dispatch hooks for ``gravity plan``."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from .plan import PlanAdapter, PlanAdapters, execute_plan, plan_schema


def add_plan_commands(
    commands: Any,
    concurrency_type: Callable[[str], int],
    add_input: Callable[..., None],
    *,
    handler: Callable[[Any, Any], Any] | None = None,
) -> None:
    """Register Plan v1 without constructing clients or owning CLI dispatch."""

    plan = commands.add_parser(
        "plan", help="Validate or execute one bounded cross-capability DAG."
    )
    actions = plan.add_subparsers(dest="plan_command", required=True)
    schema = actions.add_parser(
        "schema", help="Print the gravity.plan.v1 machine contract."
    )
    schema.set_defaults(network_required=False)
    run = actions.add_parser(
        "run", help="Execute a gravity.plan.v1 document with controlled adapters."
    )
    # Plan is a machine-facing surface: adapters report authentication failures
    # structurally, while fully local plans must never trigger an interactive
    # first-run prompt before their nodes are inspected.
    run.set_defaults(network_required=False)
    source = run.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--input", "-i",
        help="Inline Plan JSON, a JSON file, or '-' to read JSON from stdin.",
    )
    source.add_argument(
        "--recipe",
        help="Name of a parameterized Plan registered in the selected workspace.",
    )
    run.add_argument(
        "--set",
        dest="input_sets",
        action="append",
        default=[],
        metavar="PATH=VALUE",
        help="Override an input value by dotted path; JSON values are typed.",
    )
    run.add_argument(
        "--param",
        dest="parameters",
        action="append",
        default=[],
        metavar="NAME=VALUE",
        help="Bind one declared recipe parameter; JSON scalar values stay typed.",
    )
    run.add_argument(
        "--concurrency",
        type=concurrency_type,
        default=None,
        help="Override the plan outer worker budget (maximum: 24).",
    )
    run.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate the DAG and worst-case budgets without invoking adapters.",
    )
    if handler is not None:
        schema.set_defaults(_gravity_handler=handler)
        run.set_defaults(_gravity_handler=handler)


def run_plan_command(
    args: Any,
    *,
    adapters: PlanAdapters | Mapping[str, PlanAdapter],
    workspace: Any,
    object_input: Callable[[Any], Mapping[str, Any]] | None = None,
    resolved_plan: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Dispatch a registered plan command using caller-owned dependencies."""

    if args.plan_command == "schema":
        return plan_schema()
    if resolved_plan is not None:
        value = resolved_plan
    elif getattr(args, "recipe", None) is not None:
        from .workspace_plan_recipe import (
            PlanRecipeError,
            expand_plan_recipe,
            parse_plan_recipe_parameters,
        )

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
        if object_input is None:
            raise ValueError("plan run requires a decoded JSON object")
        value = object_input(value)
    return execute_plan(
        value,
        adapters=adapters,
        workspace=workspace,
        max_workers=args.concurrency,
        dry_run=bool(args.dry_run),
    )


__all__ = ["add_plan_commands", "run_plan_command"]
