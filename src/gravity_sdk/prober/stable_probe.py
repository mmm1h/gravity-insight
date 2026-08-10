"""Read-only drift probes for existing stable operations."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Mapping

from .core import EVIDENCE_ROOT, OPERATION_ROOT, canonical_fingerprint, read_json, write_json
from .privacy import candidate_fields, response_schema_sketch
from .probe_support import (
    assert_read_only_source, conclusion, last_primary, observation_summary, privacy_summary, relative,
    request_stats, semantic_success,
)
from .transport import RecordingSession


def _operation_source(operation_id: str, operation_root: Path) -> Mapping[str, Any]:
    path = operation_root / f"{operation_id}.json"
    if not path.is_file():
        raise ValueError(f"unknown stable operation: {operation_id}")
    value = read_json(path)
    if not isinstance(value, Mapping):
        raise ValueError(f"invalid stable operation source: {operation_id}")
    return value


def probe_stable(
    operation_id: str, *, stable_client: Any, recording: RecordingSession,
    evidence_root: Path = EVIDENCE_ROOT, operation_root: Path = OPERATION_ROOT,
) -> dict[str, Any]:
    from .probe_support import evidence_path

    source = _operation_source(operation_id, operation_root)
    assert_read_only_source(source)
    family = str(source["operation"].get("provenance", {}).get("family") or operation_id)
    start = len(recording.observations)
    confirmed_status = "error"
    try:
        with recording.observing(operation_id, family, "stable_drift_probe"):
            envelope = stable_client.probe(operation_id)
        if isinstance(envelope, Mapping):
            confirmed_status = str(envelope.get("status", "error"))
    except Exception:
        pass
    observations = recording.observations[start:]
    primary = last_primary(observations, operation_id)
    payload = primary.payload if primary else None
    result = conclusion(primary.status_code if primary else None, payload, confirmed_status)
    if result == "inconclusive_empty" and semantic_success(payload):
        result = "available_empty"
    sketch = response_schema_sketch(payload)
    fields = candidate_fields(sketch)
    path = evidence_path(operation_id, evidence_root)
    evidence = {
        "schema_version": "gravity-insight.probe-evidence.v1", "operation_id": operation_id,
        "route": {
            "method": source["operation"]["upstream_method"],
            "path": source["operation"]["path_template"], "family": family,
        },
        "probed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "conclusion": result, "successful": result in {"success", "available_empty"},
        "http": [observation_summary(item) for item in observations],
        "raw_schema_fingerprint": canonical_fingerprint(sketch) if primary else None,
        "projected_schema_fingerprint": None,
        "pagination": {
            "verified": confirmed_status in {"success", "empty"},
            "kind": source["operation"].get("pagination", {}).get("kind", "none"),
        },
        "semantic_errors": {
            "permission_shape_observed": any(item.status_code == 403 for item in observations)
        },
        "required_parent": None, "privacy": privacy_summary(fields),
        "request_stats": request_stats(observations),
    }
    write_json(path, evidence)
    return {
        "operation_id": operation_id, "conclusion": result,
        "status": str(source["operation"].get("stability")), "evidence": relative(path),
    }
