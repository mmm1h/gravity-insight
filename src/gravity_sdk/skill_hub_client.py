"""Stage A control-plane client for static no-code Skill content."""

from __future__ import annotations

import copy
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import __version__
from .errors import ErrorCategory, exit_code_for_category
from .skill_contract import normalize_skill_identity
from .skill_hub_cas import SkillHubCAS
from .skill_hub_contract import (
    SkillHubContractError,
    compile_hub_index,
    compile_hub_source,
)
from .skill_hub_locks import build_skills_lock, compile_skills_lock
from .skill_hub_paths import ensure_unlinked_directory
from .skill_hub_source import HttpGetter, open_locked_hub_source, sync_hub_source
from .skill_hub_state import (
    atomic_write_json,
    build_hub_snapshot,
    build_skill_installation_state,
    load_hub_snapshots,
    read_json,
    write_hub_snapshot,
    write_skill_installation_state,
)
from .support.process_lock import FileLockTimeout, advisory_file_lock


_LOCAL_EXIT = exit_code_for_category(ErrorCategory.LOCAL)


class SkillHubClient:
    """Synchronize and materialize exact static Skills outside Runtime execution."""

    def __init__(
        self,
        state_root: str | Path,
        *,
        cas_root: str | Path | None = None,
        runtime_version: str = __version__,
    ) -> None:
        self.state_root = ensure_unlinked_directory(
            Path(state_root), reason="HUB_STATE_INVALID", label="State root"
        )
        self.cas = SkillHubCAS(cas_root or self.state_root / "skill-hub-cas")
        self.runtime_version = runtime_version

    def sync(
        self,
        source: Mapping[str, Any],
        *,
        repository: str | Path | None = None,
        http_get: HttpGetter | None = None,
    ) -> dict[str, Any]:
        compiled_source = compile_hub_source(source)
        session = sync_hub_source(
            compiled_source["contract"],
            repository=repository,
            http_get=http_get,
            runtime_version=self.runtime_version,
        )
        snapshot = build_hub_snapshot(
            session.reference(),
            compiled_source["digest"],
            session.index,
            network_called=session.network_called,
        )
        write_hub_snapshot(self.state_root, snapshot)
        return {
            "schema_version": "gravity.skill-hub-sync.v1",
            "status": "synced",
            "source": session.reference(),
            "skill_count": len(session.index["skills"]),
            "trusted_pack_count": len(session.index["trusted_packs"]),
            "snapshot_digest": snapshot["snapshot_digest"],
            "network_called": session.network_called,
        }

    def search(self, query: str, *, maximum: int = 20) -> dict[str, Any]:
        tokens = _tokens(query)
        if isinstance(maximum, bool) or not isinstance(maximum, int) or not 1 <= maximum <= 100:
            raise SkillHubContractError("HUB_SEARCH_INVALID", "Search limit is invalid")
        rows: list[tuple[int, str, dict[str, Any]]] = []
        for snapshot, index in self._indexes():
            for entry in index["skills"].values():
                manifest = entry["manifest"]
                text = " ".join(
                    (
                        entry["skill_uri"],
                        manifest["summary"],
                        manifest["description"],
                        manifest["guide"]["title"],
                    )
                ).casefold()
                score = sum(token in text for token in tokens)
                if score == len(tokens):
                    rows.append(
                        (
                            score,
                            entry["skill_uri"],
                            _skill_summary(snapshot["source"], entry),
                        )
                    )
        ordered = [row for _score, _identity, row in sorted(rows, key=lambda item: (-item[0], item[1]))]
        return {
            "schema_version": "gravity.skill-hub-search.v1",
            "status": "success",
            "query": query,
            "count": min(len(ordered), maximum),
            "results": ordered[:maximum],
            "truncated": len(ordered) > maximum,
            "network_called": False,
        }

    def show(self, identifier: str) -> dict[str, Any]:
        identity = normalize_skill_identity(identifier)
        matches = [
            (snapshot, index["skills"][identity])
            for snapshot, index in self._indexes()
            if identity in index["skills"]
        ]
        if not matches:
            raise SkillHubContractError("HUB_SKILL_MISSING", "Exact Hub Skill is missing")
        if len(matches) != 1:
            raise SkillHubContractError(
                "HUB_SKILL_CONFLICT", "Exact Hub Skill exists in multiple sources"
            )
        snapshot, entry = matches[0]
        return {
            "schema_version": "gravity.skill-hub-description.v1",
            "status": "available",
            "source": copy.deepcopy(snapshot["source"]),
            "skill": _skill_summary(snapshot["source"], entry),
            "manifest": copy.deepcopy(entry["manifest"]),
            "package": copy.deepcopy(entry["package"]),
            "network_called": False,
        }

    def resolve(
        self, requested: Sequence[str], *, source_id: str | None = None
    ) -> dict[str, Any]:
        snapshot, index = self._index(source_id)
        lock = build_skills_lock(
            index,
            snapshot["source"],
            requested,
            runtime_version=self.runtime_version,
        )
        return {
            "schema_version": "gravity.skill-hub-resolution.v1",
            "status": "resolved",
            "lock": lock,
            "network_called": False,
        }

    def lock(
        self,
        requested: Sequence[str],
        output: str | Path,
        *,
        source_id: str | None = None,
    ) -> dict[str, Any]:
        lock = self.resolve(requested, source_id=source_id)["lock"]
        path = self._write_lock(Path(output), lock)
        return _lock_result(path, lock, changed=True)

    def update(
        self,
        requested: Sequence[str],
        output: str | Path,
        *,
        source_id: str | None = None,
    ) -> dict[str, Any]:
        path = Path(output)
        previous = compile_skills_lock(read_json(path))
        selected = self.resolve(requested, source_id=source_id)["lock"]
        changed = previous != selected
        if changed:
            self._write_lock(path, selected)
        return _lock_result(path.resolve(), selected, changed=changed)

    def fetch(
        self,
        lock: Mapping[str, Any],
        source: Mapping[str, Any],
        *,
        repository: str | Path | None = None,
        http_get: HttpGetter | None = None,
    ) -> dict[str, Any]:
        selected = compile_skills_lock(lock)
        session = open_locked_hub_source(
            source,
            selected["source"],
            repository=repository,
            http_get=http_get,
            runtime_version=selected["runtime_version"],
        )
        rebuilt = build_skills_lock(
            session.index,
            session.reference(),
            selected["requested"],
            runtime_version=selected["runtime_version"],
        )
        if rebuilt != selected:
            raise SkillHubContractError(
                "HUB_LOCK_SOURCE_MISMATCH", "Lock differs from the exact Hub snapshot"
            )
        results = [
            self.cas.fetch_skill(session, session.index["skills"][item["skill_uri"]])
            for item in selected["skills"]
        ]
        return {
            "schema_version": "gravity.skill-hub-fetch.v1",
            "status": "verified",
            "lock_digest": selected["lock_digest"],
            "artifacts": results,
            "network_called": session.network_called,
        }

    def install(
        self,
        lock: Mapping[str, Any],
        *,
        install_root: str | Path | None = None,
        at: str | None = None,
    ) -> dict[str, Any]:
        selected = compile_skills_lock(lock)
        root = Path(install_root or self.state_root / "installed-skills").resolve()
        timestamp = at or _now()
        results = []
        rows = []
        for item in selected["skills"]:
            target = root / _installation_relative(item["skill_uri"])
            result = self.cas.materialize_skill(item["package_digest"], target)
            results.append(result)
            rows.append(
                {
                    "skill_uri": item["skill_uri"],
                    "package_digest": item["package_digest"],
                    "installed_at": timestamp,
                    "local_path": str(target),
                    "last_verified_at": timestamp,
                    "health": "healthy",
                }
            )
        state = build_skill_installation_state(selected["lock_digest"], rows)
        state_path = write_skill_installation_state(self.state_root, state)
        return {
            "schema_version": "gravity.skill-hub-install.v1",
            "status": "installed",
            "lock_digest": selected["lock_digest"],
            "installations": results,
            "state_path": str(state_path),
            "network_called": False,
        }

    def verify(self, lock: Mapping[str, Any]) -> dict[str, Any]:
        try:
            selected = compile_skills_lock(lock)
            artifacts = [
                self.cas.verify_skill(item["package_digest"])
                for item in selected["skills"]
            ]
        except SkillHubContractError as exc:
            return _verification("gravity.skill-hub-verification.v1", lock, exc.reason_code)
        return {
            "schema_version": "gravity.skill-hub-verification.v1",
            "status": "valid",
            "ok": True,
            "lock_digest": selected["lock_digest"],
            "artifacts": artifacts,
            "reason_codes": [],
            "network_called": False,
        }

    def audit(self) -> dict[str, Any]:
        snapshots = load_hub_snapshots(self.state_root)
        return {
            "schema_version": "gravity.skill-hub-audit.v1",
            "status": "success",
            "sources": [
                {
                    "source": copy.deepcopy(item["source"]),
                    "snapshot_digest": item["snapshot_digest"],
                    "synced_at": item["synced_at"],
                    "skill_count": len(item["index"]["skills"]),
                    "trusted_pack_count": len(item["index"]["trusted_packs"]),
                }
                for item in snapshots
            ],
            "network_called": False,
        }

    def _indexes(self) -> list[tuple[dict[str, Any], dict[str, Any]]]:
        return [
            (snapshot, compile_hub_index(snapshot["index"], runtime_version=self.runtime_version))
            for snapshot in load_hub_snapshots(self.state_root)
        ]

    def _index(
        self, source_id: str | None
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        values = self._indexes()
        if source_id is not None:
            values = [item for item in values if item[0]["source"]["source_id"] == source_id]
        if len(values) != 1:
            reason = "HUB_NOT_SYNCED" if not values else "HUB_SOURCE_REQUIRED"
            raise SkillHubContractError(reason, "Select exactly one synced Hub Source")
        return values[0]

    def _write_lock(self, path: Path, lock: Mapping[str, Any]) -> Path:
        supplied = path.absolute()
        identity = hashlib.sha256(str(supplied).encode("utf-8")).hexdigest()
        lock_path = self.state_root / "locks" / f"project-skills-{identity}.lock"
        try:
            with advisory_file_lock(lock_path, owner="skill-hub-lock"):
                atomic_write_json(supplied, lock, private=False)
                if compile_skills_lock(read_json(supplied)) != lock:
                    raise SkillHubContractError(
                        "HUB_LOCK_WRITE_FAILED", "Skill lock readback changed"
                    )
        except FileLockTimeout as exc:
            raise SkillHubContractError("HUB_LOCK_BUSY", "Skill lock is busy") from exc
        return supplied.resolve()


def _tokens(value: Any) -> tuple[str, ...]:
    if not isinstance(value, str) or not value.strip() or len(value) > 512:
        raise SkillHubContractError("HUB_SEARCH_INVALID", "Hub search query is invalid")
    tokens = tuple(dict.fromkeys(value.casefold().split()))
    if len(tokens) > 16:
        raise SkillHubContractError("HUB_SEARCH_INVALID", "Hub search query is too broad")
    return tokens


def _skill_summary(source: Mapping[str, Any], entry: Mapping[str, Any]) -> dict[str, Any]:
    manifest = entry["manifest"]
    return {
        "skill_uri": entry["skill_uri"],
        "namespace": manifest["namespace"],
        "skill_id": manifest["skill_id"],
        "version": manifest["version"],
        "summary": manifest["summary"],
        "manifest_digest": entry["package"]["manifest_digest"],
        "package_digest": entry["package"]["package_digest"],
        "source_id": source["source_id"],
    }


def _installation_relative(identity: str) -> Path:
    compact, _, version = identity.removeprefix("skill://").partition("@")
    namespace, _, skill_id = compact.partition("/")
    if not namespace or not skill_id or not version:
        raise SkillHubContractError("HUB_SKILL_INVALID", "Skill identity changed")
    return Path(f"{namespace}.{skill_id}") / version


def _lock_result(path: Path, lock: Mapping[str, Any], *, changed: bool) -> dict[str, Any]:
    return {
        "schema_version": "gravity.skill-hub-lock-write.v1",
        "status": "written" if changed else "unchanged",
        "path": str(path),
        "lock_digest": lock["lock_digest"],
        "skill_count": len(lock["skills"]),
        "changed": changed,
        "network_called": False,
    }


def _verification(schema: str, lock: Any, reason: str) -> dict[str, Any]:
    digest = lock.get("lock_digest") if isinstance(lock, Mapping) else None
    return {
        "schema_version": schema,
        "status": "invalid",
        "ok": False,
        "exit_code": _LOCAL_EXIT,
        "lock_digest": digest if isinstance(digest, str) else None,
        "artifacts": [],
        "reason_codes": [reason],
        "network_called": False,
    }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


__all__ = ["SkillHubClient"]
