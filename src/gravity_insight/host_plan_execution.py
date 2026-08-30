"""Thin SDK execution surface for an origin-isolated host Plan."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .host_effects import compile_host_plan


def execute_host_plan(
    sdk: Any,
    host_plan: Mapping[str, Any],
    sources: Mapping[str, Any],
    *,
    workspace: Any | None = None,
    max_workers: int = 6,
    dry_run: bool = False,
    metadata_database: Any | None = None,
) -> dict[str, Any]:
    """Compile the trusted-source wrapper before calling the normal Plan facade."""

    mutation_operations = {
        str(item["operation_id"])
        for item in sdk.insight.operations(stability="stable")
        if isinstance(item, Mapping)
        and item.get("effect") == "mutation"
        and item.get("operation_id")
    }
    compiled = compile_host_plan(
        host_plan, sources, mutation_operations=mutation_operations
    )
    return sdk.execute_plan(
        compiled["plan"],
        workspace=workspace,
        max_workers=max_workers,
        dry_run=dry_run,
        metadata_database=metadata_database,
    )


__all__ = ["execute_host_plan"]
