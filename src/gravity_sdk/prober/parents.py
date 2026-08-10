"""Resolve parent-resource blockers and persist value-free conclusions."""

from __future__ import annotations

import copy
import re
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

try:
    from gravity_sdk.parent_resolution import (
        resolve_declared_parents,
    )
except ModuleNotFoundError:
    from gravity_sdk.parent_resolution import (
        resolve_declared_parents,
    )

from .core import DRAFT_ROOT, EVIDENCE_ROOT, read_json, write_json
from .drafts import refresh_structured_blockers
from .parameters import bind_stable_parent_candidates
from .probe_support import evidence_path, family_id, observation_summary, relative
from .promotion import evaluate_gate, save_draft
from .transport import RecordingSession


_NO_PARENT_PROOF_CONCLUSIONS = {
    "available_empty",
    "inconclusive_empty",
    "privacy_review_required",
    "success",
}
_PARENT_FIELD_RE = re.compile(r"(?:^|_)(?:id|ids)$", re.IGNORECASE)


def _unbound_parent_fields(source: Mapping[str, Any]) -> list[str]:
    operation = source.get("operation", {})
    fields = operation.get("input_fields", {})
    parents = operation.get("required_parent", [])
    bound = {
        str(item.get("input_field"))
        for item in parents
        if isinstance(item, Mapping) and item.get("input_field")
    }
    return sorted(
        str(name)
        for name in fields
        if _PARENT_FIELD_RE.search(str(name)) and str(name) not in bound
    ) if isinstance(fields, Mapping) else []


def _description(source: Mapping[str, Any]) -> dict[str, Any]:
    operation = source["operation"]
    return {
        "operation_id": operation["operation_id"],
        "input_schema": operation.get("input_fields", {}),
        "required_parent": [
            {
                "operation_id": item.get("operation_id"),
                "output_path": item.get("output_path"),
                "selection": item.get("selection"),
                "target_input": item.get("input_field"),
            }
            for item in operation.get("required_parent", [])
            if isinstance(item, Mapping)
        ],
    }


def _latest_reference(source: Mapping[str, Any]) -> Mapping[str, Any]:
    references = source.get("draft", {}).get("probe_evidence", [])
    if isinstance(references, list) and references and isinstance(references[-1], Mapping):
        return references[-1]
    return {}


