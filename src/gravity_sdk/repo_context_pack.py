"""Entity/time/authority aligned assembly of explicit Repo Context Requirements."""

from __future__ import annotations

import copy
import hashlib
from datetime import date
from pathlib import Path
from typing import Any, Mapping, Sequence

from .context_alignment import (
    authority_allowed as _authority_allowed,
    context_freshness as _freshness,
    normalize_windows as _windows,
    resolve_entities as _resolved_entities,
)
from .context_broker import ContextPackBroker
from .context_contract import (
    ContextContractError,
    ITEM_SCHEMA_VERSION,
    compile_context_requirement,
    date_range_contains,
    time_range_contains,
    validate_context_item,
)
from .repo_context_index import assert_clean_paths, git_snapshot, read_context_file


def assemble_context_pack(
    root: Path,
    *,
    project_id: str,
    provider: Mapping[str, Any],
    requirement: Mapping[str, Any],
    requested_time: Mapping[str, Mapping[str, Any]],
    entity_aliases: Mapping[str, str] | None = None,
    source_revision: str | None = None,
    observed_at: str | None = None,
) -> dict[str, Any]:
    compiled = compile_context_requirement(requirement)
    contract = compiled["contract"]
    windows = _windows(requested_time, contract["required_windows"])
    snapshot = git_snapshot(
        root, source_revision=source_revision, observed_at=observed_at
    )
    aliases = entity_aliases or {}
    resolved_subjects, subject_gaps = _resolved_entities(
        contract["subject_entities"], aliases
    )
    state = ContextPackBroker(
        contract,
        requirement_digest=compiled["digest"],
        provider=provider,
        source_revision=snapshot["source_revision"],
        subject_gaps=subject_gaps,
    )
    for declaration in contract["items"]:
        state.add(
            _candidate_item(
                root,
                project_id=project_id,
                provider=provider,
                declaration=declaration,
                windows=windows,
                subjects=set(resolved_subjects),
                aliases=aliases,
                snapshot=snapshot,
                requirement=contract,
                require_tracked=source_revision is None,
                budget=state.budget,
            )
        )
    if source_revision is None:
        assert_clean_paths(
            root, [item["citation"]["path"] for item in state.items]
        )
        if git_snapshot(root)["source_revision"] != snapshot["source_revision"]:
            raise ContextContractError(
                "CONTEXT_SNAPSHOT_CHANGED", "Repository changed while packing Context"
            )
    state.apply_supersession()
    state.apply_authority_conflicts()
    return state.render(
        subject_entities=contract["subject_entities"],
        resolved_entities=resolved_subjects,
        requested_time=windows,
    )


def _candidate_item(
    root: Path,
    *,
    project_id: str,
    provider: Mapping[str, Any],
    declaration: Mapping[str, Any],
    windows: Mapping[str, Mapping[str, str]],
    subjects: set[str],
    aliases: Mapping[str, str],
    snapshot: Mapping[str, str],
    requirement: Mapping[str, Any],
    require_tracked: bool,
    budget: Mapping[str, Any],
) -> dict[str, Any]:
    item_id = declaration["item_id"]
    resolved, gap = _candidate_alignment(
        declaration, windows, subjects, aliases, requirement
    )
    if gap is not None:
        return _candidate_gap(item_id, *gap)
    source = _candidate_source(
        root,
        declaration=declaration,
        provider=provider,
        requirement=requirement,
        snapshot=snapshot,
        require_tracked=require_tracked,
        budget=budget,
    )
    if "reason_code" in source:
        return _candidate_gap(item_id, source["status"], source["reason_code"])
    item = _render_context_item(
        project_id=project_id,
        provider=provider,
        declaration=declaration,
        resolved=resolved,
        snapshot=snapshot,
        source=source,
    )
    return {
        "item_id": item_id,
        "status": "available",
        "reason_code": None,
        "item": item,
        "size_bytes": len(source["encoded"]),
        "line_count": len(source["lines"]),
    }


