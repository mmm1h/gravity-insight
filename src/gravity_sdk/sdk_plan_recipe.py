"""Unified SDK conveniences for workspace-owned parameterized Plans."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class PlanRecipeSdkMixin:
    """Expand typed workspace parameters before using the existing Plan engine."""

    def expand_plan_recipe(
        self,
        name: str,
        parameters: Mapping[str, Any] | None = None,
        *,
        workspace: Any | None = None,
    ) -> dict[str, Any]:
        from .workspace_plan_recipe import expand_plan_recipe

        selected = self._select_workspace(workspace)
        return expand_plan_recipe(selected.plan_recipe(name), parameters)

    def validate_plan_recipe(
        self,
        name: str,
        parameters: Mapping[str, Any] | None = None,
        *,
        workspace: Any | None = None,
        max_workers: int = 6,
    ) -> dict[str, Any]:
        """Expand and fully preflight one workspace Plan recipe with zero execution."""

        selected = self._select_workspace(workspace)
        plan = self.expand_plan_recipe(name, parameters, workspace=selected)
        return self.validate_plan(plan, workspace=selected, max_workers=max_workers)

    def execute_plan_recipe(
        self,
        name: str,
        parameters: Mapping[str, Any] | None = None,
        *,
        workspace: Any | None = None,
        max_workers: int = 6,
        dry_run: bool = False,
        metadata_database: Any | None = None,
    ) -> dict[str, Any]:
        """Expand one recipe and delegate unchanged Plan v1 execution semantics."""

        selected = self._select_workspace(workspace)
        plan = self.expand_plan_recipe(name, parameters, workspace=selected)
        return self.execute_plan(
            plan,
            workspace=selected,
            max_workers=max_workers,
            dry_run=dry_run,
            metadata_database=metadata_database,
        )


__all__ = ["PlanRecipeSdkMixin"]
