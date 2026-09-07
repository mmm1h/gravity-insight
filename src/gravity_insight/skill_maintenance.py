"""Offline bundled Skill bootstrap and atomic activation."""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .skill_hub_contract import SkillHubContractError
from .skill_hub_locks import build_skills_lock, compile_skills_lock
from .skill_hub_state import build_hub_snapshot, read_json
from .skill_maintenance_state import (
    MAINTENANCE_DIRECTORY,
    MAINTENANCE_RECEIPT_NAME,
    build_skill_maintenance_generation,
    build_skill_maintenance_receipt,
    compile_skill_maintenance_receipt,
    load_skill_maintenance_generation,
    not_bootstrapped_skill_maintenance_receipt,
    write_skill_maintenance_generation,
    write_skill_maintenance_receipt,
)
from .skill_seed import open_bundled_hub_source, read_bundled_skill_seed


@dataclass(frozen=True)
class SkillBootstrapResult:
    schema_version: str
    status: str
    changed: bool
    skill_count: int
    artifacts_verified: int
    artifacts_written: int
    shortcut: str | None
    managed_lock_digest: str | None
    seed_digest: str | None
    network_called: bool
    reason_codes: list[str]


def bootstrap_bundled(
    client: Any,
    content: bytes | None = None,
    *,
    at: str | None = None,
    force: bool = False,
    project_root: str | Path | None = None,
) -> dict[str, Any]:
    timestamp = _timestamp(at)
    selected = read_bundled_skill_seed() if content is None else content
    if not isinstance(selected, bytes):
        raise SkillHubContractError("HUB_SEED_INVALID", "Bundled Skill seed is invalid")
    seed_digest = hashlib.sha256(selected).hexdigest()
    with client.cas.maintenance_writer():
        previous = maintenance_status(client)
        if _can_shortcut(previous, seed_digest, force=force):
            return asdict(_bootstrap_result(previous, changed=False, shortcut="seed_digest_match"))
        try:
            result = _install_seed(
                client,
                selected,
                seed_digest,
                previous,
                timestamp,
                project_root,
            )
        except (OSError, SkillHubContractError) as exc:
            _record_failure(client, previous, exc, timestamp)
            if isinstance(exc, SkillHubContractError):
                raise
            raise SkillHubContractError(
                "HUB_BOOTSTRAP_IO_FAILED", "Bundled Skill bootstrap failed"
            ) from exc
        return asdict(result)


def maintenance_status(client: Any) -> dict[str, Any]:
    """Read maintenance state without opening the wheel seed or using network."""

    path = client.state_root / MAINTENANCE_DIRECTORY / MAINTENANCE_RECEIPT_NAME
    if not path.exists() and not path.is_symlink():
        return not_bootstrapped_skill_maintenance_receipt()
    try:
        receipt = compile_skill_maintenance_receipt(read_json(path))
        if receipt["status"] in {"ready", "degraded"}:
            generation = load_skill_maintenance_generation(
                client.state_root, receipt["active_seed_digest"]
            )
            _assert_generation_receipt(generation, receipt)
        return receipt
    except SkillHubContractError:
        return _invalid_status(path)


def maintenance_snapshot(client: Any) -> dict[str, Any] | None:
    receipt = maintenance_status(client)
    if receipt["status"] not in {"ready", "degraded"}:
        return None
    generation = load_skill_maintenance_generation(
        client.state_root, receipt["active_seed_digest"]
    )
    return generation["snapshot"]


def _install_seed(
    client: Any,
    content: bytes,
    seed_digest: str,
    previous: Mapping[str, Any],
    timestamp: str,
    project_root: str | Path | None,
) -> SkillBootstrapResult:
    session = open_bundled_hub_source(content, runtime_version=client.runtime_version)
    candidate, fetched, verified = _prepare_candidate(client, session)
    reference = session.reference()
    snapshot = build_hub_snapshot(
        reference,
        reference["source_descriptor_digest"],
        session.index,
        network_called=False,
        at=timestamp,
    )
    generation = build_skill_maintenance_generation(
        seed_digest=seed_digest,
        managed_lock=candidate,
        snapshot=snapshot,
    )
    write_skill_maintenance_generation(client.state_root, generation)
    update_available, project_reason = _project_update_available(
        project_root, session, runtime_version=client.runtime_version
    )
    changed = previous.get("active_seed_digest") != seed_digest
    receipt = _active_receipt(
        session,
        candidate,
        timestamp,
        update_available=update_available,
        reason=project_reason,
        host_restart_required=changed,
    )
    write_skill_maintenance_receipt(client.state_root, receipt)
    return _bootstrap_result(
        receipt,
        changed=changed,
        shortcut=None,
        artifacts_verified=verified,
        artifacts_written=sum(not item["cached"] for item in fetched),
    )


