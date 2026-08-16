"""Progressive discovery derived from Agent cards, manifests, and gap owners."""

from __future__ import annotations

import copy
from collections import Counter
from collections.abc import Mapping
from typing import Any

from .agent_capabilities import composite_capability_inventory
from .agent_catalog_parity import validate_catalog_parity
from .agent_product_inventory import canonical_capability_cards
from .agent_sources import describe_operation_cards
from .agent_unavailable import registered_unavailable_gaps
from .errors import InputValidationError


SCHEMA_VERSION = "gravity.agent-catalog.v1"
DEFAULT_LIMIT = 20
MAX_LIMIT = 50


def add_agent_catalog_command(
    commands: Any, limit_parser: Any, client_factory: Any
) -> None:
    """Register an additive, read-only progressive discovery command family."""

    command = commands.add_parser(
        "agent-catalog",
        help="Progressively list and describe Agent capabilities without execution.",
    )
    command.set_defaults(
        network_required=False,
        _gravity_handler=lambda args, _object_input: run_agent_catalog_command(
            args, client_factory(args)
        ),
    )
    actions = command.add_subparsers(dest="agent_catalog_command", required=True)
    actions.add_parser("categories", help="List derived product, operation, and gap domains.")
    category = actions.add_parser("category", help="List short selectors in one domain.")
    category.add_argument("name")
    category.add_argument("--limit", type=limit_parser, default=DEFAULT_LIMIT)
    category.add_argument("--offset", type=_offset, default=0)
    describe = actions.add_parser(
        "describe", help="Describe one product, raw operation, or unavailable gap."
    )
    describe.add_argument("selector")


def run_agent_catalog_command(args: Any, client: Any) -> dict[str, Any]:
    """Handle one progressive discovery step using only local runtime metadata."""

    action = str(args.agent_catalog_command)
    inventory = _inventory(client)
    if action == "categories":
        return _envelope("list_categories", categories=_categories(inventory))
    if action == "category":
        return _category_response(inventory, str(args.name), args.limit, args.offset)
    if action == "describe":
        return _describe_response(inventory, str(args.selector), client)
    raise InputValidationError("unknown agent catalog action", field="agent_catalog_command")


def _inventory(client: Any) -> tuple[dict[str, Any], ...]:
    cards = canonical_capability_cards(client)
    gaps = registered_unavailable_gaps()
    legacy_composites = {
        f"composite:{item['name']}" for item in composite_capability_inventory()
    }
    operation_rows = tuple(
        item
        for item in client.operations(stability=None)
        if isinstance(item, Mapping) and item.get("operation_id")
    )
    operations_by_id = {
        str(item["operation_id"]): item for item in operation_rows
    }
    products = [
        _product_entry(
            card,
            source=(
                "composite" if card["selector"] in legacy_composites else "product"
            ),
            operation=operations_by_id.get(str(card["selector"])),
        )
        for card in cards
    ]
    product_selectors = {str(card["selector"]) for card in cards}
    operations = [
        {
            "source": "operation",
            "identity_kind": "raw_operation",
            "selector": str(item["operation_id"]),
            "domain": str(item.get("domain", "uncategorized")),
            "name": str(item["operation_id"]),
            "description": str(item.get("description", "")),
            "stability": str(item.get("stability", "unknown")),
            "executable": bool(item.get("executable", False)),
            "catalog_status": (
                "raw_operation_executable"
                if item.get("executable")
                else "raw_operation_unavailable"
            ),
            "product_equivalent": False,
            "operation_contract": True,
            "operation": dict(item),
        }
        for item in operation_rows
        if str(item["operation_id"]) not in product_selectors
    ]
    unavailable = [_gap_entry(item) for item in gaps]
    inventory = tuple(sorted(
        [*products, *operations, *unavailable], key=_catalog_sort_key
    ))
    validate_catalog_parity(
        inventory,
        product_cards=cards,
        operations=operation_rows,
        gaps=gaps,
    )
    return inventory


def _categories(inventory: tuple[dict[str, Any], ...]) -> list[dict[str, Any]]:
    counts: dict[str, Counter[str]] = {}
    for item in inventory:
        bucket = counts.setdefault(item["domain"], Counter())
        bucket["total"] += 1
        bucket["composites"] += int(item["source"] == "composite")
        bucket["products"] += int(item["identity_kind"] == "product")
        bucket["gaps"] += int(item["identity_kind"] == "capability_gap")
        bucket["raw_operations"] += int(item["identity_kind"] == "raw_operation")
        bucket["operations"] += int(item.get("operation_contract") is True)
        bucket[f"{item['stability']}_operations"] += int(
            item.get("operation_contract") is True
        )
    return [
        {
            "name": name,
            "total": counter["total"],
            "composites": counter["composites"],
            "products": counter["products"],
            "operations": counter["operations"],
            "raw_operations": counter["raw_operations"],
            "gaps": counter["gaps"],
            "stable_operations": counter["stable_operations"],
            "next": {"argv": ["gravity", "agent-catalog", "category", name]},
        }
        for name, counter in sorted(counts.items())
    ]


