"""Deterministic, escaped Markdown rendering for Analysis Artifact v1."""

from __future__ import annotations

import hashlib
import html
import json
import re
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from .agent_runtime_contracts import AgentRuntimeContractError, canonical_digest, validate_schema
from .analysis_artifact import MAX_RENDERED_BYTES, validate_analysis_artifact


SCHEMA_VERSION = "gravity.analysis-rendering.v1"
_SCHEMA_NAME = "analysis-rendering-v1.schema.json"
_MARKDOWN_CONTROL = re.compile(r"([\\`*_{}\[\]()#+\-.!|>/])")


class AnalysisArtifactRenderError(AgentRuntimeContractError):
    """An Artifact cannot be represented by the bounded Markdown renderer."""


def render_analysis_artifact_markdown(
    value: Mapping[str, Any], *, max_bytes: int = MAX_RENDERED_BYTES
) -> dict[str, Any]:
    artifact = validate_analysis_artifact(value)
    maximum = _render_limit(max_bytes)
    content = _render(artifact)
    encoded = content.encode("utf-8")
    if len(encoded) > maximum:
        raise AnalysisArtifactRenderError("Markdown rendering exceeds its byte limit")
    content_sha256 = hashlib.sha256(encoded).hexdigest()
    source = {
        "artifact_id": artifact["artifact_id"],
        "artifact_digest": artifact["artifact_digest"],
        "result_digest": artifact["source"]["result_digest"],
        "receipt_references_digest": artifact["source"]["receipt_references_digest"],
    }
    rendering = {
        "schema_version": SCHEMA_VERSION,
        "format": "markdown",
        "media_type": "text/markdown",
        "renderer": {"id": "gravity.markdown", "version": 1},
        "source": source,
        "content": content,
        "content_size_bytes": len(encoded),
        "content_sha256": content_sha256,
        "binding_digest": _binding_digest(source, content_sha256),
        "network_called": False,
    }
    return validate_analysis_rendering(rendering)


