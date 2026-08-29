"""Provider-neutral Context Pack state, alignment outcomes, and conflict rules."""

from __future__ import annotations

import copy
from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

from .context_contract import (
    PACK_SCHEMA_VERSION,
    context_pack_digest,
    validate_context_pack,
)


class ContextPackBroker:
    """Assemble already bounded Provider candidates into one governed Pack."""

    def __init__(
        self,
        requirement: Mapping[str, Any],
        *,
        requirement_digest: str,
        provider: Mapping[str, Any],
        source_revision: str,
        subject_gaps: Sequence[Mapping[str, Any]],
        provider_audit: Mapping[str, Any] | None = None,
    ) -> None:
        self.requirement = copy.deepcopy(dict(requirement))
        self.requirement_digest = requirement_digest
        self.provider = copy.deepcopy(dict(provider))
        self.source_revision = source_revision
        self.provider_audit = (
            copy.deepcopy(dict(provider_audit))
            if provider_audit is not None
            else None
        )
        self.items: list[dict[str, Any]] = []
        self.declarations = {
            item["item_id"]: copy.deepcopy(dict(item))
            for item in requirement["items"]
        }
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
                "source_revision": self.source_revision,
            },
            "requirement": {
                "requirement_id": self.requirement["requirement_id"],
                "digest": self.requirement_digest,
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
        if self.provider_audit is not None:
            pack.update(copy.deepcopy(self.provider_audit))
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


def _status(item_id: str, status: str, reason: str | None) -> dict[str, Any]:
    return {"item_id": item_id, "status": status, "reason_code": reason}


def _supersession_cycles(
    by_uri: Mapping[str, Mapping[str, Any]],
) -> set[str]:
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


__all__ = ["ContextPackBroker"]
