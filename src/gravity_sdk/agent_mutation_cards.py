"""Direct Agent handoff router for marker-governed mutation products."""

from __future__ import annotations

from typing import Any

from .agent_kanban_mutation import kanban_mutation_cards
from .agent_report_mutation import report_mutation_cards


def mutation_cards(
    query: str, *, domain: str | None, platform: str | None
) -> list[dict[str, Any]]:
    return [
        *kanban_mutation_cards(query, domain=domain, platform=platform),
        *report_mutation_cards(query, domain=domain, platform=platform),
    ]


__all__ = ["mutation_cards"]