def _prepare_candidate(
    client: Any, session: Any
) -> tuple[dict[str, Any], list[dict[str, Any]], int]:
    requested = sorted(session.index["skills"])
    selected = build_skills_lock(
        session.index,
        session.reference(),
        requested,
        runtime_version=client.runtime_version,
    )
    candidate = compile_skills_lock(selected)
    rebuilt = build_skills_lock(
        session.index,
        session.reference(),
        candidate["requested"],
        runtime_version=candidate["runtime_version"],
    )
    if candidate != rebuilt:
        raise SkillHubContractError(
            "HUB_LOCK_SOURCE_MISMATCH",
            "Managed lock differs from the exact bundled Hub snapshot",
        )
    session.assert_reference(candidate["source"])
    fetched = [
        client.cas.fetch_skill(session, session.index["skills"][item["skill_uri"]])
        for item in candidate["skills"]
    ]
    verification = client.verify(candidate)
    verified = len(verification["artifacts"])
    if not verification["ok"] or verified != len(candidate["skills"]):
        reason = next(iter(verification["reason_codes"]), "HUB_BOOTSTRAP_VERIFY_FAILED")
        raise SkillHubContractError(reason, "Bundled Skill final verification failed")
    return candidate, fetched, verified


def _can_shortcut(
    receipt: Mapping[str, Any], seed_digest: str, *, force: bool
) -> bool:
    return (
        not force
        and receipt["status"] in {"ready", "empty", "degraded"}
        and receipt["active_seed_digest"] == seed_digest
    )


def _record_failure(
    client: Any,
    previous: Mapping[str, Any],
    error: OSError | SkillHubContractError,
    timestamp: str,
) -> None:
    reason = (
        error.reason_code
        if isinstance(error, SkillHubContractError)
        else "HUB_BOOTSTRAP_IO_FAILED"
    )
    receipt = _failed_receipt(client, previous, reason, timestamp)
    write_skill_maintenance_receipt(client.state_root, receipt)


def _active_receipt(
    session: Any,
    lock: Mapping[str, Any],
    timestamp: str,
    *,
    update_available: bool | None,
    reason: str | None,
    host_restart_required: bool,
) -> dict[str, Any]:
    reference = session.reference()
    return build_skill_maintenance_receipt(
        status="degraded" if reason else "ready",
        bootstrap_checked=True,
        active_source=_active_source(reference),
        active_index_digest=reference["index_digest"],
        active_seed_digest=session.seed_digest,
        managed_lock_digest=lock["lock_digest"],
        skill_count=len(lock["skills"]),
        last_attempt_at=timestamp,
        last_success_at=timestamp,
        network_called=False,
        reason_codes=[reason] if reason else [],
        update_available=update_available,
        host_restart_required=host_restart_required,
    )


def _failed_receipt(
    client: Any,
    previous: Mapping[str, Any],
    reason: str,
    timestamp: str,
) -> dict[str, Any]:
    if _verified_active(client, previous):
        return build_skill_maintenance_receipt(
            status="degraded",
            bootstrap_checked=True,
            active_source=previous["active_source"],
            active_index_digest=previous["active_index_digest"],
            active_seed_digest=previous["active_seed_digest"],
            managed_lock_digest=previous["managed_lock_digest"],
            skill_count=previous["skill_count"],
            last_attempt_at=timestamp,
            last_success_at=previous["last_success_at"],
            network_called=False,
            reason_codes=[reason],
            update_available=previous["update_available"],
            host_restart_required=previous["host_restart_required"],
        )
    return build_skill_maintenance_receipt(
        status="unavailable",
        bootstrap_checked=True,
        active_source=None,
        active_index_digest=None,
        active_seed_digest=None,
        managed_lock_digest=None,
        skill_count=0,
        last_attempt_at=timestamp,
        last_success_at=None,
        network_called=False,
        reason_codes=[reason],
        update_available=None,
        host_restart_required=False,
    )


