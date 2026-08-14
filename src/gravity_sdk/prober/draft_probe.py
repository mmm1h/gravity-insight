"""Draft probe execution and immutable evidence persistence."""

from __future__ import annotations

import copy
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

from .core import DRAFT_ROOT, EVIDENCE_ROOT, canonical_fingerprint, write_json
from .privacy import build_projection, candidate_fields, response_schema_sketch
from .drafts import refresh_structured_blockers
from .parameters import apply_error_learning
from .probe_support import (
    assert_read_only_source, conclusion, contract_with_optional_required, evidence_path, family_id,
    last_primary, observation_summary, privacy_summary, probe_pagination,
    relative, request_stats, resolve_inputs, semantic_success,
)
from .promotion import evaluate_gate, save_draft
from .read_semantics import assert_probe_read_semantics
from .transport import HttpObservation, RecordingSession, build_draft_client


def _discover(
    source: Mapping[str, Any], stable_client: Any, runtime: Any,
    recording: RecordingSession, selected_family: str,
) -> tuple[
    Mapping[str, Any], Mapping[str, Any], Mapping[str, Any] | None,
    HttpObservation | None, list[dict[str, Any]],
]:
    parent_cache: dict[str, tuple[Any, dict[str, Any]]] = {}
    current = copy.deepcopy(dict(source))
    operation_id = str(source["operation"]["operation_id"])
    adjustments: list[dict[str, Any]] = []
    inputs: Mapping[str, Any] = {}
    discovery: HttpObservation | None = None
    for attempt in range(4):
        inputs = resolve_inputs(
            current["operation"].get("live_probe", {}).get("inputs", {}),
            source=current, stable_client=stable_client, recording=recording,
            parent_cache=parent_cache,
        )
        client = build_draft_client(current, runtime)
        purpose = "discovery" if attempt == 0 else f"parameter_retry_{attempt}"
        observation_start = len(recording.observations)
        error: Exception | None = None
        try:
            with recording.observing(operation_id, selected_family, purpose):
                client.read(operation_id, inputs)
        except (RuntimeError, ValueError, TypeError, OSError) as exc:
            error = exc
        discovery = last_primary(
            recording.observations[observation_start:], operation_id
        )
        if discovery is None:
            if error is not None:
                raise error
            break
        if (
            discovery.status_code < 200
            or discovery.status_code >= 300
            or semantic_success(discovery.payload)
            or attempt >= 3
        ):
            break
        learned, adjustment = apply_error_learning(
            current, discovery.payload, retry_index=attempt + 1
        )
        if adjustment is None:
            break
        current = learned
        adjustments.append(adjustment)
    parent_summaries = [item[1] for item in parent_cache.values()]
    if len(parent_summaries) == 1:
        parent_summary: Mapping[str, Any] | None = parent_summaries[0]
    elif parent_summaries:
        parent_summary = {"status": "resolved", "bindings": parent_summaries}
    else:
        parent_summary = None
    return current, inputs, parent_summary, discovery, adjustments


