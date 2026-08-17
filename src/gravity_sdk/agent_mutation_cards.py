"""Direct Agent handoff router for marker-governed mutation products."""

from __future__ import annotations

from typing import Any

from .agent_kanban_mutation import kanban_mutation_cards
from .agent_report_mutation import report_mutation_cards
from .agent_custom_metric import custom_metric_cards
from .agent_metadata_template import metadata_template_cards
from .agent_saved_analysis_mutation import saved_analysis_mutation_cards
from .agent_realtime_event import realtime_event_mutation_cards


def mutation_cards(
    query: str, *, domain: str | None, platform: str | None
) -> list[dict[str, Any]]:
    return [
        *kanban_mutation_cards(query, domain=domain, platform=platform),
        *report_mutation_cards(query, domain=domain, platform=platform),
        *custom_metric_cards(query, domain=domain, platform=platform),
        *metadata_template_cards(query, domain=domain, platform=platform),
        *saved_analysis_mutation_cards(query, domain=domain, platform=platform),
        *realtime_event_mutation_cards(query, domain=domain, platform=platform),
    ]


__all__ = ["mutation_cards"]
