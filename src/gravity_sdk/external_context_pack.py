"""Exact R08 reads aligned and assembled by the R07 Context Broker."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from datetime import date
from typing import Any

from .context_alignment import authority_allowed, context_freshness, normalize_windows, resolve_entities
from .context_broker import ContextPackBroker
from .context_contract import ContextContractError, date_range_contains, time_range_contains, validate_context_item


def assemble_external_context_pack(
    requirement_artifact: Mapping[str, Any],
    provider_artifact: Mapping[str, Any],
    injected: Mapping[str, Any] | None,
    *,
    aliases: Mapping[str, str],
    requested_time: Mapping[str, Mapping[str, str]],
) -> tuple[dict[str, Any], bool]:
    requirement = requirement_artifact["contract"]
    windows = _requested_windows(requirement, requested_time)
    resolved_subjects, subject_gaps = resolve_entities(requirement["subject_entities"], aliases)
    candidates, called = _provider_candidates(requirement, provider_artifact, injected)
    candidates, source_revision = _consistent_revision(candidates, requirement_artifact["digest"])
    broker = ContextPackBroker(
        _broker_requirement(requirement),
        requirement_digest=requirement_artifact["digest"],
        provider=provider_artifact,
        source_revision=source_revision,
        subject_gaps=subject_gaps,
        provider_audit=_provider_audit(called),
    )
    declarations = {item["item_id"]: item for item in requirement["resources"]}
    subjects = set(resolved_subjects)
    for candidate in candidates:
        if candidate["status"] == "available":
            candidate = _aligned_candidate(
                candidate["item"], declarations[candidate["item_id"]], requirement,
                windows, subjects, aliases, broker.budget,
            )
        broker.add(candidate)
    broker.apply_supersession()
    broker.apply_authority_conflicts()
    return broker.render(
        subject_entities=requirement["subject_entities"],
        resolved_entities=resolved_subjects,
        requested_time=windows,
    ), called


def _requested_windows(
    requirement: Mapping[str, Any], requested_time: Mapping[str, Mapping[str, str]]
) -> dict[str, dict[str, str]]:
    selected = {
        name: {**copy.deepcopy(requested_time[name]), "timezone": requirement["timezone"]}
        for name in requirement["required_windows"]
        if name in requested_time
    }
    return normalize_windows(selected, requirement["required_windows"])


def _provider_candidates(
    requirement: Mapping[str, Any],
    provider_artifact: Mapping[str, Any],
    injected: Mapping[str, Any] | None,
) -> tuple[list[dict[str, Any]], bool]:
    if injected is None or injected["digest"] != provider_artifact["digest"]:
        reason = "CONTEXT_PROVIDER_MISSING" if injected is None else "PROVIDER_DESCRIPTOR_MISMATCH"
        return [
            _gap(item["item_id"], "missing", reason)
            for item in requirement["resources"]
        ], False
    candidates: list[dict[str, Any]] = []
    called = False
    for declaration in requirement["resources"]:
        result = injected["provider"].read(declaration["resource_uri"])
        called = called or bool(result["provider_rpc_called"])
        candidates.append(_provider_candidate(declaration, result))
    return candidates, called


def _consistent_revision(
    candidates: list[dict[str, Any]], requirement_digest: str
) -> tuple[list[dict[str, Any]], str]:
    revisions = {
        candidate["item"]["source_revision"]
        for candidate in candidates
        if candidate["status"] == "available"
    }
    if len(revisions) <= 1:
        revision = next(iter(revisions)) if revisions else f"binding:{requirement_digest[:16]}"
        return candidates, revision
    changed = [
        _gap(candidate["item_id"], "stale", "CONTEXT_SNAPSHOT_CHANGED")
        if candidate["status"] == "available" else candidate
        for candidate in candidates
    ]
    return changed, f"binding:{requirement_digest[:16]}"


def _broker_requirement(requirement: Mapping[str, Any]) -> dict[str, Any]:
    selected = copy.deepcopy(dict(requirement))
    selected["items"] = [
        {"item_id": item["item_id"], "required": item["required"]}
        for item in requirement["resources"]
    ]
    selected.pop("resources", None)
    return selected


def _provider_audit(called: bool) -> dict[str, Any]:
    return {
        "provider_rpc_called": called,
        "provider_internal_io_controlled": False,
        "provider_internal_network": "not_observable",
    }


def _provider_candidate(
    declaration: Mapping[str, Any], result: Mapping[str, Any]
) -> dict[str, Any]:
    if not result["ok"]:
        reason = result["reason_codes"][0] if result["reason_codes"] else "CONTEXT_REQUIRED_MISSING"
        return _gap(declaration["item_id"], _gap_status(reason), reason)
    items = result["context_items"]
    exact = (
        len(items) == 1
        and items[0]["uri"] == declaration["resource_uri"]
        and items[0]["item_id"] == declaration["item_id"]
    )
    if not exact:
        return _gap(declaration["item_id"], "unsupported", "CONTEXT_ALIGNMENT_UNSUPPORTED")
    return {"item_id": declaration["item_id"], "status": "available", "item": copy.deepcopy(items[0])}


def _aligned_candidate(
    item: Mapping[str, Any], declaration: Mapping[str, Any],
    requirement: Mapping[str, Any], windows: Mapping[str, Mapping[str, str]],
    subjects: set[str], aliases: Mapping[str, str], budget: Mapping[str, Any],
) -> dict[str, Any]:
    resolved, gaps = resolve_entities(item["entity_refs"], aliases)
    alignment = _alignment_gap(item, windows, subjects, resolved, bool(gaps))
    if alignment is not None:
        return _gap(item["item_id"], *alignment)
    policy = _policy_gap(item, requirement)
    if policy is not None:
        return _gap(item["item_id"], *policy)
    encoded = item["content"].encode("utf-8")
    lines = item["content"].splitlines()
    if _budget_exceeded(encoded, lines, requirement["budget"], budget):
        return _gap(item["item_id"], "unsupported", "CONTEXT_RESOURCE_LIMIT")
    normalized = copy.deepcopy(dict(item))
    normalized["resolved_entity_refs"] = resolved
    normalized["freshness"] = "current"
    try:
        normalized = validate_context_item(normalized)
    except ContextContractError:
        return _gap(declaration["item_id"], "unsupported", "CONTEXT_ALIGNMENT_UNSUPPORTED")
    return {
        "item_id": declaration["item_id"], "status": "available", "item": normalized,
        "size_bytes": len(encoded), "line_count": max(1, len(lines)),
    }


def _alignment_gap(
    item: Mapping[str, Any], windows: Mapping[str, Mapping[str, str]],
    subjects: set[str], resolved: list[str], has_entity_gaps: bool,
) -> tuple[str, str] | None:
    if has_entity_gaps or not resolved or not subjects.issuperset(resolved):
        return "unsupported", "CONTEXT_ENTITY_UNALIGNED"
    aligned = all(
        time_range_contains(
            item["valid_time"], date.fromisoformat(window["start"]),
            date.fromisoformat(window["end"]), window["timezone"],
        )
        and date_range_contains(
            item["effective_range"], date.fromisoformat(window["start"]),
            date.fromisoformat(window["end"]),
        )
        for window in windows.values()
    )
    return None if aligned else ("unsupported", "CONTEXT_ENTITY_TIME_MISMATCH")


def _policy_gap(
    item: Mapping[str, Any], requirement: Mapping[str, Any]
) -> tuple[str, str] | None:
    if item["sensitivity"] == "restricted" or item["sensitivity"] not in requirement["allowed_sensitivity"]:
        return "denied", "CONTEXT_SENSITIVITY_DENIED"
    if not authority_allowed(item["authority"], requirement["authority_policy"]):
        return "denied", "CONTEXT_AUTHORITY_DENIED"
    stale = item["freshness"] == "stale" or context_freshness(
        {"max_age_days": None}, requirement, item["observed_at"]
    ) == "stale"
    return ("stale", "CONTEXT_STALE") if stale else None


def _budget_exceeded(
    encoded: bytes, lines: list[str], limit: Mapping[str, Any], used: Mapping[str, Any]
) -> bool:
    return (
        len(encoded) > limit["max_file_bytes"]
        or used["used_files"] + 1 > used["max_files"]
        or used["used_bytes"] + len(encoded) > used["max_total_bytes"]
        or used["used_lines"] + len(lines) > used["max_total_lines"]
    )


def _gap(item_id: str, status: str, reason: str) -> dict[str, Any]:
    return {"item_id": item_id, "status": status, "reason_code": reason}


def _gap_status(reason: str) -> str:
    if reason in {"PROVIDER_RESOURCE_DENIED", "CONTEXT_SENSITIVITY_DENIED"}:
        return "denied"
    if reason in {"CONTEXT_SNAPSHOT_CHANGED", "CONTEXT_STALE"}:
        return "stale"
    return "missing" if reason in _MISSING_REASONS else "unsupported"


_MISSING_REASONS = {
    "CONTEXT_PROVIDER_MISSING", "CONTEXT_REQUIRED_MISSING", "PROVIDER_RPC_UNAVAILABLE",
    "PROVIDER_RPC_TIMEOUT", "PROVIDER_RPC_CANCELLED", "PROVIDER_RPC_BUSY",
    "PROVIDER_RPC_CALL_LIMIT", "PROVIDER_CIRCUIT_OPEN",
}


__all__ = ["assemble_external_context_pack"]
