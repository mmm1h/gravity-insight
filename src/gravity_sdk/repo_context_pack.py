"""Entity/time/authority aligned assembly of explicit Repo Context Requirements."""

from __future__ import annotations

import copy
import hashlib
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any, Mapping, Sequence

from .context_alignment import (
    authority_allowed as _authority_allowed,
    context_freshness as _freshness,
    normalize_windows as _windows,
    resolve_entities as _resolved_entities,
)
from .context_contract import (
    ContextContractError,
    ITEM_SCHEMA_VERSION,
    PACK_SCHEMA_VERSION,
    compile_context_requirement,
    context_pack_digest,
    date_range_contains,
    time_range_contains,
    validate_context_item,
    validate_context_pack,
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
    state = _PackState(contract, provider, snapshot, subject_gaps)
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
        compiled,
        subject_entities=contract["subject_entities"],
        resolved_entities=resolved_subjects,
        requested_time=windows,
    )


class _PackState:
    def __init__(
        self,
        requirement: Mapping[str, Any],
        provider: Mapping[str, Any],
        snapshot: Mapping[str, Any],
        subject_gaps: Sequence[Mapping[str, Any]],
    ) -> None:
        self.requirement = requirement
        self.provider = provider
        self.snapshot = snapshot
        self.items: list[dict[str, Any]] = []
        self.declarations = {item["item_id"]: item for item in requirement["items"]}
        self.statuses: dict[str, dict[str, Any]] = {}
        self.excluded: list[dict[str, Any]] = []
        self.superseded: list[dict[str, Any]] = []
        self.conflicts: list[dict[str, Any]] = []
        self.gaps: list[dict[str, Any]] = [copy.deepcopy(item) for item in subject_gaps]
        self.budget = {
            **copy.deepcopy(requirement["budget"]),
            "used_files": 0,
            "used_bytes": 0,
            "used_lines": 0,
        }

    def add(self, candidate: Mapping[str, Any]) -> None:
        item_id = candidate["item_id"]
        if candidate["status"] == "available":
            self.items.append(copy.deepcopy(candidate["item"]))
            self.statuses[item_id] = _status(item_id, "available", None)
            self.budget["used_files"] += 1
            self.budget["used_bytes"] += candidate["size_bytes"]
            self.budget["used_lines"] += candidate["line_count"]
            return
        reason = str(candidate["reason_code"])
        status = str(candidate["status"])
        self.statuses[item_id] = _status(item_id, status, reason)
        exclusion = {"item_id": item_id, "reason_code": reason}
        self.excluded.append(exclusion)
        self._gap(item_id, status, reason)

    def apply_supersession(self) -> None:
        by_uri = {item["uri"]: item for item in self.items}
        cycles = _supersession_cycles(by_uri)
        remove = set(cycles)
        if cycles:
            by_fact: dict[str, list[str]] = defaultdict(list)
            for item in self.items:
                if item["item_id"] in cycles:
                    by_fact[item["fact_id"]].append(item["item_id"])
            for fact_id, item_ids in by_fact.items():
                self._conflict(
                    fact_id, item_ids, "CONTEXT_SUPERSESSION_INVALID"
                )
        for item in self.items:
            if item["item_id"] in cycles:
                continue
            for target_uri in item["supersedes"]:
                target = by_uri.get(target_uri)
                if target is None or target["item_id"] in cycles:
                    continue
                if target["fact_id"] != item["fact_id"]:
                    self._conflict(
                        item["fact_id"],
                        [target["item_id"], item["item_id"]],
                        "CONTEXT_SUPERSESSION_INVALID",
                    )
                    remove.update([target["item_id"], item["item_id"]])
                    continue
                remove.add(target["item_id"])
                self.superseded.append(
                    {
                        "item_id": target["item_id"],
                        "uri": target_uri,
                        "superseded_by": item["uri"],
                        "reason_code": "CONTEXT_SUPERSEDED",
                    }
                )
                self.statuses[target["item_id"]] = _status(
                    target["item_id"], "available", "CONTEXT_SUPERSEDED"
                )
        self.items = [item for item in self.items if item["item_id"] not in remove]

    def apply_authority_conflicts(self) -> None:
        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for item in self.items:
            groups[item["fact_id"]].append(item)
        remove: set[str] = set()
        for fact_id, values in groups.items():
            remove.update(self._authority_removals(fact_id, values))
        self.items = [item for item in self.items if item["item_id"] not in remove]

    def _authority_removals(
        self, fact_id: str, values: Sequence[dict[str, Any]]
    ) -> set[str]:
        canonical = [item for item in values if item["authority"] == "canonical"]
        if len(canonical) > 1:
            identities = [item["item_id"] for item in canonical]
            self._conflict(fact_id, identities, "CONTEXT_AUTHORITY_CONFLICT")
            return set(identities)
        if canonical:
            shadowed = [item for item in values if item["authority"] != "canonical"]
            for item in shadowed:
                self.excluded.append(
                    {
                        "item_id": item["item_id"],
                        "reason_code": "CONTEXT_AUTHORITY_SHADOWED",
                    }
                )
                self.statuses[item["item_id"]] = _status(
                    item["item_id"], "available", "CONTEXT_AUTHORITY_SHADOWED"
                )
            return {item["item_id"] for item in shadowed}
        hashes = {item["content_hash"] for item in values}
        if len(hashes) > 1 and len(values) > 1:
            identities = [item["item_id"] for item in values]
            self._conflict(fact_id, identities, "CONTEXT_SOURCE_CONFLICT")
            return set(identities)
        return set()

    def render(
        self,
        compiled_requirement: Mapping[str, Any],
        *,
        subject_entities: Sequence[str],
        resolved_entities: Sequence[str],
        requested_time: Mapping[str, Any],
    ) -> dict[str, Any]:
        self._fill_missing()
        required_gaps = [gap for gap in self.gaps if gap.get("required") is True]
        optional_gaps = [gap for gap in self.gaps if gap.get("required") is False]
        status = "blocked" if required_gaps else "partial" if optional_gaps else "available"
        claims = self._claims(required_gaps, optional_gaps)
        pack = {
            "schema_version": PACK_SCHEMA_VERSION,
            "status": status,
            "provider": {
                "uri": self.provider["contract"]["uri"],
                "digest": self.provider["digest"],
                "source_revision": self.snapshot["source_revision"],
            },
            "requirement": {
                "requirement_id": self.requirement["requirement_id"],
                "digest": compiled_requirement["digest"],
            },
            "skill_id": self.requirement["skill_uri"],
            "journey_id": self.requirement["journey_id"],
            "subject_entities": list(subject_entities),
            "resolved_entities": list(resolved_entities),
            "requested_time": copy.deepcopy(dict(requested_time)),
            "authority_policy": copy.deepcopy(self.requirement["authority_policy"]),
            "items": sorted(self.items, key=lambda item: item["item_id"]),
            "alignment": {
                "matched": sorted(item["uri"] for item in self.items),
                "excluded": sorted(self.excluded, key=lambda item: item["item_id"]),
                "superseded": sorted(self.superseded, key=lambda item: item["item_id"]),
            },
            "required_status": [
                self.statuses[item_id] for item_id in sorted(self.statuses)
            ],
            "conflicts": sorted(self.conflicts, key=lambda item: item["fact_id"]),
            "gaps": sorted(self.gaps, key=lambda item: str(item.get("item_id", ""))),
            "claims": claims,
            "budget": copy.deepcopy(self.budget),
            "network_called": False,
        }
        pack["pack_digest"] = context_pack_digest(pack)
        return validate_context_pack(pack)

    def _fill_missing(self) -> None:
        for item_id in self.declarations:
            if item_id in self.statuses:
                continue
            self.statuses[item_id] = _status(
                item_id, "missing", "CONTEXT_REQUIRED_MISSING"
            )
            self._gap(item_id, "missing", "CONTEXT_REQUIRED_MISSING")

    def _claims(
        self,
        required_gaps: Sequence[Mapping[str, Any]],
        optional_gaps: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        authorities = {item["authority"] for item in self.items}
        ceiling = next(
            (name for name in ("canonical", "supporting", "unverified") if name in authorities),
            "none",
        )
        required = set(self.requirement["authority_policy"]["required"])
        return {
            "confirmed_claims_allowed": not required_gaps and bool(authorities & required),
            "optional_context_complete": not optional_gaps,
            "authority_ceiling": ceiling,
        }

    def _gap(self, item_id: str, status: str, reason: str) -> None:
        declaration = self.declarations.get(item_id)
        required = declaration["required"] if declaration is not None else True
        gap = {
            "item_id": item_id,
            "required": required,
            "status": status,
            "reason_code": reason,
        }
        if gap not in self.gaps:
            self.gaps.append(gap)

    def _conflict(self, fact_id: str, item_ids: list[str], reason: str) -> None:
        conflict = {
            "fact_id": fact_id,
            "item_ids": sorted(item_ids),
            "reason_code": reason,
        }
        if conflict not in self.conflicts:
            self.conflicts.append(conflict)
        for item_id in item_ids:
            self.statuses[item_id] = _status(item_id, "conflicting", reason)
            self._gap(item_id, "conflicting", reason)


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


def _status(item_id: str, status: str, reason: str | None) -> dict[str, Any]:
    return {"item_id": item_id, "status": status, "reason_code": reason}


def _status_for_reason(reason: str) -> str:
    if reason in {"CONTEXT_ACCESS_DENIED", "CONTEXT_IGNORED"}:
        return "denied"
    if reason == "CONTEXT_RESOURCE_MISSING":
        return "missing"
    if reason == "CONTEXT_SNAPSHOT_CHANGED":
        return "stale"
    return "unsupported"


def _supersession_cycles(by_uri: Mapping[str, Mapping[str, Any]]) -> set[str]:
    state: dict[str, int] = {}
    trail: list[str] = []
    cycles: set[str] = set()

    def visit(uri: str) -> None:
        state[uri] = 1
        trail.append(uri)
        for target in by_uri[uri]["supersedes"]:
            if target not in by_uri:
                continue
            if state.get(target, 0) == 0:
                visit(target)
            elif state.get(target) == 1:
                cycles.update(trail[trail.index(target) :])
        trail.pop()
        state[uri] = 2

    for uri in by_uri:
        if state.get(uri, 0) == 0:
            visit(uri)
    return {by_uri[uri]["item_id"] for uri in cycles}


__all__ = ["assemble_context_pack"]
