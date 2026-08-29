"""Atomic local Hub snapshots and installation-only state."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import stat
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from .agent_runtime_contracts import (
    AgentRuntimeContractError,
    canonical_digest,
    validate_schema,
)
from .skill_hub_contract import SkillHubContractError, compile_hub_index
from .skill_hub_paths import assert_unlinked_path, is_reparse


SNAPSHOT_SCHEMA_VERSION = "gravity.skill-hub-snapshot.v1"
SKILL_STATE_SCHEMA_VERSION = "gravity.skill-installation-state.v1"
TRUSTED_STATE_SCHEMA_VERSION = "gravity.trusted-pack-installation-state.v1"
_SNAPSHOT_SCHEMA = "skill-hub-snapshot-v1.schema.json"
_SKILL_STATE_SCHEMA = "skill-installation-state-v1.schema.json"
_TRUSTED_STATE_SCHEMA = "trusted-pack-installation-state-v1.schema.json"
_MAX_STATE_BYTES = 16 * 1024 * 1024


def build_hub_snapshot(
    source: Mapping[str, Any],
    source_descriptor_digest: str,
    index: Mapping[str, Any],
    *,
    network_called: bool,
    at: str | None = None,
) -> dict[str, Any]:
    body = {
        "artifact_kind": "skill_hub_snapshot",
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "source": copy.deepcopy(dict(source)),
        "source_descriptor_digest": source_descriptor_digest,
        "index": copy.deepcopy(index["contract"]),
        "synced_at": _timestamp(at),
        "network_called": bool(network_called),
    }
    return compile_hub_snapshot(
        {**body, "snapshot_digest": canonical_digest(body)}
    )


def compile_hub_snapshot(value: Mapping[str, Any]) -> dict[str, Any]:
    contract = _contract(value, _SNAPSHOT_SCHEMA, "HUB_SNAPSHOT_INVALID")
    _source_reference(contract["source"])
    if contract["source_descriptor_digest"] != contract["source"][
        "source_descriptor_digest"
    ]:
        raise SkillHubContractError(
            "HUB_SNAPSHOT_INVALID", "Snapshot Source descriptor changed"
        )
    index = compile_hub_index(contract["index"])
    if contract["source"]["index_digest"] != index["digest"]:
        raise SkillHubContractError(
            "HUB_SNAPSHOT_INVALID", "Synced Index digest changed"
        )
    _timestamp(contract["synced_at"])
    _digest(contract, "snapshot_digest", "HUB_SNAPSHOT_DIGEST_MISMATCH")
    return contract


def write_hub_snapshot(state_root: Path, snapshot: Mapping[str, Any]) -> Path:
    selected = compile_hub_snapshot(snapshot)
    identity = hashlib.sha256(selected["source"]["source_id"].encode("utf-8")).hexdigest()
    path = state_root / "hub-snapshots" / f"{identity}.json"
    atomic_write_json(path, selected)
    if compile_hub_snapshot(read_json(path)) != selected:
        raise SkillHubContractError("HUB_STATE_WRITE_FAILED", "Hub snapshot readback changed")
    return path


def load_hub_snapshots(state_root: Path) -> list[dict[str, Any]]:
    root = state_root / "hub-snapshots"
    if not root.exists():
        return []
    if root.is_symlink() or not root.is_dir():
        raise SkillHubContractError("HUB_STATE_INVALID", "Hub snapshot root is invalid")
    snapshots = [compile_hub_snapshot(read_json(path)) for path in sorted(root.glob("*.json"))]
    identities = [item["source"]["source_id"] for item in snapshots]
    if len(identities) != len(set(identities)):
        raise SkillHubContractError("HUB_STATE_INVALID", "Hub snapshot identities collide")
    return snapshots


def build_skill_installation_state(
    lock_digest: str,
    installations: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    body = {
        "artifact_kind": "skill_installation_state",
        "schema_version": SKILL_STATE_SCHEMA_VERSION,
        "lock_digest": lock_digest,
        "installations": sorted(
            (copy.deepcopy(dict(item)) for item in installations),
            key=lambda item: item["skill_uri"],
        ),
    }
    return compile_skill_installation_state(
        {**body, "state_digest": canonical_digest(body)}
    )


def compile_skill_installation_state(value: Mapping[str, Any]) -> dict[str, Any]:
    contract = _contract(value, _SKILL_STATE_SCHEMA, "SKILL_STATE_INVALID")
    _installation_order(contract["installations"], "skill_uri")
    for item in contract["installations"]:
        _timestamp(item["installed_at"])
        _timestamp(item["last_verified_at"])
    _digest(contract, "state_digest", "SKILL_STATE_DIGEST_MISMATCH")
    return contract


def build_trusted_installation_state(
    lock_digest: str,
    installations: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    body = {
        "artifact_kind": "trusted_pack_installation_state",
        "schema_version": TRUSTED_STATE_SCHEMA_VERSION,
        "lock_digest": lock_digest,
        "installations": sorted(
            (copy.deepcopy(dict(item)) for item in installations),
            key=lambda item: item["pack_id"],
        ),
    }
    return compile_trusted_installation_state(
        {**body, "state_digest": canonical_digest(body)}
    )


def compile_trusted_installation_state(value: Mapping[str, Any]) -> dict[str, Any]:
    contract = _contract(value, _TRUSTED_STATE_SCHEMA, "TRUSTED_PACK_STATE_INVALID")
    _installation_order(contract["installations"], "pack_id")
    for item in contract["installations"]:
        _timestamp(item["installed_at"])
    _digest(contract, "state_digest", "TRUSTED_PACK_STATE_DIGEST_MISMATCH")
    return contract


def write_skill_installation_state(
    state_root: Path, value: Mapping[str, Any]
) -> Path:
    selected = compile_skill_installation_state(value)
    path = state_root / "skills-installation.json"
    atomic_write_json(path, selected)
    if compile_skill_installation_state(read_json(path)) != selected:
        raise SkillHubContractError("HUB_STATE_WRITE_FAILED", "Skill state readback changed")
    return path


def atomic_write_json(
    path: Path, value: Mapping[str, Any], *, private: bool = True
) -> None:
    path = assert_unlinked_path(
        path, reason="HUB_STATE_PATH_INVALID", label="State path"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    assert_unlinked_path(
        path.parent, reason="HUB_STATE_PATH_INVALID", label="State path"
    )
    if path.exists():
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise SkillHubContractError(
                "HUB_STATE_PATH_INVALID", "Existing state file boundary is invalid"
            )
    content = (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")
    if not 1 <= len(content) <= _MAX_STATE_BYTES:
        raise SkillHubContractError("HUB_STATE_INVALID", "State file exceeds its byte budget")
    temporary = path.parent / f".{path.name}.tmp-{uuid.uuid4().hex}"
    try:
        with temporary.open("xb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.chmod(0o600 if private else 0o644)
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def read_json(path: Path) -> dict[str, Any]:
    path = assert_unlinked_path(path, reason="HUB_STATE_INVALID", label="State path")
    try:
        metadata = path.lstat()
        content = path.read_bytes()
    except OSError as exc:
        raise SkillHubContractError("HUB_STATE_INVALID", "State file is missing") from exc
    if (
        path.is_symlink()
        or is_reparse(metadata)
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_nlink != 1
        or not 1 <= metadata.st_size <= _MAX_STATE_BYTES
        or len(content) != metadata.st_size
    ):
        raise SkillHubContractError("HUB_STATE_INVALID", "State file boundary is invalid")
    try:
        value = json.loads(content.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SkillHubContractError("HUB_STATE_INVALID", "State file is invalid") from exc
    if not isinstance(value, dict):
        raise SkillHubContractError("HUB_STATE_INVALID", "State file must be an object")
    return value


def _contract(value: Mapping[str, Any], schema: str, reason: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise SkillHubContractError(reason, "State contract must be an object")
    contract = copy.deepcopy(dict(value))
    try:
        validate_schema(contract, schema, reason)
    except AgentRuntimeContractError as exc:
        raise SkillHubContractError(reason, str(exc)) from exc
    return contract


def _source_reference(value: Mapping[str, Any]) -> None:
    expected = {
        "source_id",
        "transport",
        "source_descriptor_digest",
        "source_revision",
        "index_digest",
    }
    if set(value) != expected or value["transport"] not in {"git", "static_https"}:
        raise SkillHubContractError("HUB_SNAPSHOT_INVALID", "Snapshot source changed")
    if any(not isinstance(value[key], str) or not value[key] for key in expected):
        raise SkillHubContractError("HUB_SNAPSHOT_INVALID", "Snapshot source is invalid")


def _installation_order(values: Sequence[Mapping[str, Any]], key: str) -> None:
    identities = [item[key] for item in values]
    if identities != sorted(identities) or len(identities) != len(set(identities)):
        raise SkillHubContractError("HUB_STATE_INVALID", "Installation state is not deterministic")


def _digest(value: Mapping[str, Any], field: str, reason: str) -> None:
    body = copy.deepcopy(dict(value))
    actual = body.pop(field)
    if actual != canonical_digest(body):
        raise SkillHubContractError(reason, "State digest changed")


def _timestamp(value: str | None) -> str:
    if value is None:
        return datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
            "+00:00", "Z"
        )
    if not isinstance(value, str) or not value.endswith("Z"):
        raise SkillHubContractError("HUB_TIME_INVALID", "State time is not canonical UTC")
    try:
        selected = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise SkillHubContractError("HUB_TIME_INVALID", "State time is invalid") from exc
    rendered = selected.astimezone(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )
    if rendered != value:
        raise SkillHubContractError("HUB_TIME_INVALID", "State time is not canonical UTC")
    return rendered


__all__ = [
    "atomic_write_json",
    "build_hub_snapshot",
    "build_skill_installation_state",
    "build_trusted_installation_state",
    "compile_hub_snapshot",
    "compile_skill_installation_state",
    "compile_trusted_installation_state",
    "load_hub_snapshots",
    "read_json",
    "write_hub_snapshot",
    "write_skill_installation_state",
]
