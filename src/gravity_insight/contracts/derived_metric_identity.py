"""Data-quality contract for derived numeric ratio identity checks."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from typing import Any

from .envelope_obligations import (
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
from ..data_quality import aggregate_data_quality, data_quality_result


def identity_quality(
    status: str, scope: str, reason_code: str | None
) -> dict[str, Any]:
    return data_quality_result(
        [{"check_id": "ratio-identity", "status": status, "scope": scope}],
        reason_codes=[] if reason_code is None else [reason_code],
    )


def ratio_identity_result(
    spec: Mapping[str, Any],
    rows: list[dict[str, Any]],
    *,
    quality_counts: Counter[str],
    reason_codes: list[str],
    partial: bool,
    absolute_tolerance: str,
    quantization_tolerance: str,
) -> dict[str, Any]:
    result_name = str(spec["result_name"])
    quality = _aggregate_quality(quality_counts, reason_codes, result_name)
    status = "success" if not partial and quality["status"] == "pass" else "partial"
    payload = {
        "operator": "ratio_identity",
        "result_name": result_name,
        "ok": status == "success",
        "status": status,
        "comparison": "absolute_difference",
        "tolerance": {
            "absolute": absolute_tolerance,
            "quantization": quantization_tolerance,
        },
        "data_quality": quality,
        "quality_counts": {
            quality_status: quality_counts[quality_status]
            for quality_status in ("pass", "warn", "fail", "unknown")
            if quality_counts[quality_status]
        },
        "rows": rows,
    }
    obligations = _obligations(partial, quality, quality_counts, len(rows))
    return _serialize(payload, obligations)


def _aggregate_quality(
    quality_counts: Counter[str], reason_codes: list[str], scope: str
) -> dict[str, Any]:
    summaries = [
        data_quality_result(
            [{
                "check_id": f"ratio-identity-{status}",
                "status": status,
                "scope": f"{scope}.rows",
            }]
        )
        for status in ("pass", "warn", "fail", "unknown")
        if quality_counts[status]
    ]
    aggregate = aggregate_data_quality(summaries)
    if not summaries:
        return aggregate
    return data_quality_result(
        aggregate["checks"], reason_codes=list(dict.fromkeys(reason_codes))
    )


def _obligations(
    partial: bool,
    quality: Mapping[str, Any],
    quality_counts: Counter[str],
    row_count: int,
) -> EnvelopeObligations:
    quality_status = str(quality["status"])
    incomplete = partial or quality_status != "pass"
    execution = ExecutionStatus(
        ExecutionState.PARTIAL if incomplete else ExecutionState.COMPLETE,
        "RATIO_IDENTITY_CHECK_PARTIAL" if incomplete else "RATIO_IDENTITY_CHECK_COMPLETE",
    )
    completeness = _completeness(partial, quality_counts, row_count)
    semantic_state, semantic_code = {
        "pass": (SemanticState.VALID, "RATIO_IDENTITY_SATISFIED"),
        "warn": (SemanticState.UNKNOWN, "RATIO_IDENTITY_QUANTIZATION_DRIFT"),
        "fail": (SemanticState.INVALID, "RATIO_IDENTITY_MISMATCH"),
        "unknown": (SemanticState.UNKNOWN, "RATIO_IDENTITY_UNDEFINED"),
    }[quality_status]
    diagnostic_codes = list(dict.fromkeys(quality["reason_codes"]))
    if partial:
        diagnostic_codes.append("UPSTREAM_PARTIAL")
    diagnostics = (
        DiagnosticEvidence(DiagnosticState.NONE)
        if not diagnostic_codes
        else DiagnosticEvidence(
            DiagnosticState.INCOMPLETE, tuple(dict.fromkeys(diagnostic_codes))
        )
    )
    return EnvelopeObligations(
        execution_status=execution,
        data_completeness=completeness,
        semantic_validity=SemanticValidity(semantic_state, (semantic_code,)),
        diagnostic_evidence=diagnostics,
        mutation_certainty=MutationCertainty(
            MutationState.NOT_APPLICABLE, "READ_ONLY_DERIVATION"
        ),
    )


def _completeness(
    partial: bool, quality_counts: Counter[str], row_count: int
) -> DataCompleteness:
    if partial:
        return DataCompleteness(
            CompletenessState.PREFIX,
            "UPSTREAM_RESULT_PARTIAL",
            {"rows_evaluated": row_count},
        )
    if quality_counts["unknown"]:
        return DataCompleteness(
            CompletenessState.UNKNOWN,
            "RATIO_IDENTITY_OPERANDS_INCOMPLETE",
            {"rows_evaluated": row_count, "undefined_rows": quality_counts["unknown"]},
        )
    return DataCompleteness(
        CompletenessState.COMPLETE,
        "RATIO_IDENTITY_ROWS_COMPLETE",
        {"rows_evaluated": row_count},
    )


def _serialize(
    payload: Mapping[str, Any], obligations: EnvelopeObligations
) -> dict[str, Any]:
    return serialize_envelope(payload, obligations)


__all__ = ["identity_quality", "ratio_identity_result"]
