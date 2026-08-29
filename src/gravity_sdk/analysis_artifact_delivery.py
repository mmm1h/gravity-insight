"""Atomic local publication for Analysis Artifact JSON and Markdown."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .agent_runtime_contracts import AgentRuntimeContractError, canonical_digest, validate_schema
from .analysis_artifact import MAX_ARTIFACT_BYTES, validate_analysis_artifact
from .analysis_artifact_markdown import render_analysis_artifact_markdown
from .result_output import write_rendered_result


SCHEMA_VERSION = "gravity.analysis-delivery.v1"
_SCHEMA_NAME = "analysis-delivery-v1.schema.json"


class AnalysisDeliveryError(AgentRuntimeContractError):
    """A local Analysis Artifact delivery request is unsafe or inconsistent."""


def write_analysis_artifact(
    value: Mapping[str, Any], destination: str | Path
) -> dict[str, Any]:
    artifact = validate_analysis_artifact(value)
    path = _destination(destination, (".json",))
    rendered = json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n"
    return _write(
        rendered,
        path,
        artifact,
        output_format="json",
        media_type="application/json",
        maximum=MAX_ARTIFACT_BYTES,
    )


def write_analysis_markdown(
    value: Mapping[str, Any],
    destination: str | Path,
    *,
    max_bytes: int,
) -> dict[str, Any]:
    artifact = validate_analysis_artifact(value)
    rendering = render_analysis_artifact_markdown(artifact, max_bytes=max_bytes)
    path = _destination(destination, (".md", ".markdown"))
    return _write(
        rendering["content"],
        path,
        artifact,
        output_format="markdown",
        media_type="text/markdown",
        maximum=max_bytes,
    )


def validate_analysis_delivery(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise AnalysisDeliveryError("Analysis delivery receipt must be an object")
    selected = dict(value)
    try:
        validate_schema(selected, _SCHEMA_NAME, "Analysis delivery")
    except AgentRuntimeContractError as exc:
        raise AnalysisDeliveryError(str(exc)) from exc
    expected = _delivery_binding(
        selected["format"],
        selected["source_result_digest"],
        selected["source_artifact_digest"],
        selected["receipt_references_digest"],
        selected["content_sha256"],
    )
    if selected["binding_digest"] != expected:
        raise AnalysisDeliveryError("Analysis delivery binding changed")
    return selected


def _write(
    rendered: str,
    destination: Path,
    artifact: Mapping[str, Any],
    *,
    output_format: str,
    media_type: str,
    maximum: int,
) -> dict[str, Any]:
    encoded = rendered.encode("utf-8")
    if not encoded or len(encoded) > maximum:
        raise AnalysisDeliveryError("Analysis delivery output exceeds its byte limit")
    content_sha256 = hashlib.sha256(encoded).hexdigest()
    receipt = write_rendered_result(str(destination), rendered, output_format=output_format)
    result = {
        "schema_version": SCHEMA_VERSION,
        "ok": True,
        "status": "written",
        "format": output_format,
        "media_type": media_type,
        "output": receipt["output"],
        "source_result_digest": artifact["source"]["result_digest"],
        "source_artifact_digest": artifact["artifact_digest"],
        "receipt_references_digest": artifact["source"]["receipt_references_digest"],
        "content_sha256": content_sha256,
        "binding_digest": _delivery_binding(
            output_format,
            artifact["source"]["result_digest"],
            artifact["artifact_digest"],
            artifact["source"]["receipt_references_digest"],
            content_sha256,
        ),
        "size_bytes": len(encoded),
        "network_called": False,
    }
    return validate_analysis_delivery(result)


def _destination(value: str | Path, extensions: tuple[str, ...]) -> Path:
    try:
        path = Path(value)
    except (TypeError, ValueError) as exc:
        raise AnalysisDeliveryError("Analysis delivery destination is invalid") from exc
    if not str(path).strip() or str(path) == "-" or path.suffix.casefold() not in extensions:
        raise AnalysisDeliveryError("Analysis delivery destination has the wrong extension")
    return path


def _delivery_binding(
    output_format: str,
    result_digest: str,
    artifact_digest: str,
    receipt_references_digest: str,
    content_sha256: str,
) -> str:
    return canonical_digest({
        "schema_version": "gravity.analysis-delivery-binding.v1",
        "format": output_format,
        "result_digest": result_digest,
        "artifact_digest": artifact_digest,
        "receipt_references_digest": receipt_references_digest,
        "content_sha256": content_sha256,
    })


__all__ = [
    "AnalysisDeliveryError",
    "SCHEMA_VERSION",
    "validate_analysis_delivery",
    "write_analysis_artifact",
    "write_analysis_markdown",
]
