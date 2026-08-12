"""One-pass inventory construction for multi-question Agent discovery."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .agent_sources import workspace_catalog_fingerprint
from .errors import InputValidationError
from .find_metadata import search_metadata
from .workspace import load_workspace


@dataclass(frozen=True)
class AgentSourceSnapshot:
    """One value-free inventory/workspace snapshot shared across questions."""

    workspace: Any | None
    operation_inventory: tuple[Mapping[str, Any], ...]
    recipe_inventory: tuple[Mapping[str, Any], ...]
    product_inventory: tuple[Mapping[str, Any], ...]
    metadata_inventory: tuple[Mapping[str, Any], ...]
    warnings: tuple[str, ...]
    workspace_fingerprint: str


def snapshot_agent_sources(
    client: Any, *, workspace: Any | None = None
) -> AgentSourceSnapshot:
    """Load each discovery inventory once for a capabilities-many request."""

    selected_workspace, warnings = selected_workspace_and_warnings(workspace)
    inventory = operation_inventory(client)
    metadata = metadata_inventory(warnings)
    recipes = snapshot_recipes(selected_workspace)
    products = snapshot_products(selected_workspace, warnings)
    return AgentSourceSnapshot(
        selected_workspace,
        inventory,
        recipes,
        products,
        metadata,
        tuple(warnings),
        workspace_catalog_fingerprint(selected_workspace),
    )


def selected_workspace_and_warnings(
    workspace: Any | None,
) -> tuple[Any | None, list[str]]:
    try:
        return (load_workspace() if workspace is None else workspace), []
    except (OSError, ValueError):
        return None, [
            "The workspace catalog could not be loaded; recipe and SQL product "
            "discovery are unavailable."
        ]


def operation_inventory(client: Any) -> tuple[Mapping[str, Any], ...]:
    inventory = getattr(client, "operation_inventory", None)
    if callable(inventory):
        return tuple(
            item
            for item in inventory(stability=None)
            if isinstance(item, Mapping) and item.get("operation_id")
        )
    if not callable(getattr(client, "operations", None)):
        raise InputValidationError(
            "capabilities_many requires the complete offline operation inventory",
            field="client",
        )
    return tuple(
        item
        for item in client.operations(stability=None)
        if isinstance(item, Mapping) and item.get("operation_id")
    )


def metadata_inventory(warnings: list[str]) -> tuple[Mapping[str, Any], ...]:
    try:
        result = search_metadata("", limit=None, offset=0)
        return tuple(
            item for item in result.get("results", []) if isinstance(item, Mapping)
        )
    except (InputValidationError, OSError):
        warnings.append(
            "The default local metadata catalog is unavailable; run `gravity metadata "
            "sync --all-apps` before metadata discovery."
        )
        return ()


def snapshot_recipes(workspace: Any | None) -> tuple[Mapping[str, Any], ...]:
    if workspace is None:
        return ()
    return tuple(
        {
            "name": str(name),
            "operation_id": recipe.operation,
            "description": recipe.description,
            "required_parameters": list(recipe.required_parameters),
            "parameter_bindings": dict(recipe.parameters),
            "output_fields": list(recipe.output_fields),
        }
        for name, recipe in sorted(workspace.recipes.items())
    )


def snapshot_products(
    workspace: Any | None, warnings: list[str]
) -> tuple[Mapping[str, Any], ...]:
    if workspace is None:
        return ()
    try:
        from .sql.catalog import describe_products

        return tuple(describe_products(workspace))
    except (OSError, ValueError, KeyError, TypeError):
        warnings.append(
            "The workspace SQL product catalog is invalid; run `gravity sql --dry-run`."
        )
        return ()


__all__ = ["AgentSourceSnapshot", "snapshot_agent_sources"]
