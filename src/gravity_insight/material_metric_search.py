"""Offline metadata envelope for the versioned material metric catalog."""

from __future__ import annotations

from typing import Any

from .contracts.envelope_obligations import (
    CompletenessState,
    DataCompleteness,
    DiagnosticEvidence,
    DiagnosticState,
    EnvelopeObligations,
    ExecutionState,
    ExecutionStatus,
    MutationCertainty,
    MutationState,
    SemanticState,
    SemanticValidity,
    serialize_envelope,
)
from .material_metrics import (
    KIND,
    OPERATION_ID,
    SOURCE,
    catalog_metadata,
    search_rows,
)
from .result_source import LOCAL_CATALOG, result_source


SCHEMA_VERSION = "gravity.metadata-search.v1"


def search_material_metric_metadata(
    query: str,
    platform: str | None,
    *,
    limit: int | None,
    offset: int,
) -> dict[str, Any]:
    candidates = [_candidate(item) for item in search_rows(query, platform=platform)]
    candidates.sort(
        key=lambda item: (
            -int(item["score"]), str(item["platform"]), str(item["name"]).casefold()
        )
    )
    page = candidates[offset:] if limit is None else candidates[offset : offset + limit]
    payload = {
        "schema_version": SCHEMA_VERSION,
        "result_source": result_source(LOCAL_CATALOG),
        "ok": True,
        "status": "success",
        "offline": True,
        "query": query,
        "kind": KIND,
        "platform": platform,
        "scope": "runtime",
        "catalog": catalog_metadata(),
        "count": len(page),
        "total": len(candidates),
        "limit": limit,
        "offset": offset,
        "results": page,
        "failures": [],
    }
    return serialize_envelope(payload, _obligations(len(candidates), len(page)))


def _candidate(item: dict[str, Any]) -> dict[str, Any]:
    payload = item["payload"]
    return {
        "backend": "metadata",
        "kind": KIND,
        "scope": "runtime",
        "source": SOURCE,
        "operation_id": OPERATION_ID,
        "platform": payload["platform"],
        "name": payload["name"],
        "cname": payload["cname"],
        "score": item["score"],
        "payload": payload,
    }


def _obligations(total: int, count: int) -> EnvelopeObligations:
    return EnvelopeObligations(
        ExecutionStatus(ExecutionState.COMPLETE, "LOCAL_CATALOG_READ"),
        DataCompleteness(
            CompletenessState.COMPLETE,
            "VERSIONED_CATALOG_COMPLETE",
            {"matching_rows": total, "returned_rows": count},
        ),
        SemanticValidity(SemanticState.VALID, ("CATALOG_CONTRACT_VALIDATED",)),
        DiagnosticEvidence(DiagnosticState.NONE),
        MutationCertainty(MutationState.NOT_APPLICABLE, "READ_ONLY_CATALOG"),
    )


__all__ = ["search_material_metric_metadata"]