def _category_response(
    inventory: tuple[dict[str, Any], ...], name: str, limit: int, offset: int
) -> dict[str, Any]:
    entries = [item for item in inventory if item["domain"] == name]
    if not entries:
        raise InputValidationError("agent catalog category is not registered", field="name")
    if not 1 <= limit <= MAX_LIMIT:
        raise InputValidationError(
            f"agent catalog limit must be between 1 and {MAX_LIMIT}", field="limit"
        )
    if offset >= len(entries):
        raise InputValidationError("agent catalog offset has no entries", field="offset")
    selected = entries[offset : offset + limit]
    next_offset = offset + len(selected)
    return _envelope(
        "get_category_capabilities",
        category=name,
        count=len(selected),
        total=len(entries),
        offset=offset,
        capabilities=[_summary(item) for item in selected],
        next_offset=next_offset if next_offset < len(entries) else None,
        next_action=(
            "Describe a selected selector before constructing inputs."
            if selected
            else "No capability is available in this category."
        ),
    )


def _describe_response(
    inventory: tuple[dict[str, Any], ...], selector: str, client: Any
) -> dict[str, Any]:
    selected = next((item for item in inventory if item["selector"] == selector), None)
    if selected is None:
        raise InputValidationError("agent catalog selector is not registered", field="selector")
    capability = _capability_for_item(selected, client)
    return _envelope(
        "describe_capability",
        selector=selector,
        capability=capability,
        next_action=(
            str(capability["next_action"])
            if selected["source"] == "gap"
            else "Use the existing card contract; this command never executes it."
        ),
    )


def _capability_for_item(item: Mapping[str, Any], client: Any) -> dict[str, Any]:
    if item["source"] == "operation":
        return describe_operation_cards(client, [item["operation"]])[0]
    return copy.deepcopy(item["card"])


def _summary(item: Mapping[str, Any]) -> dict[str, Any]:
    summary = {
        key: item[key]
        for key in (
            "selector", "source", "identity_kind", "name", "description",
            "stability", "executable", "catalog_status",
        )
    }
    if item["identity_kind"] == "raw_operation":
        summary["product_equivalent"] = False
    if item["identity_kind"] == "capability_gap":
        summary.update(
            gap_code=item["gap_code"],
            reason=item["reason"],
            next_action=item["next_action"],
        )
    return summary


def _catalog_sort_key(item: Mapping[str, Any]) -> tuple[int, str]:
    rank = {"product": 0, "raw_operation": 1, "capability_gap": 2}
    return rank[str(item["identity_kind"])], str(item["selector"])


def _product_entry(
    card: Mapping[str, Any], *, source: str, operation: Mapping[str, Any] | None
) -> dict[str, Any]:
    selector = str(card["selector"])
    executable = bool(card.get("executable", False))
    stability = str(operation.get("stability", "stable")) if operation else "stable"
    return {
        "source": source,
        "identity_kind": "product",
        "selector": selector,
        "domain": str(card.get("domain", "uncategorized")),
        "name": str(card.get("composite", selector)),
        "description": str(card.get("description", "")),
        "stability": stability,
        "executable": executable,
        "catalog_status": "executable_product" if executable else "unavailable_product",
        "product_equivalent": True,
        "operation_contract": operation is not None,
        "card": copy.deepcopy(dict(card)),
    }


def _gap_entry(gap: Mapping[str, Any]) -> dict[str, Any]:
    code = str(gap["code"])
    card = {
        **copy.deepcopy(dict(gap)),
        "selector": f"gap:{code}",
        "domain": "capability_gap",
        "executable": False,
        "plan_executable": False,
        "availability": "unavailable",
    }
    return {
        "source": "gap",
        "identity_kind": "capability_gap",
        "selector": card["selector"],
        "domain": card["domain"],
        "name": code,
        "description": str(card["reason"]),
        "stability": "unavailable",
        "executable": False,
        "catalog_status": "registered_unavailable",
        "gap_code": code,
        "reason": str(card["reason"]),
        "next_action": str(card["next_action"]),
        "card": card,
    }


def _envelope(mode: str, **payload: Any) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "ok": True,
        "status": "success",
        "offline": True,
        "network_called": False,
        "mode": mode,
        **payload,
    }


def _offset(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise InputValidationError("agent catalog offset must be a non-negative integer", field="offset") from exc
    if parsed < 0:
        raise InputValidationError("agent catalog offset must be a non-negative integer", field="offset")
    return parsed


__all__ = ["SCHEMA_VERSION", "add_agent_catalog_command", "run_agent_catalog_command"]
