"""Target-independent delivery contract compiled from governed Analysis Result."""

from __future__ import annotations

import copy
import json
from collections.abc import Mapping
from typing import Any

from .agent_runtime_contracts import (
    AgentRuntimeContractError,
    canonical_digest,
    validate_schema,
)
from .analysis_result_contract import compile_analysis_result


SCHEMA_VERSION = "gravity.analysis-artifact.v1"
MAX_SOURCE_BYTES = 8 * 1024 * 1024
MAX_ARTIFACT_BYTES = 8 * 1024 * 1024
MAX_RENDERED_BYTES = 1024 * 1024
MAX_FINDINGS = 256
MAX_SECTIONS = 8
_SCHEMA_NAME = "analysis-artifact-v1.schema.json"
_LIMITS = {
    "max_source_bytes": MAX_SOURCE_BYTES,
    "max_artifact_bytes": MAX_ARTIFACT_BYTES,
    "max_rendered_bytes": MAX_RENDERED_BYTES,
    "max_findings": MAX_FINDINGS,
    "max_sections": MAX_SECTIONS,
}
_SECTIONS = (
    {"section_id": "overview", "title": "Overview", "kind": "overview", "source_paths": ["/status", "/question", "/filters"]},
    {"section_id": "semantics", "title": "Semantics", "kind": "semantics", "source_paths": ["/semantic_references", "/metric_uris", "/dimension_uris"]},
    {"section_id": "findings", "title": "Findings", "kind": "findings", "source_paths": ["/findings", "/excluded_factors"]},
    {"section_id": "hypotheses", "title": "Hypotheses", "kind": "hypotheses", "source_paths": ["/hypotheses"]},
    {"section_id": "claims", "title": "Claims", "kind": "claims", "source_paths": ["/claims"]},
    {"section_id": "recommendations", "title": "Recommendations", "kind": "recommendations", "source_paths": ["/recommended_next_actions"]},
    {"section_id": "limitations", "title": "Limitations", "kind": "limitations", "source_paths": ["/limitations"]},
    {"section_id": "evidence", "title": "Evidence", "kind": "evidence", "source_paths": ["/evidence", "/reason_codes"]},
)


class AnalysisArtifactContractError(AgentRuntimeContractError):
    """Analysis delivery would weaken or exceed its governed source contract."""


def compile_analysis_artifact(value: Mapping[str, Any]) -> dict[str, Any]:
    """Compile one governed Analysis Result without adding conclusions."""

    try:
        result = compile_analysis_result(value)
    except AgentRuntimeContractError as exc:
        raise AnalysisArtifactContractError(str(exc)) from exc
    if len(_canonical_bytes(result)) > MAX_SOURCE_BYTES:
        raise AnalysisArtifactContractError("Analysis Result exceeds the Artifact source byte limit")
    if len(result["findings"]) > MAX_FINDINGS:
        raise AnalysisArtifactContractError("Analysis Result exceeds the Artifact finding limit")
    artifact = _artifact_payload(result)
    digest = canonical_digest(artifact)
    artifact["artifact_id"] = f"sha256:{digest}"
    artifact["artifact_digest"] = digest
    selected = validate_analysis_artifact(artifact)
    if len(_canonical_bytes(selected)) > MAX_ARTIFACT_BYTES:
        raise AnalysisArtifactContractError("Analysis Artifact exceeds its byte limit")
    return selected


