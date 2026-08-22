"""Strict compiler for the cross-product Analysis Result contract."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from .agent_runtime_contracts import AgentRuntimeContractError, validate_schema
from .data_quality import DataQualityError, validate_data_quality_result
from .execution_snapshot import (
    ExecutionSnapshotError,
    compile_execution_snapshot,
)


SCHEMA_VERSION = "gravity.analysis-result.v1"
_SCHEMA_NAME = "analysis-result-v1.schema.json"


class AnalysisResultContractError(AgentRuntimeContractError):
    """An Analysis Result is malformed or exceeds its evidence boundary."""


def compile_analysis_result(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise AnalysisResultContractError("Analysis Result must be an object")
    result = copy.deepcopy(dict(value))
    try:
        validate_schema(result, _SCHEMA_NAME, "Analysis Result")
        snapshot = compile_execution_snapshot(result["execution_snapshot"])
        validate_data_quality_result(result["data_quality"])
    except (AgentRuntimeContractError, ExecutionSnapshotError, DataQualityError) as exc:
        raise AnalysisResultContractError(str(exc)) from exc
    result["execution_snapshot"] = snapshot
    _validate_snapshot_parity(result, snapshot)
    _validate_status(result, snapshot)
    _validate_context(result["context_pack"], snapshot["context_packs"])
    _reject_context_content(result["context_pack"])
    return result


def _validate_snapshot_parity(
    result: Mapping[str, Any], snapshot: Mapping[str, Any]
) -> None:
    pairs = (
        (result["journey"], snapshot["journey"]),
        (result["skill"], snapshot["skill"]),
        (result["capabilities"], snapshot["capabilities"]),
        (result["semantics"], snapshot["semantics"]),
        (result["operators"], snapshot["operators"]),
        (result["models"], snapshot["models"]),
    )
    if any(left != right for left, right in pairs):
        raise AnalysisResultContractError(
            "Analysis Result references disagree with its execution snapshot"
        )


def _validate_status(
    result: Mapping[str, Any], snapshot: Mapping[str, Any]
) -> None:
    status = result["status"]
    if status == "success":
        checks = (
            result["ok"] is True,
            result["exit_code"] == 0,
            result["can_run_status"] == "verified",
            result["question"] is not None,
            result["skill"] is not None,
            snapshot["status"] == "resolved",
            result["data_quality"]["status"] in {"pass", "warn"},
            bool(result["findings"]),
            bool(result["allowed_claims"]),
            not result["reason_codes"],
        )
        if not all(checks):
            raise AnalysisResultContractError(
                "Successful Analysis Result contradicts its evidence"
            )
        return
    empty_fields = (
        "findings",
        "excluded_factors",
        "hypotheses",
        "allowed_claims",
        "recommended_next_actions",
        "receipt_references",
    )
    checks = (
        result["ok"] is False,
        result["exit_code"] != 0,
        result["question"] is None,
        result["evidence_level"] is None,
        bool(result["reason_codes"]),
        all(not result[field] for field in empty_fields),
        status == "invalid" if result["can_run_status"] == "invalid" else status == "blocked",
    )
    if not all(checks):
        raise AnalysisResultContractError(
            "Non-success Analysis Result carries unsupported conclusions"
        )
    if status == "invalid" and result["network_called"]:
        raise AnalysisResultContractError("Invalid Analysis Result cannot call the network")


def _validate_context(value: Any, references: list[dict[str, Any]]) -> None:
    if not references:
        if value is not None:
            raise AnalysisResultContractError(
                "Analysis Result Context disagrees with its execution snapshot"
            )
        return
    if len(references) != 1 or not isinstance(value, Mapping):
        raise AnalysisResultContractError(
            "Analysis Result v1 requires exactly one referenced Context Pack"
        )
    reference = references[0]
    observed = {
        "requirement_uri": value.get("requirement", {}).get("requirement_id"),
        "requirement_digest": value.get("requirement", {}).get("digest"),
        "provider_uri": value.get("provider", {}).get("uri"),
        "provider_digest": value.get("provider", {}).get("digest"),
        "source_revision": value.get("provider", {}).get("source_revision"),
        "pack_digest": value.get("pack_digest"),
        "status": value.get("status"),
    }
    if observed != reference:
        raise AnalysisResultContractError(
            "Analysis Result Context reference disagrees with its snapshot"
        )


def _reject_context_content(value: Any) -> None:
    if value is None:
        return

    def walk(item: Any) -> None:
        if isinstance(item, Mapping):
            if "content" in item:
                raise AnalysisResultContractError(
                    "Analysis Result cannot expose Context bodies"
                )
            for child in item.values():
                walk(child)
        elif isinstance(item, list):
            for child in item:
                walk(child)

    walk(value)


__all__ = [
    "AnalysisResultContractError",
    "SCHEMA_VERSION",
    "compile_analysis_result",
]
