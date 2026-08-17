"""One-pass inventory construction for multi-question Agent discovery."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .agent_analysis_task import analysis_task_cards
from .agent_capabilities import (
    analysis_query_spec_cards,
    composite_capability_cards,
    composite_capability_inventory,
)
from .agent_export import load_export_agent_inventory, query_requests_export
from .agent_handoff import is_analysis_task_handoff_query
from .agent_discovery_policy import (
    is_authoritative_local_question,
    operation_fallback_excluded,
)
from .agent_sources import snapshot_recipe_cards, workspace_catalog_fingerprint
from .agent_table_lineage import table_lineage_capability_cards
from .agent_user_journey import user_journey_capability_cards
from .errors import InputValidationError
from .find import _metadata_card
from .find_metadata import search_metadata
from .agent_vocabulary import is_workspace_vocabulary
from .workspace import load_workspace
from .actionable_error_values import actual_value


@dataclass(frozen=True)
class AgentSourceSnapshot:
    """One value-free inventory/workspace snapshot shared across questions."""

    workspace: Any | None
    operation_inventory: tuple[Mapping[str, Any], ...]
    recipe_inventory: tuple[Mapping[str, Any], ...]
    product_inventory: tuple[Mapping[str, Any], ...]
    metadata_inventory: tuple[Mapping[str, Any], ...]
    composite_inventory: tuple[Mapping[str, Any], ...]
    warnings: tuple[str, ...]
    workspace_fingerprint: str
    export_inventory: tuple[Mapping[str, Any], ...] = ()
    metadata_catalog_available: bool = True


def snapshot_agent_sources(
    client: Any,
    *,
    workspace: Any | None = None,
    questions: Sequence[Any] | None = None,
) -> AgentSourceSnapshot:
    """Load each discovery inventory once for a capabilities-many request."""

    selected_workspace, warnings = selected_workspace_and_warnings(workspace)
    metadata, metadata_available = metadata_inventory_state(warnings)
    recipes = snapshot_recipes(selected_workspace)
    composites = composite_capability_inventory()
    export_requested = any(
        query_requests_export(str(getattr(item, "query", "")))
        and not operation_fallback_excluded(str(getattr(item, "query", "")))
        for item in questions or ()
    )
    local_only = not export_requested and questions_use_only_local_catalog(
        questions,
        metadata,
        metadata_catalog_available=metadata_available,
        recipes=recipes,
        composites=composites,
    )
    inventory = () if local_only else operation_inventory(client)
    products = () if local_only else snapshot_products(selected_workspace, warnings)
    exports = (
        load_export_agent_inventory(client)
        if export_requested
        else ()
    )
    return AgentSourceSnapshot(
        workspace=selected_workspace,
        operation_inventory=inventory,
        recipe_inventory=recipes,
        product_inventory=products,
        metadata_inventory=metadata,
        composite_inventory=composites,
        warnings=tuple(warnings),
        workspace_fingerprint=workspace_catalog_fingerprint(selected_workspace),
        export_inventory=exports,
        metadata_catalog_available=metadata_available,
    )


def questions_use_only_local_catalog(
    questions: Sequence[Any] | None,
    metadata: tuple[Mapping[str, Any], ...],
    *,
    metadata_catalog_available: bool = True,
    recipes: tuple[Mapping[str, Any], ...] = (),
    composites: tuple[Mapping[str, Any], ...] = (),
) -> bool:
    """Prove every question is fully answered by an authoritative local card."""

    if not questions:
        return False
    vocabulary = tuple(item for item in metadata if is_workspace_vocabulary(item))
    for question in questions:
        domain = getattr(question, "domain", None)
        platform = getattr(question, "platform", None)
        query = str(getattr(question, "query", ""))
        cards = [
            *snapshot_recipe_cards(query, recipes),
            *analysis_query_spec_cards(query, domain=domain, platform=platform),
            *table_lineage_capability_cards(query, domain=domain, platform=platform),
            *user_journey_capability_cards(
                query, domain=domain, platform=platform
            ),
            *composite_capability_cards(
                query,
                domain=domain,
                platform=platform,
                inventory=composites,
            ),
            *(
                analysis_task_cards(
                    query,
                    metadata_rows=metadata if metadata_catalog_available else None,
                    domain=domain,
                    platform=platform,
                )
                if is_analysis_task_handoff_query(query)
                else []
            ),
        ]
        if platform is None and domain in {None, "metadata"}:
            cards.extend(_metadata_card(query, item) for item in vocabulary)
        if not is_authoritative_local_question(cards, query):
            return False
    return True


def selected_workspace_and_warnings(
    workspace: Any | None,
) -> tuple[Any | None, list[str]]:
    from .workspace_semantic_context import SemanticContextError

    try:
        return (load_workspace() if workspace is None else workspace), []
    except SemanticContextError:
        raise
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
            f"actual value: {actual_value(type(client).__name__)}; " + ("capabilities_many requires the complete offline operation inventory"),
            field="client",
        )
    return tuple(
        item
        for item in client.operations(stability=None)
        if isinstance(item, Mapping) and item.get("operation_id")
    )


def metadata_inventory_state(
    warnings: list[str],
) -> tuple[tuple[Mapping[str, Any], ...], bool]:
    try:
        result = search_metadata("", limit=None, offset=0)
        return (
            tuple(
                item
                for item in result.get("results", [])
                if isinstance(item, Mapping)
            ),
            True,
        )
    except (InputValidationError, OSError):
        warnings.append(
            "The default local metadata catalog is unavailable; run `gravity metadata "
            "sync --all-apps` before metadata discovery."
        )
        return (), False


def metadata_inventory(warnings: list[str]) -> tuple[Mapping[str, Any], ...]:
    """Compatibility wrapper for callers that only need the rows."""

    return metadata_inventory_state(warnings)[0]


def snapshot_recipes(workspace: Any | None) -> tuple[Mapping[str, Any], ...]:
    if workspace is None:
        return ()
    return tuple(
        {
            "name": str(name),
            "operation_id": recipe.operation,
            "description": recipe.description,
            "description_origin": "caller_workspace",
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