def _candidate_alignment(
    declaration: Mapping[str, Any],
    windows: Mapping[str, Mapping[str, str]],
    subjects: set[str],
    aliases: Mapping[str, str],
    requirement: Mapping[str, Any],
) -> tuple[list[str], tuple[str, str] | None]:
    resolved, gaps = _resolved_entities(declaration["entity_refs"], aliases)
    if gaps or not resolved or not subjects.issuperset(resolved):
        return resolved, ("unsupported", "CONTEXT_ENTITY_UNALIGNED")
    aligned = all(
        time_range_contains(
            declaration["valid_time"],
            date.fromisoformat(window["start"]),
            date.fromisoformat(window["end"]),
            window["timezone"],
        )
        and date_range_contains(
            declaration["effective_range"],
            date.fromisoformat(window["start"]),
            date.fromisoformat(window["end"]),
        )
        for window in windows.values()
    )
    if not aligned:
        return resolved, ("unsupported", "CONTEXT_ENTITY_TIME_MISMATCH")
    if declaration["sensitivity"] == "restricted":
        return resolved, ("denied", "CONTEXT_SENSITIVITY_DENIED")
    if declaration["sensitivity"] not in requirement["allowed_sensitivity"]:
        return resolved, ("denied", "CONTEXT_SENSITIVITY_DENIED")
    if not _authority_allowed(declaration["authority"], requirement["authority_policy"]):
        return resolved, ("denied", "CONTEXT_AUTHORITY_DENIED")
    return resolved, None


def _candidate_source(
    root: Path,
    *,
    declaration: Mapping[str, Any],
    provider: Mapping[str, Any],
    requirement: Mapping[str, Any],
    snapshot: Mapping[str, str],
    require_tracked: bool,
    budget: Mapping[str, Any],
) -> dict[str, Any]:
    maximum = min(
        requirement["budget"]["max_file_bytes"],
        provider["contract"]["limits"]["max_file_bytes"],
    )
    try:
        content, _path = read_context_file(
            root,
            declaration["path"],
            maximum=maximum,
            require_tracked=require_tracked,
            max_depth=provider["contract"]["limits"]["max_path_depth"],
        )
    except ContextContractError as exc:
        return {
            "status": _status_for_reason(exc.reason_code),
            "reason_code": exc.reason_code,
        }
    encoded = content.encode("utf-8")
    lines = content.splitlines()
    if (
        budget["used_files"] + 1 > budget["max_files"]
        or budget["used_bytes"] + len(encoded) > budget["max_total_bytes"]
        or budget["used_lines"] + len(lines) > budget["max_total_lines"]
    ):
        return {"status": "unsupported", "reason_code": "CONTEXT_RESOURCE_LIMIT"}
    freshness = _freshness(declaration, requirement, snapshot["observed_at"])
    if freshness == "stale":
        return {"status": "stale", "reason_code": "CONTEXT_STALE"}
    return {
        "content": content,
        "encoded": encoded,
        "lines": lines,
        "freshness": freshness,
    }


def _render_context_item(
    *,
    project_id: str,
    provider: Mapping[str, Any],
    declaration: Mapping[str, Any],
    resolved: Sequence[str],
    snapshot: Mapping[str, str],
    source: Mapping[str, Any],
) -> dict[str, Any]:
    return validate_context_item(
        {
            "schema_version": ITEM_SCHEMA_VERSION,
            "uri": f"repo://{project_id}/{declaration['path']}",
            "provider_uri": provider["contract"]["uri"],
            "item_id": declaration["item_id"],
            "fact_id": declaration["fact_id"],
            "resource_type": declaration["resource_type"],
            "title": declaration["title"],
            "entity_refs": copy.deepcopy(declaration["entity_refs"]),
            "resolved_entity_refs": resolved,
            "valid_time": copy.deepcopy(declaration["valid_time"]),
            "effective_range": copy.deepcopy(declaration["effective_range"]),
            "observed_at": snapshot["observed_at"],
            "authority": declaration["authority"],
            "source_revision": snapshot["source_revision"],
            "content_hash": hashlib.sha256(source["encoded"]).hexdigest(),
            "freshness": source["freshness"],
            "source_trust": provider["contract"]["source_trust"],
            "supersedes": copy.deepcopy(declaration["supersedes"]),
            "sensitivity": declaration["sensitivity"],
            "role": "data",
            "citation": {
                "path": declaration["path"],
                "line_start": 1,
                "line_end": max(1, len(source["lines"])),
            },
            "content": source["content"],
        }
    )


def _candidate_gap(item_id: str, status: str, reason: str) -> dict[str, Any]:
    return {"item_id": item_id, "status": status, "reason_code": reason}


def _status_for_reason(reason: str) -> str:
    if reason in {"CONTEXT_ACCESS_DENIED", "CONTEXT_IGNORED"}:
        return "denied"
    if reason == "CONTEXT_RESOURCE_MISSING":
        return "missing"
    if reason == "CONTEXT_SNAPSHOT_CHANGED":
        return "stale"
    return "unsupported"


__all__ = ["assemble_context_pack"]
