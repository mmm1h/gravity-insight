"""Fail-closed Agent consumption of caller-owned workspace semantics."""

from __future__ import annotations

import copy
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .workspace_semantic_context import (
    SCHEMA_VERSION,
    DerivedMetric,
    SemanticContext,
    SemanticContextError,
    SemanticExclusion,
    SemanticTarget,
    SemanticTerm,
    VerifiedQuery,
    compiled_operation,
    normalized_phrase,
    phrase_matches,
)
from .agent_semantic_derived import (
    derived_matches,
    exclusion_gap,
    multiple_gap,
    public_matches as public_derived_matches,
    resolve_derived,
    unbound_gap,
)


@dataclass(frozen=True)
class SemanticResolution:
    cards: list[dict[str, Any]]
    gaps: list[dict[str, Any]]
    public_context: dict[str, Any] | None
    block_fallback: bool


@dataclass(frozen=True)
class _SemanticMatches:
    terms: tuple[tuple[SemanticTerm, tuple[str, ...]], ...]
    verified: tuple[VerifiedQuery, ...]
    exclusions: tuple[tuple[SemanticExclusion, tuple[str, ...]], ...]
    derived: tuple[tuple[DerivedMetric, tuple[str, ...]], ...]


def load_agent_workspace(workspace: Any | None, sources: Any | None) -> Any | None:
    """Load optional semantics without changing legacy invalid-workspace fallback."""

    if sources is not None:
        return sources.workspace
    if workspace is not None:
        return workspace
    from .agent_sources import load_workspace

    try:
        return load_workspace()
    except SemanticContextError:
        raise
    except (OSError, ValueError):
        return None


def resolve_semantic_context(
    query: str,
    workspace: Any | None,
    cards: Sequence[Mapping[str, Any]],
    client: Any | None,
    domain: str | None,
    platform: str | None,
    sources: Any | None,
) -> SemanticResolution:
    """Apply literal caller evidence without replacing centralized arbitration."""

    context = getattr(workspace, "semantic_context", None)
    if not isinstance(context, SemanticContext):
        if gap := unbound_gap(query, cards):
            return SemanticResolution([], [gap], None, True)
        return SemanticResolution([dict(card) for card in cards], [], None, False)
    _validate_composite_targets(context, sources)
    metadata = _metadata_targets(context, workspace, sources)
    matches = _semantic_matches(context, query)
    public = _public_context(
        context, matches.terms, matches.verified, matches.exclusions, matches.derived
    )
    if _existing_multiple_intents(query, sources):
        return SemanticResolution([dict(card) for card in cards], [], public, False)
    return _resolve_matches(
        query, matches, metadata, workspace, cards, client, domain, platform, sources, public
    )


def is_semantic_card(card: Mapping[str, Any]) -> bool:
    value = card.get("semantic_context")
    return isinstance(value, Mapping) and value.get("schema_version") == SCHEMA_VERSION


def _semantic_matches(context: SemanticContext, query: str) -> _SemanticMatches:
    terms = tuple(
        (item, matches)
        for item in context.terms
        if (matches := tuple(phrase for phrase in item.phrases if phrase_matches(query, phrase)))
    )
    verified = tuple(
        item
        for item in context.verified_queries
        if normalized_phrase(item.question) == normalized_phrase(query)
    )
    exclusions = tuple(
        (item, matches)
        for item in context.exclusions
        if (matches := tuple(phrase for phrase in item.when if phrase_matches(query, phrase)))
    )
    derived = derived_matches(context, query)
    return _SemanticMatches(terms, verified, exclusions, derived)


def _existing_multiple_intents(query: str, sources: Any | None) -> bool:
    from .agent_intent_routing import multiple_product_intents

    inventory = sources.composite_inventory if sources is not None else None
    return bool(multiple_product_intents(query, inventory=inventory))