def validate_analysis_artifact(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate schema, self-digest and non-strengthening internal projections."""

    if not isinstance(value, Mapping):
        raise AnalysisArtifactContractError("Analysis Artifact must be an object")
    selected = copy.deepcopy(dict(value))
    try:
        validate_schema(selected, _SCHEMA_NAME, "Analysis Artifact")
    except AgentRuntimeContractError as exc:
        raise AnalysisArtifactContractError(str(exc)) from exc
    _validate_digest(selected)
    _validate_projections(selected)
    _validate_status(selected)
    if len(_canonical_bytes(selected)) > MAX_ARTIFACT_BYTES:
        raise AnalysisArtifactContractError("Analysis Artifact exceeds its byte limit")
    return selected


def verify_analysis_artifact_source(
    artifact: Mapping[str, Any], analysis_result: Mapping[str, Any]
) -> dict[str, Any]:
    """Prove exact source parity rather than trusting a re-digested Artifact."""

    selected = validate_analysis_artifact(artifact)
    expected = compile_analysis_artifact(analysis_result)
    if selected != expected:
        raise AnalysisArtifactContractError("Analysis Artifact and source Result disagree")
    return selected


def _artifact_payload(result: Mapping[str, Any]) -> dict[str, Any]:
    snapshot = result["execution_snapshot"]
    receipts = copy.deepcopy(result["receipt_references"])
    semantic_references = copy.deepcopy(result["semantics"])
    return {
        "artifact_kind": "analysis_artifact",
        "schema_version": SCHEMA_VERSION,
        "status": result["status"],
        "title": _title(result),
        "question": result["question"],
        "source": {
            "analysis_result_schema_version": result["schema_version"],
            "result_digest": canonical_digest(result),
            "execution_snapshot_digest": snapshot["snapshot_digest"],
            "journey": copy.deepcopy(result["journey"]),
            "skill_uri": result["skill"].get("uri") if isinstance(result["skill"], Mapping) else None,
            "receipt_references_digest": canonical_digest(receipts),
        },
        "scope": copy.deepcopy(result["scope"]),
        "semantic_references": semantic_references,
        "metric_uris": _typed_uris(semantic_references, "metric://"),
        "dimension_uris": _typed_uris(semantic_references, "dimension://"),
        "filters": {"source_path": "/scope", "values": copy.deepcopy(result["scope"])},
        "visualization": {"intent": "unspecified", "reason_code": "SOURCE_VISUALIZATION_UNDECLARED"},
        "sections": copy.deepcopy(list(_SECTIONS)),
        "findings": copy.deepcopy(result["findings"]),
        "excluded_factors": copy.deepcopy(result["excluded_factors"]),
        "hypotheses": copy.deepcopy(result["hypotheses"]),
        "claims": {"allowed": copy.deepcopy(result["allowed_claims"]), "forbidden": copy.deepcopy(result["forbidden_claims"])},
        "recommended_next_actions": copy.deepcopy(result["recommended_next_actions"]),
        "limitations": copy.deepcopy(result["limitations"]),
        "evidence": {
            "completeness": result["completeness"],
            "data_quality": copy.deepcopy(result["data_quality"]),
            "evidence_level": result["evidence_level"],
            "context_references": copy.deepcopy(snapshot["context_packs"]),
            "receipt_references": receipts,
            "source_network_called": bool(result["network_called"]),
        },
        "can_run_status": result["can_run_status"],
        "reason_codes": copy.deepcopy(result["reason_codes"]),
        "limits": dict(_LIMITS),
        "network_called": False,
    }


def _validate_digest(artifact: dict[str, Any]) -> None:
    digest = artifact.pop("artifact_digest")
    artifact_id = artifact.pop("artifact_id")
    expected = canonical_digest(artifact)
    artifact["artifact_id"] = artifact_id
    artifact["artifact_digest"] = digest
    if digest != expected or artifact_id != f"sha256:{expected}":
        raise AnalysisArtifactContractError("Analysis Artifact digest is invalid")


def _validate_projections(artifact: Mapping[str, Any]) -> None:
    semantics = artifact["semantic_references"]
    if artifact["metric_uris"] != _typed_uris(semantics, "metric://"):
        raise AnalysisArtifactContractError("Analysis Artifact Metric URI projection changed")
    if artifact["dimension_uris"] != _typed_uris(semantics, "dimension://"):
        raise AnalysisArtifactContractError("Analysis Artifact Dimension URI projection changed")
    if artifact["filters"]["values"] != artifact["scope"]:
        raise AnalysisArtifactContractError("Analysis Artifact filters changed source scope")
    if artifact["sections"] != list(_SECTIONS) or artifact["limits"] != _LIMITS:
        raise AnalysisArtifactContractError("Analysis Artifact fixed delivery contract changed")
    receipts = artifact["evidence"]["receipt_references"]
    if artifact["source"]["receipt_references_digest"] != canonical_digest(receipts):
        raise AnalysisArtifactContractError("Analysis Artifact Receipt binding changed")


def _validate_status(artifact: Mapping[str, Any]) -> None:
    if artifact["status"] == "success":
        checks = (
            artifact["can_run_status"] == "verified",
            artifact["evidence"]["evidence_level"] is not None,
            artifact["evidence"]["data_quality"].get("status") in {"pass", "warn"},
            bool(artifact["findings"]),
            not artifact["reason_codes"],
        )
    else:
        empty = (
            artifact["findings"], artifact["excluded_factors"], artifact["hypotheses"],
            artifact["claims"]["allowed"], artifact["recommended_next_actions"],
        )
        checks = (
            artifact["evidence"]["evidence_level"] is None,
            bool(artifact["reason_codes"]),
            not any(empty),
            artifact["status"] == ("invalid" if artifact["can_run_status"] == "invalid" else "blocked"),
        )
    if not all(checks):
        raise AnalysisArtifactContractError("Analysis Artifact status strengthens its source evidence")


def _typed_uris(values: list[Mapping[str, Any]], prefix: str) -> list[str]:
    return [str(item["uri"]) for item in values if str(item["uri"]).startswith(prefix)]


def _title(result: Mapping[str, Any]) -> str:
    question = result.get("question")
    if isinstance(question, str) and question.strip():
        return question
    return f"Analysis result: {result['journey']['journey_id']}"


def _canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise AnalysisArtifactContractError("Analysis Artifact source must be canonical JSON") from exc


class AnalysisArtifactService:
    """Lazy offline facade for compile, verify, render and local publication."""

    def compile(self, result: Mapping[str, Any]) -> dict[str, Any]:
        return compile_analysis_artifact(result)

    def validate(self, artifact: Mapping[str, Any]) -> dict[str, Any]:
        return validate_analysis_artifact(artifact)

    def verify(self, artifact: Mapping[str, Any], result: Mapping[str, Any]) -> dict[str, Any]:
        return verify_analysis_artifact_source(artifact, result)

    def render_markdown(self, artifact: Mapping[str, Any], *, max_bytes: int = MAX_RENDERED_BYTES) -> dict[str, Any]:
        from .analysis_artifact_markdown import render_analysis_artifact_markdown

        return render_analysis_artifact_markdown(artifact, max_bytes=max_bytes)

    def write_artifact(self, artifact: Mapping[str, Any], destination: str) -> dict[str, Any]:
        from .analysis_artifact_delivery import write_analysis_artifact

        return write_analysis_artifact(artifact, destination)

    def write_markdown(self, artifact: Mapping[str, Any], destination: str, *, max_bytes: int = MAX_RENDERED_BYTES) -> dict[str, Any]:
        from .analysis_artifact_delivery import write_analysis_markdown

        return write_analysis_markdown(artifact, destination, max_bytes=max_bytes)


__all__ = [
    "AnalysisArtifactContractError",
    "AnalysisArtifactService",
    "MAX_RENDERED_BYTES",
    "SCHEMA_VERSION",
    "compile_analysis_artifact",
    "validate_analysis_artifact",
    "verify_analysis_artifact_source",
]
