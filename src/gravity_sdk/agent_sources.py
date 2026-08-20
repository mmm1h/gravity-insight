"""Bounded offline candidate sources for the Agent discovery protocol."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .agent_pagination import compact_pagination

from .agent_capabilities import (
    agent_query_match,
    operation_query_match,
)
from .agent_handoff import apply_workspace_prefix
from .errors import InputValidationError
from .find import (
    RecipeFindBackend,
    _metadata_card,
    metadata_capability_cards,
)
from .sql.catalog import search_product_cards
from .workspace import load_workspace
from .actionable_error_values import actual_value


_FIELD_KEYS = (
    "type",
    "item_type", "item_enum",
    "required",
    "nullable",
    "default",
    "enum",
    "minimum",
    "maximum",
    "min_items",
    "max_items",
)


@dataclass(frozen=True)
class OperationDiscovery:
    matches: list[Mapping[str, Any]]
    weak: list[Mapping[str, Any]]


def discover_operation_cards(
    client: Any,
    query: str,
    *,
    domain: str | None,
    platform: str | None,
    limit: int = 20,
    continuation: str | None = None,
    inventory: tuple[Mapping[str, Any], ...] | None = None,
) -> OperationDiscovery:
    matches: list[Mapping[str, Any]] = []
    weak: list[Mapping[str, Any]] = []
    del limit, continuation
    if inventory is not None:
        selected_inventory = inventory
    elif hasattr(client, "operations"):
        selected_inventory = client.operations(
            domain=domain,
            platform=platform,
            stability="stable",
        )
    else:
        search = client.search_operations(
            query,
            domain=domain,
            platform=platform,
            stability="stable",
            limit=20,
        )
        if search.get("continuation_token"):
            raise InputValidationError(
                f"actual value: {actual_value(type(client).__name__)}; " + ("client must expose the complete offline operation inventory"),
                field="client",
            )
        selected_inventory = search.get("operations", [])
    eligible = _eligible_operations(
        selected_inventory,
        require_stable=inventory is not None,
        domain=domain,
        platform=platform,
    )
    exact = _exact_operation(eligible, query)
    if exact is not None:
        return OperationDiscovery(
            matches=[{
                **dict(exact),
                "agent_match": operation_query_match(query, exact),
            }],
            weak=[],
        )
    for item in eligible:
        match = operation_query_match(query, item)
        selected = {**dict(item), "agent_match": match}
        if match["confidence"] == "strong":
            matches.append(selected)
        elif match["confidence"] == "partial":
            weak.append(selected)
    matches.sort(
        key=lambda item: (
            -float(item["agent_match"]["coverage"]),
            -int(item["agent_match"].get("score", 0)),
            str(item["operation_id"]).count("."),
            str(item["operation_id"]),
        )
    )
    return OperationDiscovery(matches=matches, weak=weak)


def _eligible_operations(
    inventory: Any,
    *,
    require_stable: bool,
    domain: str | None,
    platform: str | None,
) -> list[Mapping[str, Any]]:
    return [
        item
        for item in inventory
        if isinstance(item, Mapping)
        and item.get("operation_id")
        and (not require_stable or item.get("stability") == "stable")
        and (domain is None or item.get("domain") == domain)
        and (platform is None or item.get("platform") == platform)
    ]


def _exact_operation(
    inventory: list[Mapping[str, Any]], query: str
) -> Mapping[str, Any] | None:
    selected = query.strip().casefold()
    return next(
        (
            item
            for item in inventory
            if str(item.get("operation_id", "")).casefold() == selected
        ),
        None,
    )


def describe_operation_cards(
    client: Any, matches: list[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    return [
        _operation_card(item, client.describe(str(item["operation_id"])))
        for item in matches
    ]


def catalog_cards(
    query: str,
    limit: int,
    *,
    workspace: Any | None,
    sources: Any | None = None,
) -> tuple[list[dict[str, Any]], int, list[str], str]:
    warnings: list[str] = list(sources.warnings) if sources is not None else []
    if sources is not None:
        selected_workspace = sources.workspace
    else:
        from .workspace_semantic_context import SemanticContextError

        try:
            selected_workspace = load_workspace() if workspace is None else workspace
        except SemanticContextError:
            raise
        except (OSError, ValueError):
            selected_workspace = None
            warnings.append(
                "The workspace catalog could not be loaded; recipe and SQL product "
                "discovery are unavailable."
            )
    cards: list[dict[str, Any]] = []
    if sources is not None:
        cards.extend(snapshot_recipe_cards(query, sources.recipe_inventory))
        cards.extend(snapshot_product_cards(query, sources.product_inventory))
    elif selected_workspace is not None:
        recipe_limit = max(1, len(selected_workspace.recipes))
        recipes, recipe_warnings = _recipe_cards(
            query, recipe_limit, workspace=selected_workspace
        )
        products, product_warnings = search_product_cards(
            query,
            workspace=selected_workspace,
            limit=max(1, len(selected_workspace.products)),
        )
        cards.extend((*recipes, *products))
        warnings.extend((*recipe_warnings, *product_warnings))
    if sources is None:
        metadata, metadata_warnings = metadata_capability_cards(query, limit=None)
    else:
        metadata = [
            _metadata_card(query, item) for item in sources.metadata_inventory
        ]
        metadata = [
            card for card in metadata if card["match"]["confidence"] == "strong"
        ]
        metadata_warnings = []
    cards.extend(metadata)
    warnings.extend(metadata_warnings)
    workspace_path = (
        getattr(selected_workspace, "path", None)
        if selected_workspace is not None
        else None
    )
    cards = [apply_workspace_prefix(card, workspace_path) for card in cards]
    priority = {"recipe": 0, "sql_product": 1, "metadata": 2}
    ordered = sorted(
        cards,
        key=lambda card: (
            priority.get(str(card.get("kind")), 9),
            -float(card.get("match", {}).get("coverage", 0)),
            str(card.get("selector", "")),
        ),
    )
    fingerprint = (
        sources.workspace_fingerprint
        if sources is not None
        else workspace_catalog_fingerprint(selected_workspace)
    )
    return ordered, len(ordered), warnings, fingerprint


def snapshot_recipe_cards(
    query: str, inventory: tuple[Mapping[str, Any], ...]
) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    for recipe in inventory:
        name = str(recipe["name"])
        match = agent_query_match(
            query,
            name,
            recipe.get("operation_id"),
            recipe.get("description"),
        )
        if match["confidence"] != "strong":
            continue
        argv = ["gravity", "run", f"@{name}"]
        for parameter in recipe.get("required_parameters", []):
            argv.extend(["--param", f"{parameter}=<{parameter}>"])
        cards.append({
            "kind": "recipe",
            "selector": f"@{name}",
            "recipe": name,
            "operation_id": recipe.get("operation_id"),
            "description": recipe.get("description", ""),
            "description_origin": "caller_workspace",
            "match": match,
            "required_parameters": list(recipe.get("required_parameters", [])),
            "parameter_bindings": dict(recipe.get("parameter_bindings", {})),
            "output_fields": list(recipe.get("output_fields", [])),
            "next": {
                "ready_without_input": not recipe.get("required_parameters"),
                "argv": argv,
            },
        })
    return cards


def snapshot_product_cards(
    query: str, inventory: tuple[Mapping[str, Any], ...]
) -> list[dict[str, Any]]:
    cards = [_snapshot_product_card(query, product) for product in inventory]
    return sorted(
        (card for card in cards if card["match"]["confidence"] == "strong"),
        key=lambda card: (-float(card["match"]["coverage"]), str(card["product"])),
    )


def _snapshot_product_card(
    query: str, product: Mapping[str, Any]
) -> dict[str, Any]:
    name = str(product["name"])
    match = agent_query_match(
        query,
        name.replace("-", " "),
        product.get("measurement"),
        product.get("datasource"),
        *(product.get("output_fields") or ()),
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
        "max_rows": product.get("max_rows"),
        "forbidden_claims": list(product.get("forbidden_claims", [])),
        "match": match,
        "next": {
            "ready_without_input": False,
            "argv": [
                "gravity", "sql", "query", name, "--start", "<inclusive-iso>",
                "--end", "<exclusive-iso>",
            ],
        },
    }


def workspace_catalog_fingerprint(workspace: Any | None) -> str:
    """Identify recipe/product execution contracts without exposing their values."""

    recipes: list[dict[str, str]] = []
    products: list[dict[str, str]] = []
    if workspace is not None:
        for name in sorted(workspace.recipes):
            recipe = workspace.recipes[name]
            contract = {
                "operation": recipe.operation,
                "description": recipe.description,
                "bindings": {
                    "app_ref": recipe.bindings.app_ref,
                    "app_input": recipe.bindings.app_input,
                    "report_ref": recipe.bindings.report_ref,
                    "report_input": recipe.bindings.report_input,
                    "resolved_app": (
                        workspace.resolve_app(recipe.bindings.app_ref)
                        if recipe.bindings.app_ref is not None
                        else None
                    ),
                },
                "parameters": dict(recipe.parameters),
                "required_parameters": list(recipe.required_parameters),
                "input": dict(recipe.input),
                "output_fields": list(recipe.output_fields),
                "contract_fingerprint": recipe.contract_fingerprint,
            }
            recipes.append(
                {"selector": f"@{name}", "contract_sha256": _digest(contract)}
            )
        for name in sorted(workspace.products):
            definition = dict(workspace.products[name])
            datasource = workspace.datasources.get(str(definition.get("datasource")), {})
            contract = {
                "definition": definition,
                "datasource": dict(datasource),
                "resolved_apps": [
                    workspace.resolve_app(value)
                    for value in definition.get("apps", [])
                ],
            }
            products.append(
                {"selector": f"sql:{name}", "contract_sha256": _digest(contract)}
            )
    from .workspace_semantic_context import semantic_fingerprint_fields
    return _digest({"recipes": recipes, "products": products,
                    **semantic_fingerprint_fields(workspace)})


def candidates_fingerprint(
    candidates: list[tuple[str, Mapping[str, Any]]],
) -> str:
    """Bind continuation to the complete ordered cross-source candidate set."""

    identities: list[dict[str, Any]] = []
    for source, item in candidates:
        kind = "operation" if source == "operation" else str(item.get("kind"))
        selector = str(
            item.get("operation_id") if source == "operation" else item.get("selector")
        )
        identity: dict[str, Any] = {"source": kind, "selector": selector}
        if source == "operation":
            probe = item.get("probe")
            identity["contract"] = (
                probe.get("contract_fingerprint")
                if isinstance(probe, Mapping)
                else item.get("contract_version")
            )
        elif kind == "metadata":
            identity["contract"] = {
                key: item.get(key)
                for key in (
                    "metadata_kind",
                    "app_id",
                    "name",
                    "display_name",
                    "operation_id",
                )
            }
        elif kind == "composite":
            identity["contract"] = {
                "composite": item.get("composite"),
                "required_inputs": list(item.get("required_inputs", [])),
                "input_schema": item.get("input_schema", {}),
            }
        elif kind == "analysis_query_spec":
            identity["contract"] = {
                "compiler": item.get("compiler"),
                "kinds": list(item.get("kinds", [])),
                "input_schema": item.get("input_schema", {}),
            }
        elif kind == "export":
            identity["contract"] = {
                "effect": item.get("effect"),
                "currently_callable": item.get("currently_callable"),
                "request_required_fields": list(
                    item.get("request_required_fields", [])
                ),
                "columns": item.get("columns", {}),
            }
        identities.append(identity)
    return _digest(identities)


def _digest(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _operation_card(
    search_item: Mapping[str, Any], description: Mapping[str, Any]
) -> dict[str, Any]:
    from .pagination_completeness import collection_claims

    operation_id = str(search_item["operation_id"])
    input_schema = description.get("input_schema", {})
    if not isinstance(input_schema, Mapping):
        input_schema = {}
    fields = {
        str(name): _compact_field(specification)
        for name, specification in input_schema.items()
    }
    required = [
        name
        for name, specification in fields.items()
        if specification.get("required") is True and "default" not in specification
    ]
    parents = description.get("required_parent", [])
    parent_operations = (
        [
            str(item["operation_id"])
            for item in parents
            if isinstance(item, Mapping) and item.get("operation_id")
        ]
        if isinstance(parents, list)
        else []
    )
    argv = ["gravity", "run", operation_id]
    if required:
        argv.extend(["--input", "<json-object-or-file>"])
    pagination = compact_pagination(description.get("pagination"))
    allowed_claims, forbidden_claims = collection_claims(
        str(pagination["completeness"])
    )
    return {
        "kind": "operation",
        "selector": operation_id,
        "operation_id": operation_id,
        "description": description.get(
            "description", search_item.get("description", "")
        ),
        "description_origin": "sdk_contract",
        "domain": description.get("domain", search_item.get("domain")),
        "platform": description.get("platform", search_item.get("platform")),
        "stability": description.get("stability", search_item.get("stability")),
        "executable": bool(
            description.get("executable", search_item.get("executable", True))
        ),
        "effect": description.get("effect", "read"),
        "input_schema": fields,
        "required_inputs": required,
        "required_parent_operations": parent_operations,
        "pagination": pagination,
        "allowed_claims": allowed_claims,
        "forbidden_claims": forbidden_claims,
        "match": dict(search_item.get("agent_match", {})),
        "next": {"ready_without_input": not required, "argv": argv},
    }


def _recipe_cards(
    query: str, limit: int, *, workspace: Any
) -> tuple[list[dict[str, Any]], list[str]]:
    try:
        matches = RecipeFindBackend(workspace).search(query, limit=limit)
    except (OSError, ValueError):
        return [], ["The workspace recipe catalog could not be loaded."]
    cards: list[dict[str, Any]] = []
    for match in matches:
        name = str(match["name"])
        recipe = workspace.recipe(name)
        relevance = agent_query_match(
            query,
            name,
            recipe.operation,
            recipe.description,
            score=int(match.get("score", 0)),
        )
        if relevance["confidence"] != "strong":
            continue
        argv = ["gravity", "run", f"@{name}"]
        for parameter in recipe.required_parameters:
            argv.extend(["--param", f"{parameter}=<{parameter}>"])
        cards.append({
            "kind": "recipe",
            "selector": f"@{name}",
            "recipe": name,
            "operation_id": recipe.operation,
            "description": recipe.description,
            "description_origin": "caller_workspace",
            "match": relevance,
            "required_parameters": list(recipe.required_parameters),
            "parameter_bindings": dict(recipe.parameters),
            "output_fields": list(recipe.output_fields),
            "next": {
                "ready_without_input": not recipe.required_parameters,
                "argv": argv,
            },
        })
    return cards, []


def _compact_field(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    return {key: value[key] for key in _FIELD_KEYS if key in value}


__all__ = [
    "OperationDiscovery",
    "catalog_cards",
    "candidates_fingerprint",
    "describe_operation_cards",
    "discover_operation_cards",
    "workspace_catalog_fingerprint",
]