def _value_free_bindings(bindings: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    allowed = {
        "parent_operation_id",
        "output_path",
        "target_input",
        "target_cardinality",
        "selection",
        "status",
        "candidate_count",
        "candidate_types",
    }
    return [
        {name: item[name] for name in allowed if name in item}
        for item in bindings
    ]


def _offline_resolution(source: Mapping[str, Any]) -> dict[str, Any]:
    operation = source.get("operation", {})
    unbound_fields = _unbound_parent_fields(source)
    path_segments = {
        segment.casefold()
        for segment in str(operation.get("path_template", "")).split("/")
        if segment
    }
    probe_inputs = operation.get("live_probe", {}).get("inputs", {})
    ambiguous_controls = {
        str(name)
        for name in probe_inputs
        if str(name).casefold() in {"operate", "operation", "action"}
    } if isinstance(probe_inputs, Mapping) else set()
    if "manage" in path_segments or ambiguous_controls:
        return {
            "conclusion": "undetermined",
            "basis": "read_semantics_unproven",
            "detail": "Parent probing is withheld because the current route shape does not prove read-only semantics.",
            "bindings": [],
            "source_evidence": None,
            "missing_evidence": [
                "A read-only request contract for the manage/operate route before any further live probe."
            ],
        }
    latest = _latest_reference(source)
    conclusion = str(latest.get("conclusion", ""))
    if unbound_fields:
        return {
            "conclusion": "undetermined",
            "basis": "unbound_parent_fields",
            "detail": (
                "A child response exists, but parent-shaped input fields remain "
                "unbound: " + ", ".join(unbound_fields) + "."
            ),
            "bindings": [],
            "source_evidence": latest.get("path"),
            "missing_evidence": [
                "A proven parent operation and output path for: "
                + ", ".join(unbound_fields)
                + "."
            ],
        }
    if conclusion in _NO_PARENT_PROOF_CONCLUSIONS:
        return {
            "conclusion": "unblocked",
            "basis": "child_semantic_success_without_parent",
            "detail": "The child route returned a semantic success without a parent selector; no parent binding is required.",
            "bindings": [],
            "source_evidence": latest.get("path"),
            "missing_evidence": [],
        }
    return {
        "conclusion": "undetermined",
        "basis": "no_proven_binding",
        "detail": "No declared parent binding exists and the child has not returned a semantic success without one.",
        "bindings": [],
        "source_evidence": latest.get("path"),
        "missing_evidence": [
            "A frontend request binding, a semantic error naming the parent field, or a successful child request without a parent selector."
        ],
    }


def _online_resolution(
    source: Mapping[str, Any], stable_client: Any, recording: RecordingSession,
    cache: dict[str, Any], errors: dict[str, Exception],
) -> dict[str, Any]:
    unbound_fields = _unbound_parent_fields(source)
    def probe(operation_id: str) -> Mapping[str, Any]:
        if operation_id in errors:
            raise errors[operation_id]
        if operation_id not in cache:
            try:
                with recording.observing(
                    operation_id, family_id(source), "parent_resolution"
                ):
                    cache[operation_id] = stable_client.probe(operation_id)
            except Exception as exc:
                errors[operation_id] = exc
                raise
        return cache[operation_id]

    result = resolve_declared_parents(_description(source), probe)
    status = str(result["status"])
    if unbound_fields:
        conclusion, replacement = "undetermined", None
        detail = (
            "Declared parent probes were not enough to bind every parent-shaped "
            "input field: " + ", ".join(unbound_fields) + "."
        )
        missing = [
            "A proven parent operation and output path for: "
            + ", ".join(unbound_fields)
            + "."
        ]
    elif status == "resolved":
        conclusion, replacement = "unblocked", None
        detail = "Every declared parent binding yielded a selectable value; values stayed in process memory."
        missing: list[str] = []
    elif status in {"empty", "permission_unavailable"}:
        conclusion = "blocked_by_data"
        replacement = (
            "permission_unavailable"
            if status == "permission_unavailable"
            else "empty_sample"
        )
        detail = "The binding is declared and typed, but the current account cannot supply a selectable parent value."
        missing = []
    else:
        conclusion, replacement = "undetermined", None
        detail = "At least one declared stable parent did not produce a readable candidate response."
        missing = [
            "A successful or explicit permission response from every declared parent operation."
        ]
    return {
        "conclusion": conclusion,
        "basis": "declared_parent_probe",
        "detail": detail,
        "replacement_blocker": replacement,
        "bindings": _value_free_bindings(result["bindings"]),
        "source_evidence": None,
        "missing_evidence": missing,
    }


def _evidence_document(
    source: Mapping[str, Any], resolution: Mapping[str, Any],
    observations: Sequence[Any],
) -> dict[str, Any]:
    operation = source["operation"]
    return {
        "schema_version": "gravity-insight.parent-resolution-evidence.v1",
        "operation_id": operation["operation_id"],
        "route": {
            "method": operation["upstream_method"],
            "path": operation["path_template"],
        },
        "resolved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "conclusion": resolution["conclusion"],
        "basis": resolution["basis"],
        "detail": resolution["detail"],
        "replacement_blocker": resolution.get("replacement_blocker"),
        "bindings": list(resolution["bindings"]),
        "source_evidence": resolution.get("source_evidence"),
        "missing_evidence": list(resolution.get("missing_evidence", [])),
        "http": [observation_summary(item) for item in observations],
        "values_persisted": False,
    }


def resolve_parent_blockers(
    *, stable_client: Any, recording: RecordingSession,
    operation_ids: Sequence[str] = (), draft_root: Path = DRAFT_ROOT,
    evidence_root: Path = EVIDENCE_ROOT,
) -> dict[str, Any]:
    selected = set(operation_ids)
    bind_stable_parent_candidates(
        draft_root=draft_root, operation_ids=operation_ids
    )
    paths = sorted(draft_root.glob("*.json"))
    cache: dict[str, Any] = {}
    errors: dict[str, Exception] = {}
    rows: list[dict[str, Any]] = []
    for path in paths:
        source = read_json(path)
        operation_id = str(source.get("operation", {}).get("operation_id", path.stem))
        if selected and operation_id not in selected:
            continue
        blocker_codes = {
            str(item.get("code"))
            for item in source.get("draft", {}).get("blockers", [])
            if isinstance(item, Mapping)
        }
        if "parent_resource_required" not in blocker_codes and not selected:
            continue
        start = len(recording.observations)
        if source["operation"].get("required_parent"):
            resolution = _online_resolution(
                source, stable_client, recording, cache, errors
            )
        else:
            resolution = _offline_resolution(source)
        evidence = _evidence_document(
            source, resolution, recording.observations[start:]
        )
        output = evidence_path(operation_id, evidence_root)
        write_json(output, evidence)
        updated = copy.deepcopy(source)
        stored = {
            "conclusion": resolution["conclusion"],
            "basis": resolution["basis"],
            "detail": resolution["detail"],
            "evidence": relative(output),
            "replacement_blocker": resolution.get("replacement_blocker"),
            "bindings": list(resolution["bindings"]),
            "missing_evidence": list(resolution.get("missing_evidence", [])),
        }
        updated["draft"]["route_evidence"]["parent_resolution"] = stored
        updated = refresh_structured_blockers(
            updated, updated["draft"].get("route_evidence")
        )
        updated["draft"]["promotion_gate"] = evaluate_gate(updated)
        save_draft(updated, draft_root)
        rows.append(
            {
                "operation_id": operation_id,
                "conclusion": resolution["conclusion"],
                "replacement_blocker": resolution.get("replacement_blocker"),
                "evidence": relative(output),
            }
        )
    counts = {
        name: sum(item["conclusion"] == name for item in rows)
        for name in ("unblocked", "blocked_by_data", "undetermined")
    }
    return {
        "schema_version": "gravity-insight.parent-resolution-run.v1",
        "ok": True,
        "status": "success",
        "count": len(rows),
        "conclusions": counts,
        "operations": rows,
        "request_stats": {
            "total": recording.discipline.total,
            "failed": recording.discipline.failed,
        },
    }


__all__ = ["resolve_parent_blockers"]
