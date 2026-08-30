"""Direct Agent handoff router for marker-governed mutation products."""

from __future__ import annotations

from typing import Any

from .kanban_mutation import kanban_mutation_cards
from .report_mutation import report_mutation_cards
from .custom_metric import custom_metric_cards
from .metadata_template import metadata_template_cards
from .saved_analysis_mutation import saved_analysis_mutation_cards
from .realtime_event import realtime_event_mutation_cards


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
