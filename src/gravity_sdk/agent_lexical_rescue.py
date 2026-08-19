"""Strict second-stage scoring for lexical product retrieval."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any


MINIMUM_SCORE = 0.500
MINIMUM_MATCHED_TERMS = 4
MINIMUM_MARGIN = 0.250


@dataclass(frozen=True)
class IndexedEvidenceDecision:
    match: tuple[Any, float, tuple[str, ...]] | None
    reason: str
    top_score: float
    runner_up_score: float
    matched_terms: int

    def receipt(self) -> dict[str, Any]:
        return {
            "reason": self.reason,
            "top_score": self.top_score,
            "runner_up_score": self.runner_up_score,
            "matched_terms": self.matched_terms,
            "minimum_score": MINIMUM_SCORE,
            "minimum_matched_terms": MINIMUM_MATCHED_TERMS,
            "minimum_margin": MINIMUM_MARGIN,
        }


def indexed_evidence_rescue(
    documents: Sequence[Any],
    query_terms: frozenset[str],
    document_terms: Mapping[str, frozenset[str]],
    idf: Mapping[str, float],
) -> IndexedEvidenceDecision:
    """Return one clear owner without letting unseen filler lower confidence."""

    denominator = sum(idf[term] for term in query_terms if term in idf)
    if not denominator:
        return IndexedEvidenceDecision(None, "no_indexed_terms", 0.0, 0.0, 0)
    ranked: list[tuple[float, Any, tuple[str, ...]]] = []
    for document in documents:
        matched = tuple(sorted(query_terms & document_terms[document.identity]))
        score = round(sum(idf[term] for term in matched) / denominator, 6)
        ranked.append((score, document, matched))
    ranked.sort(
        key=lambda item: (-item[0], item[1].selector, item[1].identity)
    )
    score, document, matched = ranked[0]
    runner_up = ranked[1][0] if len(ranked) > 1 else 0.0
    reason = (
        "score_below_threshold" if score < MINIMUM_SCORE
        else "insufficient_matched_terms" if len(matched) < MINIMUM_MATCHED_TERMS
        else "margin_below_threshold" if score - runner_up < MINIMUM_MARGIN
        else "selected"
    )
    match = (document, score, matched) if reason == "selected" else None
    return IndexedEvidenceDecision(match, reason, score, runner_up, len(matched))


def query_top_score(
    query_terms: frozenset[str],
    documents: Sequence[Any],
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


__all__ = ["IndexedEvidenceDecision", "indexed_evidence_rescue", "query_top_score"]
