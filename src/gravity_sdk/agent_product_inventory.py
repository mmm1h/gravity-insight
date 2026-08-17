"""Complete product-card projection over the existing Agent card owners."""

from __future__ import annotations

import copy
from typing import Any

from .agent_analysis import analysis_query_spec_inventory
from .agent_app_catalog import app_catalog_capability_inventory
from .agent_capabilities import (
    composite_capability_cards,
    composite_capability_inventory,
)
from .agent_export import export_capability_inventory
from .agent_material_asset import material_asset_capability_inventory
from .agent_kanban_mutation import kanban_mutation_capability_inventory
from .agent_metadata_search import metadata_search_capability_inventory
from .agent_metadata_onboarding import metadata_onboarding_capability_inventory
from .agent_report_mutation import report_mutation_capability_inventory
from .agent_segment import segment_capability_inventory
from .agent_table_lineage import table_lineage_capability_inventory
from .agent_user_journey import user_journey_capability_inventory
from .agent_custom_metric import custom_metric_capability_inventory
from .agent_metadata_template import metadata_template_capability_inventory
from .agent_saved_analysis_mutation import (
    saved_analysis_mutation_capability_inventory,
)


def canonical_capability_cards(client: Any) -> tuple[dict[str, Any], ...]:
    """Return every static product card from the existing Agent card owners."""

    definitions = composite_capability_inventory()
    composites = tuple(
        composite_capability_cards(
            f"composite:{definition['name']}",
            domain=None,
            platform=None,
            inventory=definitions,
        )[0]
        for definition in definitions
    )
    cards = (
        *composites,
        *app_catalog_capability_inventory(),
        *analysis_query_spec_inventory(),
        *segment_capability_inventory(),
        *kanban_mutation_capability_inventory(),
        *report_mutation_capability_inventory(),
        *custom_metric_capability_inventory(),
        *metadata_template_capability_inventory(),
        *saved_analysis_mutation_capability_inventory(),
        *user_journey_capability_inventory(),
        *material_asset_capability_inventory(),
        *metadata_search_capability_inventory(),
        *metadata_onboarding_capability_inventory(),
        *table_lineage_capability_inventory(),
        *export_capability_inventory(client),
    )
    selectors = [str(card.get("selector", "")) for card in cards]
    if any(not selector for selector in selectors) or len(set(selectors)) != len(cards):
        raise RuntimeError("canonical Agent product-card selectors must be unique")
    return tuple(copy.deepcopy(card) for card in cards)


__all__ = ["canonical_capability_cards"]
