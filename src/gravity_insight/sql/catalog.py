"""Safe discovery surface for configured SQL products."""

from __future__ import annotations

from typing import Any, Mapping

from gravity_insight.agents.query_match import query_match
from gravity_insight.sql.time_window import EvidenceFormatError
from gravity_insight.workspace import Workspace, WorkspaceError, load_workspace, require_products


def product_definition(product: str, workspace: Workspace | None = None) -> Mapping[str, Any]:
    """Read a registered definition with the SQL boundary's existing error identity."""

    selected = load_workspace() if workspace is None else workspace
    try:
        return selected.product(product)
    except WorkspaceError as exc:
        raise EvidenceFormatError(str(exc)) from exc


def product_apps(product: str, workspace: Workspace | None = None) -> tuple[int, ...]:
    selected = load_workspace() if workspace is None else workspace
    definition = product_definition(product, selected)
    return tuple(selected.resolve_app(value) for value in definition["apps"])


def describe_products(workspace: Workspace | None = None) -> list[dict[str, Any]]:
    """Return callable product contracts without exposing implementation SQL."""

    selected = load_workspace() if workspace is None else workspace
    return [
        _describe_product(name, selected)
        for name in require_products(selected)
    ]


def _describe_product(name: str, workspace: Workspace) -> dict[str, Any]:
    definition = product_definition(name, workspace)
    return {
        "name": name,
        "kind": definition["kind"],
        "datasource": definition["datasource"],
        "app_ids": list(product_apps(name, workspace)),
        "privacy": definition["privacy"],
        "output_fields": list(definition["output_fields"]),
        "output_semantics": dict(definition.get("output_semantics", {})),
        "max_rows": int(definition.get("max_rows", 1000)),
        "measurement": str(definition.get("measurement", "workspace aggregate")),
        "forbidden_claims": list(definition["forbidden_claims"]),
    }


def search_product_cards(
    query: str, *, workspace: Workspace, limit: int
) -> tuple[list[dict[str, Any]], list[str]]:
    """Return strongly matching safe product cards without exposing SQL."""

    if not workspace.products:
        return [], []
    try:
        products = describe_products(workspace)
    except (OSError, ValueError, KeyError, TypeError):
        return [], [
            "The workspace SQL product catalog is invalid; run `gravity sql --dry-run`."
        ]
    cards = [_product_card(query, product) for product in products]
    strong = [card for card in cards if card["match"]["confidence"] == "strong"]
    return sorted(
        strong,
        key=lambda card: (-float(card["match"]["coverage"]), str(card["product"])),
    )[:limit], []


def _product_card(query: str, product: dict[str, Any]) -> dict[str, Any]:
    name = str(product["name"])
    match = query_match(
        query,
        name.replace("-", " "),
        product.get("measurement"),
        product.get("datasource"),
        *(product.get("output_fields") or ()),
        *(product.get("output_semantics") or {}).values(),
    )
    return {
        "kind": "sql_product",
        "selector": f"sql:{name}",
        "product": name,
        "datasource": product.get("datasource"),
        "app_ids": list(product.get("app_ids", [])),
        "privacy": product.get("privacy"),
        "measurement": product.get("measurement"),
        "output_fields": list(product.get("output_fields", [])),
        "output_semantics": dict(product.get("output_semantics", {})),
        "max_rows": product.get("max_rows"),
        "forbidden_claims": list(product.get("forbidden_claims", [])),
        "match": match,
        "next": {
            "ready_without_input": False,
            "argv": [
                "gravity",
                "sql",
                "query",
                name,
                "--start",
                "<inclusive-iso>",
                "--end",
                "<exclusive-iso>",
            ],
        },
    }


__all__ = ["describe_products", "search_product_cards"]
