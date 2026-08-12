"""Product CLI bridge for the dependency-injected Plan v1 engine."""

from __future__ import annotations

from typing import Any


def dispatch(args: Any, object_input: Any) -> dict[str, Any]:
    """Bind one workspace and construct only the governed Plan adapters."""

    from .plan import plan_schema

    if args.plan_command == "schema":
        return plan_schema()

    from .plan_adapters import build_plan_adapters
    from .plan_cli import run_plan_command
    from .sdk import GravitySDK
    from .workspace import load_workspace

    workspace = load_workspace()
    sdk = GravitySDK.from_env(workspace=workspace)
    return run_plan_command(
        args,
        adapters=build_plan_adapters(sdk, workspace=workspace),
        workspace=workspace,
        object_input=object_input,
    )


__all__ = ["dispatch"]