def validate_analysis_rendering(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise AnalysisArtifactRenderError("Analysis rendering must be an object")
    selected = dict(value)
    try:
        validate_schema(selected, _SCHEMA_NAME, "Analysis rendering")
    except AgentRuntimeContractError as exc:
        raise AnalysisArtifactRenderError(str(exc)) from exc
    encoded = selected["content"].encode("utf-8")
    if len(encoded) != selected["content_size_bytes"] or len(encoded) > MAX_RENDERED_BYTES:
        raise AnalysisArtifactRenderError("Analysis rendering byte count changed")
    content_sha256 = hashlib.sha256(encoded).hexdigest()
    if content_sha256 != selected["content_sha256"]:
        raise AnalysisArtifactRenderError("Analysis rendering content digest changed")
    if selected["binding_digest"] != _binding_digest(selected["source"], content_sha256):
        raise AnalysisArtifactRenderError("Analysis rendering source binding changed")
    return selected


def _render(artifact: Mapping[str, Any]) -> str:
    lines = [f"# {_markdown_text(artifact['title'])}", ""]
    renderers: dict[str, Callable[[Mapping[str, Any]], list[str]]] = {
        "overview": _overview,
        "semantics": _semantics,
        "findings": _findings,
        "hypotheses": _hypotheses,
        "claims": _claims,
        "recommendations": _recommendations,
        "limitations": _limitations,
        "evidence": _evidence,
    }
    for section in artifact["sections"]:
        lines.extend((f"## {section['title']}", ""))
        lines.extend(renderers[section["kind"]](artifact))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _overview(artifact: Mapping[str, Any]) -> list[str]:
    lines = [
        _field("Status", artifact["status"]),
        _field("Can run", artifact["can_run_status"]),
        _field("Visualization", artifact["visualization"]["intent"]),
        _field("Artifact schema", artifact["schema_version"]),
        _field("Renderer", "gravity.markdown@1"),
    ]
    if artifact["question"] is not None:
        lines.append(_field("Question", artifact["question"]))
    lines.append("- Scope filters:")
    scope = artifact["filters"]["values"]
    if not scope:
        lines.append("  - None")
    else:
        lines.extend(
            f"  - {_markdown_text(key)}: {_json_text(scope[key])}"
            for key in sorted(scope)
        )
    return lines


def _semantics(artifact: Mapping[str, Any]) -> list[str]:
    lines = _named_values("Metric URIs", artifact["metric_uris"])
    lines.extend(_named_values("Dimension URIs", artifact["dimension_uris"]))
    lines.append("- Semantic references:")
    references = artifact["semantic_references"]
    if not references:
        lines.append("  - None")
    else:
        lines.extend(
            f"  - {_markdown_text(item['uri'])} ({_markdown_text(item['status'])})"
            for item in references
        )
    return lines


def _findings(artifact: Mapping[str, Any]) -> list[str]:
    lines: list[str] = []
    findings = artifact["findings"]
    if not findings:
        lines.append("- None")
    for index, finding in enumerate(findings, 1):
        lines.append(f"- Finding {index}: {_markdown_text(finding['statement'])}")
        lines.append(f"  - Type: {_markdown_text(finding['finding_type'])}")
        lines.append(f"  - Evidence level: {_markdown_text(finding['evidence_level'])}")
        lines.append(f"  - Scope: {_json_text(finding['scope'])}")
        for reference in finding["fact_references"]:
            lines.append(
                f"  - Fact: {_markdown_text(reference['step_id'])} {_markdown_text(reference['path'])}"
            )
        for limitation in finding["limitations"]:
            lines.append(f"  - Limitation: {_markdown_text(limitation)}")
        for reference in finding["supporting_references"]:
            lines.append(
                f"  - Support: {_markdown_text(reference['kind'])} "
                f"{_markdown_text(reference['uri'])} {_markdown_text(reference['digest'])}"
            )
    lines.append("- Excluded factors:")
    lines.extend(_object_items(artifact["excluded_factors"], indent="  "))
    return lines


def _hypotheses(artifact: Mapping[str, Any]) -> list[str]:
    return _object_items(artifact["hypotheses"])


def _claims(artifact: Mapping[str, Any]) -> list[str]:
    lines = ["- Allowed claims:"]
    allowed = artifact["claims"]["allowed"]
    lines.extend(
        [
            f"  - {_markdown_text(item['claim_id'])}: {_markdown_text(item['statement'])}; "
            f"scope={_json_text(item['scope'])}"
            for item in allowed
        ]
        or ["  - None"]
    )
    lines.append("- Forbidden claims:")
    lines.extend(
        [f"  - {_markdown_text(item)}" for item in artifact["claims"]["forbidden"]]
        or ["  - None"]
    )
    return lines


def _recommendations(artifact: Mapping[str, Any]) -> list[str]:
    return _object_items(artifact["recommended_next_actions"])


def _limitations(artifact: Mapping[str, Any]) -> list[str]:
    return [f"- {_markdown_text(item)}" for item in artifact["limitations"]] or ["- None"]


def _evidence(artifact: Mapping[str, Any]) -> list[str]:
    evidence = artifact["evidence"]
    lines = [
        _field("Completeness", evidence["completeness"]),
        _field("Data quality", evidence["data_quality"].get("status")),
        _field("Evidence level", evidence["evidence_level"]),
        _field("Source network called", evidence["source_network_called"]),
        _field("Source Result digest", artifact["source"]["result_digest"]),
        _field("Execution snapshot digest", artifact["source"]["execution_snapshot_digest"]),
        _field("Analysis Artifact digest", artifact["artifact_digest"]),
    ]
    lines.extend(_named_values("Reason codes", artifact["reason_codes"]))
    lines.append("- Receipt references:")
    lines.extend(
        [
            f"  - {_markdown_text(item['receipt_id'])} ({_markdown_text(item['storage_status'])})"
            for item in evidence["receipt_references"]
        ]
        or ["  - None"]
    )
    lines.append("- Data quality checks:")
    lines.extend(
        [
            f"  - {_markdown_text(item['check_id'])}: {_markdown_text(item['status'])}; "
            f"scope={_markdown_text(item['scope'])}"
            for item in evidence["data_quality"].get("checks", [])
        ]
        or ["  - None"]
    )
    lines.extend(_named_values("Data quality reason codes", evidence["data_quality"].get("reason_codes", [])))
    lines.append("- Context references:")
    lines.extend(
        [
            f"  - {_markdown_text(item['requirement_uri'])} ({_markdown_text(item['status'])}); "
            f"pack={_markdown_text(item['pack_digest'] or 'none')}"
            for item in evidence["context_references"]
        ]
        or ["  - None"]
    )
    return lines


def _field(name: str, value: Any) -> str:
    return f"- {name}: {_markdown_text('none' if value is None else value)}"


def _named_values(name: str, values: Sequence[Any]) -> list[str]:
    lines = [f"- {name}:"]
    lines.extend([f"  - {_markdown_text(value)}" for value in values] or ["  - None"])
    return lines


def _object_items(values: Sequence[Mapping[str, Any]], *, indent: str = "") -> list[str]:
    return [f"{indent}- {_json_text(value)}" for value in values] or [f"{indent}- None"]


def _json_text(value: Any) -> str:
    try:
        rendered = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise AnalysisArtifactRenderError("Analysis rendering value is not canonical JSON") from exc
    return _markdown_text(rendered)


def _markdown_text(value: Any) -> str:
    flattened = " ".join(str(value).splitlines()).strip() or "none"
    escaped = html.escape(flattened, quote=False)
    return _MARKDOWN_CONTROL.sub(r"\\\1", escaped)


def _render_limit(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 < value <= MAX_RENDERED_BYTES:
        raise AnalysisArtifactRenderError("Markdown byte limit is invalid")
    return value


def _binding_digest(source: Mapping[str, Any], content_sha256: str) -> str:
    return canonical_digest({
        "schema_version": "gravity.analysis-rendering-binding.v1",
        "renderer": {"id": "gravity.markdown", "version": 1},
        "source": dict(source),
        "content_sha256": content_sha256,
    })


__all__ = [
    "AnalysisArtifactRenderError",
    "SCHEMA_VERSION",
    "render_analysis_artifact_markdown",
    "validate_analysis_rendering",
]