def _observed_contract(
    source: Mapping[str, Any], payload: Mapping[str, Any]
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    from .probe_support import pagination_from_payload

    sketch = response_schema_sketch(payload)
    fields = candidate_fields(
        sketch, operation_id=str(source["operation"]["operation_id"])
    )
    updated = copy.deepcopy(dict(source))
    data = payload.get("data")
    page_info = data.get("page_info") if isinstance(data, Mapping) else None
    if (
        isinstance(data, Mapping)
        and isinstance(data.get("list"), list)
        and isinstance(page_info, Mapping)
        and "page" in page_info
        and "page_size" in page_info
    ):
        operation = updated["operation"]
        operation["input_fields"].setdefault(
            "page", {"type": "integer", "default": 1}
        )
        operation["input_fields"].setdefault(
            "page_size", {"type": "integer", "default": 20}
        )
        _bind_observed_pagination(operation)
        operation["request"]["defaults"].setdefault("page", 1)
        operation["request"]["defaults"].setdefault("page_size", 20)
        operation["live_probe"]["inputs"].setdefault("page", 1)
        operation["live_probe"]["inputs"].setdefault("page_size", 20)
    pagination = pagination_from_payload(payload, updated["operation"])
    if pagination["kind"] == "page_info":
        operation = updated["operation"]
        default_page_size = int(pagination["default_page_size"])
        operation["input_fields"]["page"]["type"] = "integer"
        operation["input_fields"]["page"]["default"] = 1
        operation["input_fields"]["page_size"]["type"] = "integer"
        operation["input_fields"]["page_size"]["default"] = default_page_size
        operation["request"]["defaults"]["page"] = 1
        operation["request"]["defaults"]["page_size"] = default_page_size
        operation["live_probe"]["inputs"]["page"] = 1
        operation["live_probe"]["inputs"]["page_size"] = default_page_size
    updated["operation"]["response_projection"] = build_projection(payload, fields)
    updated["operation"]["pagination"] = pagination
    classifications = {
        str(item.get("privacy_classification")) for item in fields
    }
    domain = str(updated["operation"].get("domain", ""))
    if "sensitive" in classifications:
        privacy_classification = "user_level"
    elif "manual_review" in classifications:
        privacy_classification = "unverified"
    elif domain == "material":
        privacy_classification = "material"
    elif domain in {"metadata", "report"}:
        privacy_classification = "configuration"
    else:
        privacy_classification = "internal_business"
    updated["operation"]["privacy_policy"]["classification"] = privacy_classification
    return updated, pagination, fields, sketch


def _bind_observed_pagination(operation: dict[str, Any]) -> None:
    """Preserve an explicit pagination location and eliminate stale duplicates."""

    fields = {"page", "page_size"}
    request = operation["request"]
    query = set(request.get("query_fields", []))
    body = set(request.get("body_fields", []))
    query_complete = fields <= query
    body_complete = fields <= body
    if query_complete != body_complete:
        selected = "query_fields" if query_complete else "body_fields"
    else:
        selected = (
            "query_fields"
            if operation["upstream_method"] == "GET"
            else "body_fields"
        )
    other = "body_fields" if selected == "query_fields" else "query_fields"
    request[selected] = sorted(set(request.get(selected, [])) | fields)
    request[other] = sorted(set(request.get(other, [])) - fields)


def _bounded_pagination_inputs(
    source: Mapping[str, Any], inputs: Mapping[str, Any]
) -> dict[str, Any]:
    bounded = dict(inputs)
    pagination = source["operation"].get("pagination", {})
    if not isinstance(pagination, Mapping) or pagination.get("kind") != "page_info":
        return bounded
    page_field = str(pagination["page_field"])
    page_size_field = str(pagination["page_size_field"])
    default_page_size = int(pagination["default_page_size"])
    max_page_size = int(pagination["max_page_size"])
    bounded.setdefault(page_field, 1)
    page_size = bounded.get(page_size_field, default_page_size)
    if isinstance(page_size, (int, float)) and not isinstance(page_size, bool):
        bounded[page_size_field] = min(int(page_size), max_page_size)
    else:
        bounded[page_size_field] = default_page_size
    return bounded


def _verify_pagination(
    updated: Mapping[str, Any], inputs: Mapping[str, Any], runtime: Any,
    recording: RecordingSession, selected_family: str, discovery: HttpObservation | None,
) -> tuple[bool, dict[str, Any]]:
    pagination = updated["operation"]["pagination"]
    prior = next(
        (
            item for item in reversed(updated.get("draft", {}).get("probe_evidence", []))
            if item.get("pagination_verified") and item.get("path")
        ),
        None,
    )
    if pagination["kind"] != "none" and prior is not None:
        return True, {
            "kind": pagination["kind"], "verified_from": prior["path"],
            "total_field_path": f"data.page_info.{pagination['total_page_field']}",
            "upstream_hard_max": None,
        }
    verified = pagination["kind"] == "none"
    detail: dict[str, Any] = {
        "kind": pagination["kind"],
        "total_field_path": (
            f"data.page_info.{pagination['total_page_field']}"
            if pagination["kind"] != "none" else None
        ),
        "upstream_hard_max": None,
    }
    if pagination["kind"] != "none" and discovery and discovery.status_code < 400:
        client = build_draft_client(updated, runtime)
        verified, observed = probe_pagination(
            updated, inputs, client, recording, selected_family
        )
        detail.update(observed)
    return verified, detail


def _probe_missing_parameter(
    source: Mapping[str, Any], updated: Mapping[str, Any], inputs: Mapping[str, Any],
    runtime: Any, recording: RecordingSession, selected_family: str,
    discovery: HttpObservation | None,
) -> dict[str, Any]:
    required = [
        name for name, field in source["operation"].get("input_fields", {}).items()
        if isinstance(field, Mapping) and field.get("required") is True
    ]
    if not required or not discovery or discovery.status_code >= 500:
        return {"attempted": False, "shape_observed": False}
    missing_name = required[0]
    missing_source = contract_with_optional_required(updated, missing_name)
    client = build_draft_client(missing_source, runtime)
    missing_inputs = _bounded_pagination_inputs(updated, inputs)
    missing_inputs.pop(missing_name, None)
    start = len(recording.observations)
    try:
        with recording.observing(
            str(source["operation"]["operation_id"]), selected_family, "missing_parameter"
        ):
            client.read(str(source["operation"]["operation_id"]), missing_inputs)
    except Exception:
        pass
    primary = last_primary(
        recording.observations[start:], str(source["operation"]["operation_id"])
    )
    return {
        "attempted": True, "field": missing_name,
        "http_status": primary.status_code if primary else None,
        "shape_observed": primary is not None,
        "semantic_error_observed": bool(primary and not semantic_success(primary.payload)),
    }


def _confirm(
    updated: Mapping[str, Any], inputs: Mapping[str, Any], runtime: Any,
    recording: RecordingSession, selected_family: str,
) -> tuple[str, str | None]:
    operation_id = str(updated["operation"]["operation_id"])
    try:
        client = build_draft_client(updated, runtime)
        inputs = _bounded_pagination_inputs(updated, inputs)
        with recording.observing(operation_id, selected_family, "confirmation"):
            envelope = client.read(operation_id, inputs)
        if isinstance(envelope, Mapping):
            fingerprint = envelope.get("schema_fingerprint")
            return str(envelope.get("status", "error")), str(fingerprint) if fingerprint else None
    except Exception:
        pass
    return "error", None


def _evidence_document(
    source: Mapping[str, Any], observations: Sequence[HttpObservation], *,
    selected_family: str, result: str, successful: bool,
    raw_fingerprint: str | None, projected_fingerprint: str | None,
    pagination: Mapping[str, Any], pagination_verified: bool,
    missing_parameter: Mapping[str, Any], parent_summary: Mapping[str, Any] | None,
    fields: Sequence[Mapping[str, Any]],
    parameter_adjustments: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    return {
        "schema_version": "gravity-insight.probe-evidence.v1",
        "operation_id": str(source["operation"]["operation_id"]),
        "route": {
            "method": source["operation"]["upstream_method"],
            "path": source["operation"]["path_template"], "family": selected_family,
        },
        "probed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "conclusion": result, "successful": successful,
        "http": [observation_summary(item) for item in observations],
        "raw_schema_fingerprint": raw_fingerprint,
        "projected_schema_fingerprint": projected_fingerprint,
        "pagination": {**pagination, "verified": pagination_verified},
        "semantic_errors": {
            "rules": list(source["operation"].get("semantic_error_rules", [])),
            "missing_parameter": dict(missing_parameter),
            "parameter_adjustments": [dict(item) for item in parameter_adjustments],
            "permission_shape_observed": any(item.status_code == 403 for item in observations),
        },
        "required_parent": parent_summary, "privacy": privacy_summary(fields),
        "request_stats": request_stats(observations),
    }


def _method_verified(evidence: Mapping[str, Any]) -> bool:
    """A 2xx on the target route proves the method even when the body is empty.

    Neither a parent observation nor a non-2xx reply proves it: 405 means the
    upstream rejects this method outright.
    """

    if evidence.get("successful"):
        return True
    operation_id = evidence.get("operation_id")
    return any(
        item.get("operation_id") == operation_id
        and 200 <= int(item.get("http_status") or 0) < 300
        for item in evidence.get("http", [])
    )


def _persist_observed(
    updated: dict[str, Any], evidence: Mapping[str, Any], path: Path,
    fields: Sequence[Mapping[str, Any]], *, pagination_verified: bool,
    raw_fingerprint: str | None, projected_fingerprint: str | None,
    draft_root: Path,
) -> dict[str, Any]:
    write_json(path, evidence)
    parent_resolved = bool(
        not updated["operation"].get("required_parent")
        or (
            isinstance(evidence.get("required_parent"), Mapping)
            and evidence["required_parent"].get("status") == "resolved"
        )
    )
    reference = {
        "path": relative(path), "probed_at": evidence["probed_at"],
        "conclusion": evidence["conclusion"], "successful": evidence["successful"],
        "pagination_verified": pagination_verified,
        "parent_resolved": parent_resolved,
        "method_verified": _method_verified(evidence),
        "raw_schema_fingerprint": raw_fingerprint,
        "projected_schema_fingerprint": projected_fingerprint,
    }
    draft = updated["draft"]
    draft["candidate_fields"] = list(fields)
    draft["manual_review_fields"] = sorted(
        str(item["path"]) for item in fields
        if item["privacy_classification"] == "manual_review"
    )
    draft["probe_evidence"] = list(draft.get("probe_evidence", [])) + [reference]
    updated = refresh_structured_blockers(updated, draft.get("route_evidence"))
    draft = updated["draft"]
    draft["promotion_gate"] = evaluate_gate(updated)
    save_draft(updated, draft_root)
    return {
        "operation_id": evidence["operation_id"], "conclusion": evidence["conclusion"],
        "status": "draft", "eligible": draft["promotion_gate"]["eligible"],
        "missing": draft["promotion_gate"]["missing"], "evidence": relative(path),
    }


def _write_inconclusive_evidence(
    source: Mapping[str, Any], observations: Sequence[HttpObservation], *,
    result: str, error_type: str, parent_summary: Mapping[str, Any] | None,
    evidence_root: Path, draft_root: Path,
) -> dict[str, Any]:
    operation_id = str(source["operation"]["operation_id"])
    path = evidence_path(operation_id, evidence_root)
    summaries = [observation_summary(item) for item in observations]
    raw_fingerprint = summaries[-1]["raw_schema_fingerprint"] if summaries else None
    evidence = {
        "schema_version": "gravity-insight.probe-evidence.v1", "operation_id": operation_id,
        "route": {
            "method": source["operation"]["upstream_method"],
            "path": source["operation"]["path_template"], "family": family_id(source),
        },
        "probed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "conclusion": result, "successful": False, "http": summaries,
        "raw_schema_fingerprint": raw_fingerprint, "projected_schema_fingerprint": None,
        "pagination": {"verified": False, "kind": "unknown"},
        "semantic_errors": {
            "error_type": error_type,
            "permission_shape_observed": any(item.status_code == 403 for item in observations),
        },
        "required_parent": parent_summary, "privacy": privacy_summary([]),
        "request_stats": request_stats(observations),
    }
    write_json(path, evidence)
    updated = copy.deepcopy(dict(source))
    updated["draft"]["probe_evidence"] = list(updated["draft"].get("probe_evidence", [])) + [
        {
            "path": relative(path), "probed_at": evidence["probed_at"],
            "conclusion": result, "successful": False, "pagination_verified": False,
            "parent_resolved": False, "method_verified": False,
            "raw_schema_fingerprint": raw_fingerprint, "projected_schema_fingerprint": None,
        }
    ]
    updated = refresh_structured_blockers(
        updated, updated["draft"].get("route_evidence")
    )
    updated["draft"]["promotion_gate"] = evaluate_gate(updated)
    save_draft(updated, draft_root)
    return {
        "operation_id": operation_id, "conclusion": result, "status": "draft",
        "eligible": False, "missing": updated["draft"]["promotion_gate"]["missing"],
        "evidence": relative(path),
    }


def probe_draft(
    source: Mapping[str, Any], *, stable_client: Any, runtime: Any,
    recording: RecordingSession, evidence_root: Path = EVIDENCE_ROOT,
    draft_root: Path = DRAFT_ROOT,
) -> dict[str, Any]:
    assert_probe_read_semantics(source); assert_read_only_source(source)
    operation_id = str(source["operation"]["operation_id"])
    selected_family = family_id(source)
    start = len(recording.observations)
    try:
        learned_source, inputs, parent_summary, discovery, parameter_adjustments = _discover(
            source, stable_client, runtime, recording, selected_family
        )
    except (RuntimeError, ValueError, TypeError, OSError) as exc:
        observations = recording.observations[start:]
        primary = last_primary(observations, operation_id)
        result = conclusion(
            primary.status_code if primary else None,
            primary.payload if primary else None, None,
        )
        return _write_inconclusive_evidence(
            source, observations, result=result, error_type=type(exc).__name__,
            parent_summary=None, evidence_root=evidence_root, draft_root=draft_root,
        )
    payload = discovery.payload if discovery and isinstance(discovery.payload, Mapping) else {}
    updated, pagination, fields, sketch = _observed_contract(learned_source, payload)
    discovery_result = conclusion(
        discovery.status_code if discovery else None, payload, None
    )
    if discovery_result not in {"inconclusive", "inconclusive_empty"}:
        raw_fingerprint = canonical_fingerprint(sketch) if discovery else None
        evidence = _evidence_document(
            updated, recording.observations[start:], selected_family=selected_family,
            result=discovery_result, successful=False,
            raw_fingerprint=raw_fingerprint, projected_fingerprint=None,
            pagination={"kind": pagination["kind"]},
            pagination_verified=pagination["kind"] == "none",
            missing_parameter={"attempted": False, "shape_observed": False},
            parent_summary=parent_summary, fields=fields,
            parameter_adjustments=parameter_adjustments,
        )
        return _persist_observed(
            updated, evidence, evidence_path(operation_id, evidence_root), fields,
            pagination_verified=pagination["kind"] == "none",
            raw_fingerprint=raw_fingerprint, projected_fingerprint=None,
            draft_root=draft_root,
        )
    verified, pagination_detail = _verify_pagination(
        updated, inputs, runtime, recording, selected_family, discovery
    )
    if discovery_result == "inconclusive_empty":
        raw_fingerprint = canonical_fingerprint(sketch) if discovery else None
        evidence = _evidence_document(
            updated, recording.observations[start:], selected_family=selected_family,
            result=discovery_result, successful=False,
            raw_fingerprint=raw_fingerprint, projected_fingerprint=None,
            pagination=pagination_detail, pagination_verified=verified,
            missing_parameter={"attempted": False, "shape_observed": False},
            parent_summary=parent_summary, fields=fields,
            parameter_adjustments=parameter_adjustments,
        )
        return _persist_observed(
            updated, evidence, evidence_path(operation_id, evidence_root), fields,
            pagination_verified=verified, raw_fingerprint=raw_fingerprint,
            projected_fingerprint=None, draft_root=draft_root,
        )
    missing = _probe_missing_parameter(
        learned_source, updated, inputs, runtime, recording, selected_family, discovery
    )
    confirmed_status, projected_fingerprint = _confirm(
        updated, inputs, runtime, recording, selected_family
    )
    result = conclusion(discovery.status_code if discovery else None, payload, confirmed_status)
    observations = recording.observations[start:]
    raw_fingerprint = canonical_fingerprint(sketch) if discovery else None
    evidence = _evidence_document(
        updated, observations, selected_family=selected_family, result=result,
        successful=result == "success", raw_fingerprint=raw_fingerprint,
        projected_fingerprint=projected_fingerprint, pagination=pagination_detail,
        pagination_verified=verified, missing_parameter=missing,
        parent_summary=parent_summary, fields=fields,
        parameter_adjustments=parameter_adjustments,
    )
    return _persist_observed(
        updated, evidence, evidence_path(operation_id, evidence_root), fields,
        pagination_verified=verified, raw_fingerprint=raw_fingerprint,
        projected_fingerprint=projected_fingerprint, draft_root=draft_root,
    )
