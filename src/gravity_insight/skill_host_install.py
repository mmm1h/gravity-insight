"""Verified, plan-only handoff to native Agent Skill installers."""

from __future__ import annotations

import copy
import hashlib
import stat
from pathlib import Path
from typing import Any, Mapping

from .agent_runtime_contracts import (
    AgentRuntimeContractError,
    canonical_digest,
    validate_schema,
)
from .skill_hub_contract import SkillHubContractError
from .skill_hub_paths import assert_unlinked_path, is_reparse
from .skill_maintenance import maintenance_status
from .skill_seed import read_bundled_skill_seed, validate_bundled_skill_seed


def build_host_install_plan(
    client: Any,
    host: str,
    host_root: str | Path,
    content: bytes | None = None,
) -> dict[str, Any]:
    if host not in {"codex", "claude"}:
        raise SkillHubContractError(
            "HOST_SKILL_PLAN_INVALID", "Host must be codex or claude"
        )
    receipt = maintenance_status(client)
    if receipt["status"] not in {"ready", "degraded"}:
        raise SkillHubContractError(
            "HOST_SKILL_STATE_UNAVAILABLE", "Verified bundled Skills are not active"
        )
    selected = read_bundled_skill_seed() if content is None else content
    validated = validate_bundled_skill_seed(
        selected, runtime_version=client.runtime_version
    )
    if validated["seed_digest"] != receipt["active_seed_digest"]:
        raise SkillHubContractError(
            "HOST_SKILL_SEED_NOT_ACTIVE",
            "Bundled Host Skills do not match the active Runtime seed",
        )
    target_root = assert_unlinked_path(
        Path(host_root).expanduser().absolute(),
        reason="HOST_SKILL_PATH_INVALID",
        label="Host Skill root",
    )
    actions: list[dict[str, Any]] = []
    unchanged: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    packages = validated["agent_packages"]
    entries = sorted(
        validated["agent_index"]["skills"], key=lambda value: value["skill_uri"]
    )
    for item in entries:
        source = client.cas.stage_agent_skill(item, packages[item["skill_uri"]])
        target = target_root / item["directory"]
        _classify_target(host, item, source, target, actions, unchanged, conflicts)
    body = {
        "artifact_kind": "agent_skill_host_install_plan",
        "schema_version": "gravity.agent-skill-host-install-plan.v1",
        "status": "local_override_conflict" if conflicts else "ready",
        "host": host,
        "installation_owner": f"{host}_native_skill_installer",
        "activation": "next_host_start",
        "seed_digest": validated["seed_digest"],
        "actions": actions,
        "unchanged": unchanged,
        "conflicts": conflicts,
        "host_restart_required": bool(actions),
        "network_called": False,
    }
    return _compile_host_install_plan(
        {**body, "plan_digest": canonical_digest(body)}
    )


def _classify_target(
    host: str,
    item: Mapping[str, Any],
    source: Path,
    target: Path,
    actions: list[dict[str, Any]],
    unchanged: list[dict[str, Any]],
    conflicts: list[dict[str, Any]],
) -> None:
    state, preimage = _host_target_state(target, item)
    common = {
        "skill_uri": item["skill_uri"],
        "target_directory": str(target),
        "target_preimage_digest": preimage,
    }
    if state == "absent":
        actions.append(
            {
                "action_id": f"install-{item['archive']['sha256'][:12]}",
                "effect": "host_native_skill_install",
                "host": host,
                "package_digest": item["package_digest"],
                "archive_sha256": item["archive"]["sha256"],
                "source_directory": str(source),
                **common,
            }
        )
    elif state == "unchanged":
        unchanged.append(common)
    else:
        conflicts.append({**common, "reason_code": "local_override_conflict"})


def _host_target_state(
    target: Path, entry: Mapping[str, Any]
) -> tuple[str, str | None]:
    if not target.exists() and not target.is_symlink():
        return "absent", None
    try:
        root_metadata = target.lstat()
    except OSError:
        return "conflict", None
    if target.is_symlink() or is_reparse(root_metadata) or not target.is_dir():
        return "conflict", None
    observed = _bounded_target_files(target)
    if observed is None:
        return "conflict", None
    expected = {item["path"]: item for item in entry["files"]}
    exact = len(observed) == len(expected) and all(
        row["path"] in expected
        and row["sha256"] == expected[row["path"]]["sha256"]
        and row["size_bytes"] == expected[row["path"]]["size_bytes"]
        for row in observed
    )
    preimage = canonical_digest(observed)
    return ("unchanged" if exact else "conflict"), preimage


def _bounded_target_files(target: Path) -> list[dict[str, Any]] | None:
    try:
        paths = sorted(target.rglob("*"))
        if len(paths) > 64:
            return None
        rows: list[dict[str, Any]] = []
        for path in paths:
            metadata = path.lstat()
            if path.is_symlink() or is_reparse(metadata):
                return None
            if path.is_dir():
                continue
            if not _bounded_regular_file(metadata):
                return None
            content = path.read_bytes()
            rows.append(
                {
                    "path": path.relative_to(target).as_posix(),
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "size_bytes": len(content),
                }
            )
        return rows
    except OSError:
        return None


def _bounded_regular_file(metadata: Any) -> bool:
    return (
        stat.S_ISREG(metadata.st_mode)
        and metadata.st_nlink == 1
        and metadata.st_size <= 262_144
    )


def _compile_host_install_plan(value: Mapping[str, Any]) -> dict[str, Any]:
    contract = copy.deepcopy(dict(value))
    try:
        validate_schema(
            contract,
            "agent-skill-host-install-plan-v1.schema.json",
            "Host Skill install plan",
        )
    except AgentRuntimeContractError as exc:
        raise SkillHubContractError(
            "HOST_SKILL_PLAN_INVALID", "Host Skill install plan changed"
        ) from exc
    body = copy.deepcopy(contract)
    actual = body.pop("plan_digest")
    if actual != canonical_digest(body):
        raise SkillHubContractError(
            "HOST_SKILL_PLAN_DIGEST_MISMATCH", "Host Skill install plan changed"
        )
    for field in ("actions", "unchanged", "conflicts"):
        identities = [item["skill_uri"] for item in contract[field]]
        if identities != sorted(identities) or len(identities) != len(set(identities)):
            raise SkillHubContractError(
                "HOST_SKILL_PLAN_INVALID", "Host Skill plan order changed"
            )
    return contract


__all__ = ["build_host_install_plan"]