def _resolve_matches(
    query: str,
    matches: _SemanticMatches,
    metadata: Mapping[str, Mapping[str, Any]],
    workspace: Any,
    cards: Sequence[Mapping[str, Any]],
    client: Any | None,
    domain: str | None,
    platform: str | None,
    sources: Any | None,
    public: dict[str, Any],
) -> SemanticResolution:
    direct = list(
        dict.fromkeys(str(card["selector"]) for card in cards if card.get("selector"))
    )
    blocked = _exclusion_resolution(
        query, matches.exclusions, direct, workspace, metadata, public
    )
    if blocked is not None:
        return blocked
    derived = resolve_derived(
        query, matches.derived,
        competing=bool(matches.terms or matches.verified), direct=direct,
    )
    if derived is not None:
        derived_cards, derived_gaps, block = derived
        return SemanticResolution(derived_cards, derived_gaps, public, block)
    if matches.verified:
        declaration = matches.verified[0]
        return _single_target_resolution(
            query,
            (
                SemanticTarget("operation", declaration.operation),
                declaration,
                (declaration.question,),
            ),
            metadata,
            workspace,
            (),
            client,
            domain,
            platform,
            sources,
            public,
        )
    active = [(item.target, item, phrases) for item, phrases in matches.terms]
    if not active:
        if gap := unbound_gap(query, cards):
            return SemanticResolution([], [gap], public, True)
        return SemanticResolution([dict(card) for card in cards], [], public, False)
    identities = list(dict.fromkeys(item[0].identity for item in active))
    if len(identities) > 1:
        selectors = [_target_selector(item[0], workspace, metadata) for item in active]
        return SemanticResolution([], [multiple_gap(query, selectors)], public, True)
    return _single_target_resolution(
        query, active[0], metadata, workspace, direct, client, domain, platform, sources, public
    )


def _exclusion_resolution(
    query: str,
    exclusions: Sequence[tuple[SemanticExclusion, tuple[str, ...]]],
    direct: Sequence[str],
    workspace: Any,
    metadata: Mapping[str, Mapping[str, Any]],
    public: dict[str, Any],
) -> SemanticResolution | None:
    if not exclusions:
        return None
    selectors = {
        _target_selector(item.target, workspace, metadata) for item, _phrases in exclusions
    }
    blocked = [selector for selector in direct if selector in selectors]
    return SemanticResolution(
        [], [exclusion_gap(query, blocked or sorted(selectors), exclusions)], public, True
    )


def _single_target_resolution(
    query: str,
    active: tuple[SemanticTarget, SemanticTerm | VerifiedQuery, tuple[str, ...]],
    metadata: Mapping[str, Mapping[str, Any]],
    workspace: Any,
    direct: Sequence[str],
    client: Any | None,
    domain: str | None,
    platform: str | None,
    sources: Any | None,
    public: dict[str, Any],
) -> SemanticResolution:
    target, declaration, phrases = active
    card, rejection = _semantic_card(
        query, target, declaration, phrases,
        workspace=workspace, client=client, domain=domain, platform=platform,
        sources=sources, metadata=metadata,
    )
    if rejection is not None:
        return SemanticResolution([], [rejection], public, True)
    selector = str(card["selector"])
    conflicts = [item for item in direct if item != selector]
    if conflicts:
        return SemanticResolution([], [multiple_gap(query, [selector, *conflicts])], public, True)
    return SemanticResolution([card], [], public, True)


