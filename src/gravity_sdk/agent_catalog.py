"""Progressive, value-free discovery derived from Agent cards and manifests."""

from __future__ import annotations

import copy
from collections import Counter
from collections.abc import Mapping
from typing import Any

from .agent_capabilities import composite_capability_cards, composite_capability_inventory
from .agent_sources import describe_operation_cards
from .errors import InputValidationError


SCHEMA_VERSION = "gravity.agent-catalog.v1"
DEFAULT_LIMIT = 20
MAX_LIMIT = 50


def add_agent_catalog_command(commands: Any, limit_parser: Any) -> None:
    """Register an additive, read-only progressive discovery command family."""

    command = commands.add_parser(
        "agent-catalog",
        help="Progressively list and describe Agent capabilities without execution.",
    )
    command.set_defaults(network_required=False)
    actions = command.add_subparsers(dest="agent_catalog_command", required=True)
    actions.add_parser("categories", help="List manifest-derived capability domains.")
    category = actions.add_parser("category", help="List short selectors in one domain.")
    category.add_argument("name")
    category.add_argument("--limit", type=limit_parser, default=DEFAULT_LIMIT)
    category.add_argument("--offset", type=_offset, default=0)
    describe = actions.add_parser("describe", help="Describe one composite or operation selector.")
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
    composites = [
        {
            "source": "composite",
            "selector": f"composite:{item['name']}",
            "domain": str(item["domain"]),
            "name": str(item["name"]),
            "description": str(item.get("description", "")),
            "stability": "stable",
            "executable": True,
        }
        for item in composite_capability_inventory()
    ]
    operations = [
        {
            "source": "operation",
            "selector": str(item["operation_id"]),
            "domain": str(item.get("domain", "uncategorized")),
            "name": str(item["operation_id"]),
            "description": str(item.get("description", "")),
            "stability": str(item.get("stability", "unknown")),
            "executable": bool(item.get("executable", False)),
            "operation": dict(item),
        }
        for item in client.operations(stability=None)
        if isinstance(item, Mapping) and item.get("operation_id")
    ]
    return tuple(sorted([*composites, *operations], key=lambda item: item["selector"]))


def _categories(inventory: tuple[dict[str, Any], ...]) -> list[dict[str, Any]]:
    counts: dict[str, Counter[str]] = {}
    for item in inventory:
        bucket = counts.setdefault(item["domain"], Counter())
        bucket["total"] += 1
        bucket[f"{item['source']}s"] += 1
        bucket[f"{item['stability']}_operations"] += int(item["source"] == "operation")
    return [
        {
            "name": name,
            "total": counter["total"],
            "composites": counter["composites"],
            "operations": counter["operations"],
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
    if selected["source"] == "composite":
        cards = composite_capability_cards(
            selector, domain=None, platform=None, inventory=composite_capability_inventory()
        )
        if len(cards) != 1:
            raise RuntimeError("composite inventory cannot reproduce its Agent card")
        capability = copy.deepcopy(cards[0])
    else:
        capability = describe_operation_cards(client, [selected["operation"]])[0]
    return _envelope(
        "describe_capability",
        selector=selector,
        capability=capability,
        next_action="Use the existing card contract; this command never executes it.",
    )


def _summary(item: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: item[key]
        for key in ("selector", "source", "name", "description", "stability", "executable")
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
