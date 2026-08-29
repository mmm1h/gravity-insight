"""Separate Stage A Trusted Pack control-plane and startup verification."""

from __future__ import annotations

import copy
import hashlib
from importlib import metadata as importlib_metadata
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from . import __version__
from .errors import ErrorCategory, exit_code_for_category
from .skill_hub_cas import SkillHubCAS
from .skill_hub_contract import SkillHubContractError, compile_hub_index
from .skill_hub_locks import (
    build_trusted_pack_install_plan,
    build_trusted_packs_lock,
    compile_trusted_packs_lock,
)
from .skill_hub_paths import ensure_unlinked_directory
from .skill_hub_source import HttpGetter, open_locked_hub_source
from .skill_hub_state import (
    atomic_write_json,
    compile_trusted_installation_state,
    load_hub_snapshots,
    read_json,
)
from .support.process_lock import FileLockTimeout, advisory_file_lock


_LOCAL_EXIT = exit_code_for_category(ErrorCategory.LOCAL)
DistributionLookup = Callable[[str], Any]


class TrustedPackHubClient:
    """Resolve/fetch Trusted wheels but delegate every installation externally."""

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

    def resolve(
        self, requested: Sequence[str], *, source_id: str | None = None
    ) -> dict[str, Any]:
        snapshot, index = _select_index(self.state_root, self.runtime_version, source_id)
        lock = build_trusted_packs_lock(
            index,
            snapshot["source"],
            requested,
            runtime_version=self.runtime_version,
        )
        return {
            "schema_version": "gravity.trusted-pack-resolution.v1",
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
        path = Path(output).absolute()
        identity = hashlib.sha256(str(path).encode("utf-8")).hexdigest()
        process_lock = self.state_root / "locks" / f"trusted-packs-{identity}.lock"
        try:
            with advisory_file_lock(process_lock, owner="trusted-pack-lock"):
                atomic_write_json(path, lock, private=False)
                if compile_trusted_packs_lock(read_json(path)) != lock:
                    raise SkillHubContractError(
                        "TRUSTED_PACK_LOCK_WRITE_FAILED",
                        "Trusted Pack lock readback changed",
                    )
        except FileLockTimeout as exc:
            raise SkillHubContractError(
                "TRUSTED_PACK_LOCK_BUSY", "Trusted Pack lock is busy"
            ) from exc
        return {
            "schema_version": "gravity.trusted-pack-lock-write.v1",
            "status": "written",
            "path": str(path),
            "lock_digest": lock["lock_digest"],
            "pack_count": len(lock["packs"]),
            "network_called": False,
        }

    def fetch(
        self,
        lock: Mapping[str, Any],
        source: Mapping[str, Any],
        *,
        repository: str | Path | None = None,
        http_get: HttpGetter | None = None,
    ) -> dict[str, Any]:
        selected = compile_trusted_packs_lock(lock)
        session = open_locked_hub_source(
            source,
            selected["source"],
            repository=repository,
            http_get=http_get,
            runtime_version=selected["runtime_version"],
        )
        rebuilt = build_trusted_packs_lock(
            session.index,
            session.reference(),
            selected["requested"],
            runtime_version=selected["runtime_version"],
        )
        if rebuilt != selected:
            raise SkillHubContractError(
                "HUB_LOCK_SOURCE_MISMATCH", "Trusted lock differs from Hub snapshot"
            )
        results = [
            self.cas.fetch_trusted_pack(
                session, session.index["trusted_packs"][item["pack_id"]]
            )
            for item in selected["packs"]
        ]
        return {
            "schema_version": "gravity.trusted-pack-fetch.v1",
            "status": "verified",
            "lock_digest": selected["lock_digest"],
            "artifacts": results,
            "network_called": session.network_called,
        }

    def verify(self, lock: Mapping[str, Any]) -> dict[str, Any]:
        try:
            selected = compile_trusted_packs_lock(lock)
            artifacts = [
                {
                    "pack_id": item["pack_id"],
                    "wheel_sha256": item["wheel_sha256"],
                    "path": str(
                        self.cas.verify_trusted_wheel(
                            item["wheel_sha256"], size_bytes=item["artifact_size"]
                        )
                    ),
                }
                for item in selected["packs"]
            ]
        except SkillHubContractError as exc:
            return _invalid("gravity.trusted-pack-verification.v1", lock, exc.reason_code)
        return {
            "schema_version": "gravity.trusted-pack-verification.v1",
            "status": "valid",
            "ok": True,
            "lock_digest": selected["lock_digest"],
            "artifacts": artifacts,
            "reason_codes": [],
            "network_called": False,
        }

    def install_plan(self, lock: Mapping[str, Any]) -> dict[str, Any]:
        selected = compile_trusted_packs_lock(lock)
        paths = {
            item["pack_id"]: self.cas.verify_trusted_wheel(
                item["wheel_sha256"], size_bytes=item["artifact_size"]
            )
            for item in selected["packs"]
        }
        return build_trusted_pack_install_plan(selected, paths)


def verify_trusted_pack_startup(
    lock: Mapping[str, Any],
    installation_state: Mapping[str, Any],
    *,
    distribution_lookup: DistributionLookup = importlib_metadata.distribution,
) -> dict[str, Any]:
    try:
        selected = compile_trusted_packs_lock(lock)
        state = compile_trusted_installation_state(installation_state)
        if state["lock_digest"] != selected["lock_digest"]:
            raise SkillHubContractError(
                "TRUSTED_PACK_STATE_MISMATCH", "Installer state belongs to another lock"
            )
        installed = {item["pack_id"]: item for item in state["installations"]}
        if set(installed) != set(selected["requested"]):
            raise SkillHubContractError(
                "TRUSTED_PACK_STATE_MISMATCH", "Installer state is incomplete"
            )
        results = [
            _verify_distribution(item, installed[item["pack_id"]], distribution_lookup)
            for item in selected["packs"]
        ]
    except (SkillHubContractError, importlib_metadata.PackageNotFoundError) as exc:
        reason = getattr(exc, "reason_code", "TRUSTED_PACK_DISTRIBUTION_MISSING")
        return _invalid("gravity.trusted-pack-startup-verification.v1", lock, reason)
    return {
        "schema_version": "gravity.trusted-pack-startup-verification.v1",
        "status": "verified",
        "ok": True,
        "lock_digest": selected["lock_digest"],
        "packs": results,
        "reason_codes": [],
        "network_called": False,
    }


def _verify_distribution(
    locked: Mapping[str, Any],
    installed: Mapping[str, Any],
    lookup: DistributionLookup,
) -> dict[str, Any]:
    exact = {
        "pack_id": locked["pack_id"],
        "descriptor_digest": locked["descriptor_digest"],
        "distribution": locked["distribution"],
        "version": locked["version"],
        "wheel_sha256": locked["wheel_sha256"],
    }
    if any(installed[key] != value for key, value in exact.items()) or installed[
        "health"
    ] != "healthy":
        raise SkillHubContractError(
            "TRUSTED_PACK_STATE_MISMATCH", "Installer receipt changed"
        )
    distribution = lookup(locked["distribution"])
    metadata = distribution.metadata
    if (
        distribution.version != locked["version"]
        or _normalized_distribution(str(metadata.get("Name", "")))
        != _normalized_distribution(locked["distribution"])
        or metadata.get("Gravity-Trusted-Pack-ID") != locked["pack_id"]
    ):
        raise SkillHubContractError(
            "TRUSTED_PACK_DISTRIBUTION_MISMATCH", "Installed distribution identity changed"
        )
    groups = {item.group for item in distribution.entry_points}
    if groups != set(locked["allowed_groups"]):
        raise SkillHubContractError(
            "TRUSTED_PACK_GROUP_INVALID", "Installed distribution groups changed"
        )
    return {
        "pack_id": locked["pack_id"],
        "descriptor_digest": locked["descriptor_digest"],
        "distribution": locked["distribution"],
        "version": locked["version"],
        "wheel_sha256": locked["wheel_sha256"],
        "allowed_groups": sorted(groups),
    }


def _select_index(
    state_root: Path, runtime_version: str, source_id: str | None
) -> tuple[dict[str, Any], dict[str, Any]]:
    values = [
        (snapshot, compile_hub_index(snapshot["index"], runtime_version=runtime_version))
        for snapshot in load_hub_snapshots(state_root)
    ]
    if source_id is not None:
        values = [item for item in values if item[0]["source"]["source_id"] == source_id]
    if len(values) != 1:
        reason = "HUB_NOT_SYNCED" if not values else "HUB_SOURCE_REQUIRED"
        raise SkillHubContractError(reason, "Select exactly one synced Hub Source")
    return values[0]


def _invalid(schema: str, lock: Any, reason: str) -> dict[str, Any]:
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


def _normalized_distribution(value: str) -> str:
    return "-".join(filter(None, value.replace("_", "-").replace(".", "-").split("-"))).casefold()


__all__ = ["TrustedPackHubClient", "verify_trusted_pack_startup"]
