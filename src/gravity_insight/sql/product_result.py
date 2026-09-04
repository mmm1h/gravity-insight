"""Typed inner conclusions for registered SQL product envelopes."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from gravity_insight.contracts.envelope_obligations import (
    DataCompleteness,
    DiagnosticEvidence,
    DiagnosticState,
    EnvelopeObligations,
    ExecutionStatus,
    MutationCertainty,
    MutationState,
    SemanticState,
    SemanticValidity,
)
from gravity_insight.sql.time_window import summarize_custom_result


_LEGACY_COMPLETENESS_REASONS = {
    "TOTAL_ROW_COUNT_MATCH": "total_row_count_match",
    "ROW_CAP_REACHED_WITHOUT_TOTAL": "possible_truncation",
    "BELOW_ROW_CAP": "below_row_cap",
}


def summarize_product_rows(
    definition: Mapping[str, Any],
    rows: list[dict[str, Any]],
    app_ids: tuple[int, ...],
    start_at: datetime,
    end_at: datetime,
) -> tuple[
    dict[str, Any], ExecutionStatus, list[str], list[str], DataCompleteness
]:
    return summarize_custom_result(
        rows,
        app_ids,
        start_at,
        end_at,
        output_fields=list(definition["output_fields"]),
        max_rows=int(definition.get("max_rows", 1000)),
        measurement=str(definition.get("measurement", "workspace aggregate")),
    )


def product_envelope_parts(
    payload: Mapping[str, Any],
    execution: ExecutionStatus,
    completeness: DataCompleteness,
) -> tuple[dict[str, Any], EnvelopeObligations]:
    """Return the legacy projection and its lossless typed conclusions."""

    selected = dict(payload)
    selected.update(
        status=execution.state.value,
        row_cap_reached=completeness.facts["row_cap_reached"],
        completeness=completeness.state.value,
        completeness_reason=_LEGACY_COMPLETENESS_REASONS[
            completeness.evidence_code
        ],
    )
    obligations = EnvelopeObligations(
        execution_status=execution,
        data_completeness=completeness,
        semantic_validity=SemanticValidity(
            SemanticState.UNKNOWN, ("SQL_RESULT_SEMANTICS_NOT_EVALUATED",)
        ),
        diagnostic_evidence=DiagnosticEvidence(DiagnosticState.NONE),
        mutation_certainty=MutationCertainty(
            MutationState.NOT_APPLICABLE, "READ_ONLY_PATH"
        ),
    )
    return selected, obligations


__all__ = ["product_envelope_parts", "summarize_product_rows"]