def _verified_active(client: Any, receipt: Mapping[str, Any]) -> bool:
    if receipt["status"] == "empty":
        return True
    if receipt["status"] not in {"ready", "degraded"}:
        return False
    try:
        generation = load_skill_maintenance_generation(
            client.state_root, receipt["active_seed_digest"]
        )
        _assert_generation_receipt(generation, receipt)
    except SkillHubContractError:
        return False
    return client.verify(generation["managed_lock"])["ok"]


def _bootstrap_result(
    receipt: Mapping[str, Any],
    *,
    changed: bool,
    shortcut: str | None,
    artifacts_verified: int = 0,
    artifacts_written: int = 0,
) -> SkillBootstrapResult:
    return SkillBootstrapResult(
        schema_version="gravity.skill-bootstrap.v1",
        status=receipt["status"],
        changed=changed,
        skill_count=receipt["skill_count"],
        artifacts_verified=artifacts_verified,
        artifacts_written=artifacts_written,
        shortcut=shortcut,
        managed_lock_digest=receipt["managed_lock_digest"],
        seed_digest=receipt["active_seed_digest"],
        network_called=False,
        reason_codes=list(receipt["reason_codes"]),
    )


def _assert_generation_receipt(
    generation: Mapping[str, Any], receipt: Mapping[str, Any]
) -> None:
    snapshot = generation["snapshot"]
    lock = generation["managed_lock"]
    agrees = (
        generation["seed_digest"] == receipt["active_seed_digest"]
        and snapshot["source"]["index_digest"] == receipt["active_index_digest"]
        and _active_source(snapshot["source"]) == receipt["active_source"]
        and lock["lock_digest"] == receipt["managed_lock_digest"]
        and len(snapshot["index"]["skills"]) == receipt["skill_count"]
    )
    if not agrees:
        raise SkillHubContractError(
            "SKILL_MAINTENANCE_STATE_INVALID",
            "Active Skill maintenance generation and receipt disagree",
        )


def _project_update_available(
    project_root: str | Path | None,
    session: Any,
    *,
    runtime_version: str,
) -> tuple[bool | None, str | None]:
    if project_root is None:
        return False, None
    path = Path(project_root).absolute() / "gravity.skills.lock.json"
    if not path.exists() and not path.is_symlink():
        return False, None
    try:
        current = compile_skills_lock(read_json(path))
    except SkillHubContractError:
        return None, "PROJECT_SKILL_LOCK_INVALID"
    try:
        available = build_skills_lock(
            session.index,
            session.reference(),
            current["requested"],
            runtime_version=runtime_version,
        )
    except SkillHubContractError:
        return True, None
    return current != available, None


def _invalid_status(path: Path) -> dict[str, Any]:
    return build_skill_maintenance_receipt(
        status="unavailable",
        bootstrap_checked=True,
        active_source=None,
        active_index_digest=None,
        active_seed_digest=None,
        managed_lock_digest=None,
        skill_count=0,
        last_attempt_at=_path_timestamp(path),
        last_success_at=None,
        network_called=False,
        reason_codes=["SKILL_MAINTENANCE_STATE_INVALID"],
        update_available=None,
        host_restart_required=False,
    )


def _active_source(reference: Mapping[str, Any]) -> dict[str, Any]:
    fields = (
        "source_id",
        "transport",
        "source_descriptor_digest",
        "source_revision",
    )
    return {key: reference[key] for key in fields}


def _timestamp(value: str | None) -> str:
    if value is None:
        return _now()
    try:
        selected = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except (AttributeError, ValueError) as exc:
        raise SkillHubContractError("HUB_TIME_INVALID", "Bootstrap time is invalid") from exc
    rendered = selected.astimezone(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )
    if rendered != value:
        raise SkillHubContractError(
            "HUB_TIME_INVALID", "Bootstrap time is not canonical UTC"
        )
    return rendered


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def _path_timestamp(*paths: Path) -> str:
    timestamps = []
    for path in paths:
        try:
            timestamps.append(path.lstat().st_mtime)
        except OSError:
            pass
    return _now() if not timestamps else datetime.fromtimestamp(
        max(timestamps), timezone.utc
    ).isoformat(timespec="seconds").replace("+00:00", "Z")


__all__ = [
    "bootstrap_bundled",
    "maintenance_snapshot",
    "maintenance_status",
]
