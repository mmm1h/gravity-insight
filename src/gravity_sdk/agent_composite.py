"""Shared construction for value-free Agent composite cards."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def composite_card(
    query: str, normalized: str, domain: str | None, definition: Mapping[str, Any]
) -> dict[str, Any] | None:
    from .agent_capabilities import agent_query_match

    selection = _selection(query, domain, definition)
    if selection is None:
        return None
    name, selected_domain, accepted, dashboard = selection
    selector = f"composite:{name}"
    match = agent_query_match(
        query, selector, name, name.replace("_", " "), selected_domain, *accepted,
        definition.get("description"),
        *(str(value) for value in definition.get("aliases", ())),
    )
    if dashboard or normalized in {selector.casefold(), name.casefold()}:
        match = _exact_match(match, normalized)
    if match["confidence"] != "strong":
        return None
    required = [str(value) for value in definition.get("required_inputs", ())]
    input_schema = {
        str(key): dict(value)
        for key, value in definition.get("input_schema", {}).items()
        if isinstance(value, Mapping)
    }
    return {
        "kind": "composite", "selector": selector, "composite": name,
        "domain": selected_domain, "description": str(definition.get("description", "")),
        "effect": "read", "executable": True, "plan_executable": True,
        "natural_language_auto_execute": False, "input_schema": input_schema,
        "required_inputs": required, "match": match,
        "next": {"ready_without_input": not required,
                 "argv": ["gravity", "plan", "run", "--input", "<plan.json>"]},
    }


def _selection(
    query: str, domain: str | None, definition: Mapping[str, Any]
) -> tuple[str, str, tuple[str, ...], bool] | None:
    from .agent_dashboard import dashboard_snapshot_query

    name, selected_domain = str(definition["name"]), str(definition["domain"])
    accepted = tuple(
        str(value) for value in definition.get("accepted_domains", (selected_domain,))
    )
    if domain is not None and domain not in accepted:
        return None
    intent = tuple(str(value) for value in definition.get("intent_terms", ()))
    dashboard = name == "dashboard_snapshot" and dashboard_snapshot_query(query)
    if intent and not dashboard and not any(term in query.casefold() for term in intent):
        return None
    return name, selected_domain, accepted, dashboard


def _exact_match(match: Mapping[str, Any], normalized: str) -> dict[str, Any]:
    return {
        **dict(match), "confidence": "strong", "coverage": 1.0,
        "matched_terms": [normalized], "missing_terms": [], "exact_selector": True,
    }


__all__ = ["composite_card"]
