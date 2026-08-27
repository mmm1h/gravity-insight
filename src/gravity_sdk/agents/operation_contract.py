"""Contract-derived overlays for Agent-owned operation cards."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .client import DeferredAgentClient
from .sources import describe_operation_cards


def operation_contract_overlay(
    client: Any, operation: Mapping[str, Any], extra: Any = None
) -> dict[str, Any]:
    """Project one operation contract and preserve owner-only field metadata."""

    contract = describe_operation_cards(client, [operation])[0]
    fields = dict(contract.get("input_schema") or {})
    if isinstance(extra, Mapping):
        for name, specification in extra.items():
            current = fields.get(str(name))
            fields[str(name)] = {
                **(current if isinstance(current, Mapping) else {}),
                **dict(specification),
            }
    return {
        "input_schema": fields,
        "required_inputs": list(contract.get("required_inputs") or ()),
        "required_parent_operations": list(
            contract.get("required_parent_operations") or ()
        ),
        "pagination": dict(contract.get("pagination") or {"supported": False}),
        "stability": contract.get("stability"),
        "platform": contract.get("platform"),
        "effect": contract.get("effect", "read"),
        "executable": bool(contract.get("executable", True)),
    }


def materialize_operation_owner_card(
    client: Any, card: Mapping[str, Any]
) -> dict[str, Any]:
    """Hydrate selected operation owners without changing candidate precedence."""

    selected = dict(card)
    template = selected.get("input_template")
    fields = selected.get("input_schema")
    needs_overlay = (
        selected.get("kind") == "operation"
        and selected.get("operation_id") == selected.get("selector")
        and isinstance(template, Mapping)
        and (
            not isinstance(fields, Mapping)
            or not set(template).issubset(fields)
        )
    )
    if not needs_overlay:
        return selected

    contract_describer = (
        client.loaded_attribute("describe")
        if isinstance(client, DeferredAgentClient)
        else getattr(client, "describe", None)
    )
    if callable(contract_describer):
        selected.update(
            operation_contract_overlay(client, selected, fields)
        )
    return selected


__all__ = ["materialize_operation_owner_card", "operation_contract_overlay"]