def _semantic_card(
    query: str,
    target: SemanticTarget,
    declaration: SemanticTerm | VerifiedQuery,
    phrases: tuple[str, ...],
    *,
    workspace: Any,
    client: Any | None,
    domain: str | None,
    platform: str | None,
    sources: Any | None,
    metadata: Mapping[str, Mapping[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    if target.kind == "product":
        card, rejection = _product_card(
            query,
            target.ref,
            workspace=workspace,
            domain=domain,
            platform=platform,
            sources=sources,
        )
        if rejection is not None:
            return {}, rejection
    elif target.kind == "operation":
        card = _operation_card(target.ref, query, client)
    else:
        row = metadata[target.identity]
        from .find import _metadata_card

        card = _metadata_card(target.ref, row)

    description = declaration.description or phrases[0]
    card.update(
        description=description,
        description_origin="caller_workspace",
        match={
            "confidence": "strong",
            "coverage": 1.0,
            "matched_terms": list(phrases),
            "missing_terms": [],
            "score": 0,
            "exact_selector": isinstance(declaration, VerifiedQuery),
        },
        semantic_context={
            "schema_version": SCHEMA_VERSION,
            "match_kind": (
                "verified_query" if isinstance(declaration, VerifiedQuery) else "term"
            ),
            "declaration": declaration.name,
            "matched_phrases": list(phrases),
            **(
                {
                    "verified_call": {
                        "kind": "run",
                        "request": {
                            "selector": declaration.operation,
                            "input": copy.deepcopy(dict(declaration.inputs)),
                            **({"all_pages": True} if declaration.all_pages else {}),
                        },
                    }
                }
                if isinstance(declaration, VerifiedQuery)
                else {}
            ),
        },
    )
    if isinstance(declaration, VerifiedQuery):
        encoded = json.dumps(
            declaration.inputs,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        card["required_inputs"] = []
        card["next"] = {
            "ready_without_input": True,
            "argv": ["gravity", "run", declaration.operation, "--input", encoded],
        }
    return card, None


def _product_card(
    query: str,
    selector: str,
    *,
    workspace: Any,
    domain: str | None,
    platform: str | None,
    sources: Any | None,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    if selector.startswith("composite:"):
        from .agent_capabilities import composite_capability_cards
        from .agent_intent_routing import multiple_product_intents

        canonical = selector.removeprefix("composite:").replace("_", " ")
        expanded = f"{query} {canonical}"
        inventory = sources.composite_inventory if sources is not None else None
        intents = multiple_product_intents(expanded, inventory=inventory)
        if len(intents) > 1:
            return {}, multiple_gap(query, list(intents))
        matches = composite_capability_cards(
            expanded,
            domain=domain,
            platform=platform,
            inventory=inventory,
        )
        selected = next(
            (dict(card) for card in matches if card.get("selector") == selector), None
        )
        if selected is None:
            return {}, {
                "kind": "capability_gap",
                "code": "SEMANTIC_CONTEXT_TARGET_REJECTED",
                "query": query,
                "reason": (
                    "the caller term matched, but the registered product rejected "
                    "the complete query under its existing intent constraints"
                ),
                "next_action": "Remove the conflicting intent or split the request; do not execute the semantic target.",
                "candidate_selectors": [selector],
                "weak_matches": [],
            }
        return selected, None
    if selector.startswith("@"):
        from .agent_batch_sources import snapshot_recipes
        from .agent_sources import snapshot_recipe_cards

        cards = snapshot_recipe_cards(selector, snapshot_recipes(workspace))
    else:
        from .agent_batch_sources import snapshot_products
        from .agent_sources import snapshot_product_cards

        warnings: list[str] = []
        cards = snapshot_product_cards(selector, snapshot_products(workspace, warnings))
    selected = next((dict(card) for card in cards if card.get("selector") == selector), None)
    if selected is None:
        raise SemanticContextError(
            f"semantic product selector could not be resolved: {selector}",
            field="semantic_context",
        )
    return selected, None


def _operation_card(
    operation_id: str, query: str, client: Any | None
) -> dict[str, Any]:
    from .agent_sources import _operation_card as build_card

    operation = compiled_operation(operation_id)
    if operation is None:
        raise SemanticContextError(
            f"semantic operation could not be resolved: {operation_id}",
            field="semantic_context",
        )
    summary = operation.operation_summary()
    search_item = {
        **summary,
        "agent_match": {
            "confidence": "strong",
            "coverage": 1.0,
            "matched_terms": [query],
            "missing_terms": [],
            "score": 0,
            "exact_selector": True,
        },
    }
    if client is not None:
        description = client.describe(operation_id)
    else:
        schema = operation.schema()
        description = {
            **summary,
            "effect": operation.effect,
            "input_schema": schema.get("input_fields", {}),
            "pagination": schema.get("pagination", {}),
        }
    return build_card(search_item, description)


def _metadata_targets(
    context: SemanticContext, workspace: Any, sources: Any | None
) -> dict[str, Mapping[str, Any]]:
    targets = {
        item.target.identity: item.target
        for item in (*context.terms, *context.exclusions)
        if item.target.kind not in {"product", "operation"}
    }
    if not targets:
        return {}
    rows = _metadata_inventory(sources)
    return {
        identity: _metadata_target_row(target, rows, workspace)
        for identity, target in targets.items()
    }


def _validate_composite_targets(context: SemanticContext, sources: Any | None) -> None:
    selectors = {
        item.target.ref
        for item in (*context.terms, *context.exclusions)
        if item.target.kind == "product" and item.target.ref.startswith("composite:")
    }
    if not selectors:
        return
    if sources is not None:
        inventory = sources.composite_inventory
    else:
        from .agent_capabilities import composite_capability_inventory

        inventory = composite_capability_inventory()
    registered = {f"composite:{item.get('name')}" for item in inventory}
    missing = sorted(selectors - registered)
    if missing:
        raise SemanticContextError(
            f"semantic context references unknown product selectors: {', '.join(missing)}",
            field="semantic_context",
        )


def _metadata_inventory(sources: Any | None) -> tuple[Mapping[str, Any], ...]:
    if sources is not None:
        if not bool(getattr(sources, "metadata_catalog_available", True)):
            raise SemanticContextError(
                "semantic metadata references require a synchronized local catalog",
                field="semantic_context",
            )
        return tuple(sources.metadata_inventory)
    from .find_metadata import search_metadata

    try:
        result = search_metadata("", limit=None, offset=0)
    except (OSError, ValueError) as exc:
        raise SemanticContextError(
            "semantic metadata references require a synchronized local catalog",
            field="semantic_context",
        ) from exc
    return tuple(item for item in result.get("results", []) if isinstance(item, Mapping))


def _metadata_target_row(
    target: SemanticTarget, rows: Sequence[Mapping[str, Any]], workspace: Any
) -> Mapping[str, Any]:
    app_id = str(workspace.resolve_app(target.app)) if target.app is not None else None
    matches = [
        row
        for row in rows
        if str(row.get("kind")) == target.kind
        and str(row.get("name")) == target.ref
        and (app_id is None or str(row.get("app_id")) == app_id)
    ]
    if len(matches) != 1:
        raise SemanticContextError(
            f"semantic target {target.contract()!r} resolved to {len(matches)} registered objects",
            field="semantic_context",
        )
    return matches[0]


def _target_selector(
    target: SemanticTarget,
    workspace: Any,
    metadata: Mapping[str, Mapping[str, Any]],
) -> str:
    if target.kind in {"product", "operation"}:
        return target.ref
    from .find import _metadata_card

    return str(_metadata_card(target.ref, metadata[target.identity])["selector"])


def _public_context(
    context: SemanticContext,
    terms: Sequence[tuple[SemanticTerm, tuple[str, ...]]],
    verified: Sequence[VerifiedQuery],
    exclusions: Sequence[tuple[SemanticExclusion, tuple[str, ...]]],
    derived: Sequence[tuple[DerivedMetric, tuple[str, ...]]] | None = None,
) -> dict[str, Any]:
    derived = derived or ()
    return {
        "schema_version": SCHEMA_VERSION,
        "instructions": context.instructions,
        "matches": [
            {
                "kind": "term",
                "declaration": item.name,
                "matched_phrases": list(phrases),
                "target": item.target.contract(),
            }
            for item, phrases in terms
        ]
        + [
            {
                "kind": "verified_query",
                "declaration": item.name,
                "matched_phrases": [item.question],
                "target": {"kind": "operation", "ref": item.operation},
            }
            for item in verified
        ]
        + public_derived_matches(derived),
        "exclusions": [
            {
                "declaration": item.name,
                "matched_phrases": list(phrases),
                "target": item.target.contract(),
                "reason": item.reason,
            }
            for item, phrases in exclusions
        ],
    }


__all__ = [
    "SemanticResolution",
    "is_semantic_card",
    "load_agent_workspace",
    "resolve_semantic_context",
]
