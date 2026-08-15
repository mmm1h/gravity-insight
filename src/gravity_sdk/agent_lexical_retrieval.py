"""Deterministic zero-candidate retrieval over registered Agent products."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
import copy
from dataclasses import dataclass
import math
import re
import unicodedata
from typing import Any


ALGORITHM = "idf_weighted_term_coverage.v1"
MINIMUM_SCORE = 0.375
MINIMUM_MATCHED_TERMS = 2

_ASCII_WORD = re.compile(r"[a-z0-9]+", re.IGNORECASE)
_CJK_RUN = re.compile(r"[\u3400-\u9fff]+")
_ENGLISH_STOP_WORDS = frozenset({
    "a", "an", "and", "are", "be", "can", "for", "from", "get", "give",
    "i", "in", "is", "me", "of", "on", "or", "please", "read", "show",
    "the", "this", "to", "use", "want", "with",
})
_DIRECT_SELECTORS = (
    "analysis.query.spec",
    "analysis.query.spec:event",
    "analysis.query.spec:funnel",
    "analysis.query.spec:property",
    "analysis.query.spec:retention",
    "analysis.query.spec:scatter",
    "analysis.segment.rule.spec",
    "composite:user_journey",
    "metadata:search",
    "metadata:table_lineage",
    "material.asset.fetch",
)


@dataclass(frozen=True)
class LexicalDocument:
    identity: str
    selector: str
    document_kind: str
    fields: tuple[str, ...]
    payload: Mapping[str, Any]


@dataclass(frozen=True)
class LexicalMatch:
    document: LexicalDocument
    score: float
    matched_terms: tuple[str, ...]


@dataclass(frozen=True)
class LexicalDecision:
    matches: tuple[LexicalMatch, ...]
    disposition: str
    threshold: float
    top_score: float

    def receipt(self) -> dict[str, Any]:
        return {
            "algorithm": ALGORITHM,
            "disposition": self.disposition,
            "minimum_score": self.threshold,
            "minimum_matched_terms": MINIMUM_MATCHED_TERMS,
            "top_score": self.top_score,
            "matches": [
                {
                    "selector": item.document.selector,
                    "document_kind": item.document.document_kind,
                    "score": item.score,
                    "matched_terms": list(item.matched_terms),
                }
                for item in self.matches
            ],
        }


@dataclass(frozen=True)
class AppliedLexicalFallback:
    candidates: tuple[tuple[str, Mapping[str, Any]], ...]
    gaps: tuple[dict[str, Any], ...]
    receipt: Mapping[str, Any]


def apply_lexical_fallback(
    query: str,
    *,
    existing_candidates: Sequence[tuple[str, Mapping[str, Any]]],
    existing_semantic_gaps: Sequence[Mapping[str, Any]],
    fallback_blocked: bool,
    workspace: Any | None,
    sources: Any | None,
    domain: str | None,
    platform: str | None,
) -> AppliedLexicalFallback:
    """Apply retrieval only after the complete existing route chain abstains."""

    if existing_candidates or existing_semantic_gaps or fallback_blocked:
        return AppliedLexicalFallback(
            tuple(existing_candidates), (), _not_needed_receipt()
        )
    decision = _workspace_decision(
        query,
        workspace=workspace,
        sources=sources,
        domain=domain,
        platform=platform,
    )
    return _apply_decision(query, decision)


def response_match_policy(receipt: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "success_requires": "at least 80% query-term coverage",
        "partial_matches_are_executable": False,
        "zero_candidate_lexical_fallback": dict(receipt),
    }


def retrieve_registered_products(
    query: str,
    *,
    composite_inventory: Sequence[Mapping[str, Any]],
    recipe_inventory: Sequence[Mapping[str, Any]] = (),
    product_inventory: Sequence[Mapping[str, Any]] = (),
    export_inventory: Sequence[Mapping[str, Any]] = (),
    domain: str | None = None,
    platform: str | None = None,
    threshold: float = MINIMUM_SCORE,
) -> LexicalDecision:
    """Return every registered product at or above one fixed confidence floor."""

    documents = registered_documents(
        composite_inventory=composite_inventory,
        recipe_inventory=recipe_inventory,
        product_inventory=product_inventory,
        export_inventory=export_inventory,
        domain=domain,
        platform=platform,
    )
    query_terms = _terms(query)
    if not documents or not query_terms:
        return LexicalDecision((), "below_threshold", threshold, 0.0)
    document_terms, idf, denominator = _retrieval_model(documents, query_terms)
    scored = _matches_at_threshold(
        documents, query_terms, document_terms, idf, denominator, threshold
    )
    scored.sort(key=lambda item: (-item.score, item.document.selector, item.document.identity))
    disposition = (
        "below_threshold" if not scored
        else "single_match" if len(scored) == 1
        else "multiple_matches"
    )
    top_score = scored[0].score if scored else _top_score(
        query_terms, documents, document_terms, idf, denominator
    )
    return LexicalDecision(tuple(scored), disposition, threshold, top_score)


def _workspace_decision(
    query: str,
    *,
    workspace: Any | None,
    sources: Any | None,
    domain: str | None,
    platform: str | None,
) -> LexicalDecision:
    from .agent_batch_sources import snapshot_products, snapshot_recipes
    from .agent_capabilities import composite_capability_inventory
    from .agent_semantic_context import load_agent_workspace

    selected_workspace = load_agent_workspace(workspace, sources)
    warnings: list[str] = []
    return retrieve_registered_products(
        query,
        composite_inventory=(
            sources.composite_inventory
            if sources is not None
            else composite_capability_inventory()
        ),
        recipe_inventory=(
            sources.recipe_inventory
            if sources is not None
            else snapshot_recipes(selected_workspace)
        ),
        product_inventory=(
            sources.product_inventory
            if sources is not None
            else snapshot_products(selected_workspace, warnings)
        ),
        export_inventory=(sources.export_inventory if sources is not None else ()),
        domain=domain,
        platform=platform,
    )


def _apply_decision(query: str, decision: LexicalDecision) -> AppliedLexicalFallback:
    receipt = decision.receipt()
    if decision.disposition == "single_match":
        match = decision.matches[0]
        candidate = selected_candidate(match)
        gap = selected_gap(query, match)
        return AppliedLexicalFallback(
            (candidate,) if candidate is not None else (),
            (gap,) if gap is not None else (),
            receipt,
        )
    if decision.disposition == "multiple_matches":
        from .agent_intent_routing import product_selection_gap

        gap = product_selection_gap(
            query,
            [match.document.selector for match in decision.matches],
            reason=(
                "offline lexical retrieval identified multiple registered products "
                "above the confidence threshold"
            ),
        )
        gap["lexical_retrieval"] = receipt
        return AppliedLexicalFallback((), (gap,), receipt)
    return AppliedLexicalFallback((), (), receipt)


def _not_needed_receipt() -> dict[str, Any]:
    return {
        "algorithm": ALGORITHM,
        "disposition": "not_needed",
        "minimum_score": MINIMUM_SCORE,
        "minimum_matched_terms": MINIMUM_MATCHED_TERMS,
        "top_score": 0.0,
        "matches": [],
    }


def _retrieval_model(
    documents: Sequence[LexicalDocument], query_terms: frozenset[str]
) -> tuple[dict[str, frozenset[str]], dict[str, float], float]:
    document_terms = {item.identity: _document_terms(item) for item in documents}
    document_frequency = Counter(
        term for terms in document_terms.values() for term in set(terms)
    )
    idf = {
        term: math.log((len(documents) + 1) / (count + 1)) + 1.0
        for term, count in document_frequency.items()
    }
    denominator = sum(
        idf.get(term, _unseen_idf(len(documents))) for term in query_terms
    )
    return document_terms, idf, denominator


def _matches_at_threshold(
    documents: Sequence[LexicalDocument],
    query_terms: frozenset[str],
    document_terms: Mapping[str, frozenset[str]],
    idf: Mapping[str, float],
    denominator: float,
    threshold: float,
) -> list[LexicalMatch]:
    scored: list[LexicalMatch] = []
    for document in documents:
        available = document_terms[document.identity]
        matched = tuple(sorted(query_terms & available))
        numerator = sum(idf[term] for term in matched)
        score = round(numerator / denominator, 6) if denominator else 0.0
        if score >= threshold and len(matched) >= MINIMUM_MATCHED_TERMS:
            scored.append(LexicalMatch(document, score, matched))
    return scored


def selected_candidate(
    match: LexicalMatch,
) -> tuple[str, Mapping[str, Any]] | None:
    """Re-expose a selected existing card with retrieval evidence, never a new card."""

    if match.document.document_kind == "gap":
        return None
    card = copy.deepcopy(dict(match.document.payload))
    card["match"] = {
        "confidence": "strong",
        "coverage": match.score,
        "matched_terms": list(match.matched_terms),
        "missing_terms": [],
        "score": round(match.score * 1000),
        "exact_selector": False,
        "lexical_retrieval": {
            "algorithm": ALGORITHM,
            "minimum_score": MINIMUM_SCORE,
        },
    }
    return "catalog", card


def selected_gap(query: str, match: LexicalMatch) -> dict[str, Any] | None:
    if match.document.document_kind != "gap":
        return None
    gap = copy.deepcopy(dict(match.document.payload))
    gap["query"] = query
    gap["lexical_retrieval"] = {
        "algorithm": ALGORITHM,
        "minimum_score": MINIMUM_SCORE,
        "score": match.score,
        "matched_terms": list(match.matched_terms),
    }
    return gap


def registered_documents(
    *,
    composite_inventory: Sequence[Mapping[str, Any]],
    recipe_inventory: Sequence[Mapping[str, Any]] = (),
    product_inventory: Sequence[Mapping[str, Any]] = (),
    export_inventory: Sequence[Mapping[str, Any]] = (),
    domain: str | None = None,
    platform: str | None = None,
) -> tuple[LexicalDocument, ...]:
    """Build the index from existing card fields and registered gap wording."""

    documents: list[LexicalDocument] = []
    if platform is None:
        documents.extend(_composite_documents(composite_inventory, domain))
        documents.extend(_direct_documents(domain))
        documents.extend(_recipe_documents(recipe_inventory, domain))
        documents.extend(_product_documents(product_inventory, domain))
        documents.extend(_export_documents(export_inventory, domain))
        documents.extend(_gap_documents(domain))
    deduplicated: dict[str, LexicalDocument] = {}
    for document in documents:
        deduplicated.setdefault(document.identity, document)
    return tuple(deduplicated[key] for key in sorted(deduplicated))


def _composite_documents(
    inventory: Sequence[Mapping[str, Any]], domain: str | None
) -> list[LexicalDocument]:
    from .agent_capabilities import composite_capability_cards

    documents: list[LexicalDocument] = []
    for definition in inventory:
        selected_domain = str(definition.get("domain", ""))
        accepted = tuple(definition.get("accepted_domains", (selected_domain,)))
        if domain is not None and domain not in accepted:
            continue
        name = str(definition["name"])
        selector = f"composite:{name}"
        cards = composite_capability_cards(
            selector, domain=domain, platform=None, inventory=inventory
        )
        card = next((item for item in cards if item.get("selector") == selector), None)
        if card is None:
            continue
        documents.append(_card_document(card, name=name))
    return documents


def _direct_documents(domain: str | None) -> list[LexicalDocument]:
    from .agent_capabilities import analysis_query_spec_cards
    from .agent_material_asset import material_asset_capability_cards
    from .agent_metadata_search import metadata_search_capability_cards
    from .agent_table_lineage import table_lineage_capability_cards
    from .agent_user_journey import user_journey_capability_cards

    builders = (
        analysis_query_spec_cards,
        user_journey_capability_cards,
        metadata_search_capability_cards,
        table_lineage_capability_cards,
        material_asset_capability_cards,
    )
    documents: list[LexicalDocument] = []
    for selector in _DIRECT_SELECTORS:
        for build in builders:
            cards = build(selector, domain=domain, platform=None)
            card = next((item for item in cards if item.get("selector") == selector), None)
            if card is not None:
                documents.append(_card_document(card))
                break
    return documents


def _recipe_documents(
    inventory: Sequence[Mapping[str, Any]], domain: str | None
) -> list[LexicalDocument]:
    if domain is not None:
        return []
    from .agent_sources import snapshot_recipe_cards

    documents: list[LexicalDocument] = []
    frozen = tuple(inventory)
    for recipe in frozen:
        name = str(recipe["name"])
        cards = snapshot_recipe_cards(name, frozen)
        card = next((item for item in cards if item.get("selector") == f"@{name}"), None)
        if card is not None:
            documents.append(_card_document(card, name=name))
    return documents


def _product_documents(
    inventory: Sequence[Mapping[str, Any]], domain: str | None
) -> list[LexicalDocument]:
    if domain not in {None, "sql"}:
        return []
    from .agent_sources import snapshot_product_cards

    documents: list[LexicalDocument] = []
    frozen = tuple(inventory)
    for product in frozen:
        name = str(product["name"])
        cards = snapshot_product_cards(name, frozen)
        card = next((item for item in cards if item.get("selector") == f"sql:{name}"), None)
        if card is not None:
            documents.append(_card_document(card, name=name))
    return documents


def _export_documents(
    inventory: Sequence[Mapping[str, Any]], domain: str | None
) -> list[LexicalDocument]:
    if domain not in {None, "analysis", "export", "material", "report"}:
        return []
    from .agent_export import export_capability_cards

    documents: list[LexicalDocument] = []
    for item in inventory:
        selector = str(item.get("operation_id", ""))
        cards = export_capability_cards(
            selector, domain=domain, platform=None, inventory=inventory
        )
        card = next((value for value in cards if value.get("selector") == selector), None)
        if card is not None:
            documents.append(_card_document(card))
    return documents


def _gap_documents(domain: str | None) -> list[LexicalDocument]:
    if domain is not None:
        return []
    from .agent_unavailable import registered_unavailable_gaps

    return [
        LexicalDocument(
            identity=f"gap:{gap['code']}",
            selector=f"gap:{gap['code']}",
            document_kind="gap",
            fields=tuple(str(gap.get(key, "")) for key in (
                "journey", "code", "reason", "next_action"
            )),
            payload=gap,
        )
        for gap in registered_unavailable_gaps()
    ]


def _card_document(card: Mapping[str, Any], *, name: str | None = None) -> LexicalDocument:
    selector = str(card["selector"])
    selected_name = name or str(
        card.get("composite")
        or card.get("analysis_kind")
        or card.get("metadata_kind")
        or card.get("product")
        or card.get("recipe")
        or selector
    )
    return LexicalDocument(
        identity=f"card:{selector}",
        selector=selector,
        document_kind="card",
        fields=(selected_name, selector, str(card.get("description", ""))),
        payload=card,
    )


def _document_terms(document: LexicalDocument) -> frozenset[str]:
    return frozenset(term for field in document.fields for term in _terms(field))


def _terms(value: str) -> frozenset[str]:
    normalized = unicodedata.normalize("NFKC", str(value)).casefold()
    terms = {
        f"w:{word}"
        for word in _ASCII_WORD.findall(normalized.replace("_", " ").replace(".", " "))
        if len(word) >= 2 and word not in _ENGLISH_STOP_WORDS
    }
    for run in _CJK_RUN.findall(normalized):
        if len(run) == 1:
            terms.add(f"h:{run}")
        for width in (2, 3):
            terms.update(
                f"h:{run[start:start + width]}"
                for start in range(max(0, len(run) - width + 1))
            )
    return frozenset(terms)


def _unseen_idf(document_count: int) -> float:
    return math.log(document_count + 1) + 1.0


def _top_score(
    query_terms: frozenset[str],
    documents: Sequence[LexicalDocument],
    document_terms: Mapping[str, frozenset[str]],
    idf: Mapping[str, float],
    denominator: float,
) -> float:
    if not denominator:
        return 0.0
    scores = [
        sum(idf[term] for term in query_terms if term in document_terms[item.identity])
        / denominator
        for item in documents
    ]
    return round(max(scores, default=0.0), 6)


__all__ = [
    "ALGORITHM",
    "AppliedLexicalFallback",
    "LexicalDecision",
    "MINIMUM_SCORE",
    "MINIMUM_MATCHED_TERMS",
    "apply_lexical_fallback",
    "registered_documents",
    "retrieve_registered_products",
    "response_match_policy",
    "selected_candidate",
    "selected_gap",
]
