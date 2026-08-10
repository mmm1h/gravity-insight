"""Controlled online probing through the public Gravity Insight client API."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

from .core import DRAFT_ROOT, EVIDENCE_ROOT, OPERATION_ROOT, read_json
from .draft_probe import probe_draft
from .stable_probe import probe_stable
from .transport import (
    HttpObservation,
    RecordingSession,
    RequestContext,
    RequestDiscipline,
    build_runtime,
    sdk_parts,
)


def _session_or_default(session: Any | None) -> Any:
    if session is not None:
        return session
    try:
        import requests
    except ImportError as exc:
        raise RuntimeError("requests is required for online Gravity probing") from exc
    return requests.Session()


def _probe_one_draft(
    operation_id: str, *, draft_root: Path, stable_client: Any, runtime: Any,
    recording: RecordingSession, evidence_root: Path,
) -> dict[str, Any]:
    path = draft_root / f"{operation_id}.json"
    source = read_json(path)
    if not isinstance(source, Mapping):
        raise ValueError(f"invalid draft source: {operation_id}")
    return probe_draft(
        source, stable_client=stable_client, runtime=runtime, recording=recording,
        evidence_root=evidence_root, draft_root=draft_root,
    )


def run_online_probes(
    operation_ids: Sequence[str], *, stable: bool = False,
    interval_seconds: float = 0.31, request_limit: int = 200,
    draft_root: Path = DRAFT_ROOT, operation_root: Path = OPERATION_ROOT,
    evidence_root: Path = EVIDENCE_ROOT, session: Any | None = None,
) -> dict[str, Any]:
    if not operation_ids:
        raise ValueError("probe requires at least one operation_id")
    if len(operation_ids) > 12:
        raise ValueError("one probe command accepts at most 12 operations")
    discipline = RequestDiscipline(
        interval_seconds=interval_seconds, request_limit=request_limit
    )
    recording = RecordingSession(_session_or_default(session), discipline)
    runtime = build_runtime(recording)
    parts = sdk_parts()
    stable_client = parts["GravityInsightClient"].from_env(
        runtime=runtime, timeout=120.0, attempts=1
    )
    results: list[dict[str, Any]] = []
    for operation_id in operation_ids:
        if stable:
            result = probe_stable(
                operation_id, stable_client=stable_client, recording=recording,
                evidence_root=evidence_root, operation_root=operation_root,
            )
        else:
            result = _probe_one_draft(
                operation_id, draft_root=draft_root, stable_client=stable_client,
                runtime=runtime, recording=recording, evidence_root=evidence_root,
            )
        results.append(result)
    accepted = {"success", "available_empty"}
    return {
        "schema_version": "gravity-insight.prober-run.v1", "ok": True,
        "status": "success" if all(item["conclusion"] in accepted for item in results) else "partial",
        "results": results,
        "request_stats": {
            "total": discipline.total, "failed": discipline.failed,
            "backoff_terminations": discipline.backoff_terminations,
            "request_limit": discipline.request_limit,
            "minimum_interval_ms": int(discipline.interval_seconds * 1000),
        },
    }


__all__ = [
    "HttpObservation", "RecordingSession", "RequestContext", "RequestDiscipline",
    "probe_draft", "probe_stable", "run_online_probes",
]
