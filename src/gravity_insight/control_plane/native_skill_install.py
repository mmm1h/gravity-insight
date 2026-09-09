"""Explicit project-native Skill file transactions; no Runtime execution side effects."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

from ..agent_runtime_contracts import canonical_digest
from ..contracts.envelope_obligations import (
    CompletenessState, DataCompleteness, DiagnosticEvidence, DiagnosticState,
    EnvelopeObligations, ExecutionState, ExecutionStatus, MutationCertainty,
    MutationState, SemanticState, SemanticValidity, serialize_envelope,
)
from ..skill_host_install import _bounded_regular_file, _bounded_target_files, _compile_host_install_plan
from ..skill_hub_contract import SkillHubContractError
from ..skill_hub_paths import assert_unlinked_path
from ..skill_seed import read_bundled_skill_seed, validate_bundled_skill_seed


def _native_path(path: Path) -> Path:
    if ".." in path.parts or path.drive.startswith("\\"):
        raise SkillHubContractError("HOST_SKILL_PATH_INVALID", "Parent traversal and network/device paths are forbidden")
    checked = assert_unlinked_path(path, reason="HOST_SKILL_PATH_INVALID", label="Native Skill path")
    return checked.resolve()


def _native_snapshot(path: Path) -> dict[str, Any] | None:
    _native_path(path)
    if not path.exists():
        return None
    if not path.is_dir():
        raise SkillHubContractError("HOST_SKILL_CONFLICT", "Native target is not a directory")
    directories: list[str] = []
    files = _bounded_target_files(path, directories=directories)
    if files is None:
        raise SkillHubContractError("HOST_SKILL_CONFLICT", "Unsafe or oversized native tree")
    # Empty directories are also preimages: preserve untracked local folders.
    return {"files": files, "directories": sorted(directories)}


def _ownership_bytes(path: Path) -> bytes | None:
    _native_path(path)
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return None
    if not _bounded_regular_file(metadata):
        raise SkillHubContractError("HOST_SKILL_CONFLICT", "Unsafe native ownership file")
    return path.read_bytes()


def _expected_native(entry: Mapping[str, Any]) -> dict[str, Any]:
    files = sorted(entry["files"], key=lambda row: Path(row["path"]))
    directories = sorted({
        parent.as_posix() for row in files for parent in Path(row["path"]).parents
        if parent != Path(".")
    })
    return {"files": files, "directories": directories}


@lru_cache(maxsize=1)
def _native_seed_index(content: bytes) -> tuple[str, str]:
    validated = validate_bundled_skill_seed(content)
    # Cache only immutable, byte-keyed index data, never mutable file observations.
    return validated["seed_digest"], json.dumps(validated["agent_index"]["skills"])


def _native_selection(plan: Mapping[str, Any], project_root: Path) -> tuple[dict, Path, list]:
    selected = _compile_host_install_plan(plan)
    project = _native_path(project_root.expanduser().absolute())
    if not project.is_dir():
        raise SkillHubContractError("HOST_SKILL_PATH_INVALID", "Project root must exist")
    root = _native_path(project / (".agents" if selected["host"] == "codex" else ".claude") / "skills")
    if any(root.is_relative_to(protected.resolve()) for protected in (Path.home() / ".agents/skills", Path.home() / ".claude/skills")):
        raise SkillHubContractError("HOST_SKILL_PATH_INVALID", "User-global installation is not supported")
    seed_digest, index_json = _native_seed_index(read_bundled_skill_seed())
    if selected["seed_digest"] != seed_digest:
        raise SkillHubContractError("HOST_SKILL_SEED_NOT_ACTIVE", "Plan requires the matching bundled Runtime seed")
    entries = {row["skill_uri"]: row for row in json.loads(index_json)}
    rows = []
    seen: set[str] = set()
    for kind in ("actions", "unchanged", "conflicts"):
        for item in selected[kind]:
            identity = item["skill_uri"]
            if identity in seen or identity not in entries:
                raise SkillHubContractError("HOST_SKILL_PLAN_INVALID", "Duplicate or unavailable native Skill")
            seen.add(identity)
            entry = entries[identity]
            target = _native_path(Path(item["target_directory"]))
            if target != root / entry["directory"]:
                raise SkillHubContractError("HOST_SKILL_PATH_INVALID", "Plan target is not the selected project's native discovery directory")
            if kind == "actions" and any((
                item["host"] != selected["host"],
                item["package_digest"] != entry["package_digest"],
                item["archive_sha256"] != entry["archive"]["sha256"],
            )):
                raise SkillHubContractError("HOST_SKILL_PLAN_INVALID", "Native action identity changed")
            rows.append((kind, item, entry, target))
    return selected, root, rows


def preview_native_install(
    plan: Mapping[str, Any], project_root: Path, *, operation: str = "install",
) -> dict[str, Any]:
    """Read-only preview; approval binds source, target and ownership preimages."""
    if operation not in {"install", "uninstall"}:
        raise SkillHubContractError("HOST_SKILL_PLAN_INVALID", "Unsupported native operation")
    selected, root, rows = _native_selection(plan, project_root)
    targets = []
    for kind, item, entry, target in rows:
        expected = _expected_native(entry)
        owner_path = root / (".gravity-" + entry["directory"] + ".json")
        owner = {"schema_version": "gravity.native-skill-ownership.v1", "host": selected["host"], "skill_uri": entry["skill_uri"], **expected}
        owner_bytes = (json.dumps(owner, sort_keys=True, separators=(",", ":")) + chr(10)).encode()
        observed = _native_snapshot(target)
        ownership = _ownership_bytes(owner_path)
        owned = ownership == owner_bytes
        source = None
        if operation == "install" and kind == "actions":
            source = _native_snapshot(Path(item["source_directory"]))
            if source != expected:
                raise SkillHubContractError("HOST_SKILL_SOURCE_CHANGED", "Plan source no longer matches verified package files")
        effect, reason = _native_effect(kind, item, operation, observed, expected, ownership, owned)
        targets.append({
            "skill_uri": entry["skill_uri"], "target_directory": str(target),
            "source_directory": item.get("source_directory"), "source_preimage": source,
            "target_preimage": observed, "expected": expected,
            "ownership_path": str(owner_path), "ownership_preimage_sha256": hashlib.sha256(ownership).hexdigest() if ownership is not None else None,
            "ownership_content": owner_bytes.decode(), "owned": owned,
            "effect": effect, "conflict": reason,
        })
    result = {
        "schema_version": "gravity.native-skill-preview.v1", "operation": operation,
        "plan_digest": selected["plan_digest"], "host_root": str(root),
        "status": "conflict" if any(row["conflict"] for row in targets) else "ready",
        "targets": targets, "activation": "next_host_start", "host_discovery": "not_measured",
        "network_called": False,
    }
    return serialize_envelope(
        {**result, "preview_digest": canonical_digest(result)},
        _native_obligations("HOST_SKILL_PREVIEW_OBSERVED"),
    )


def _native_effect(kind, item, operation, observed, expected, ownership, owned):
    if kind == "conflicts":
        return "unchanged", "plan_contains_conflicts"
    if observed is None:
        if ownership is not None:
            return "unchanged", "owned_target_missing"
        if operation == "uninstall":
            return "unchanged", None
        return ("install", None) if kind == "actions" else ("unchanged", "target_preimage_changed")
    if observed != expected:
        return "unchanged", "local_override_conflict"
    if operation == "uninstall":
        return ("remove", None) if owned else ("unchanged", "unknown_ownership")
    if kind == "actions" and not owned:
        return "unchanged", "unknown_ownership"
    if kind == "unchanged" and item["target_preimage_digest"] != canonical_digest(observed["files"]):
        return "unchanged", "target_preimage_changed"
    return "unchanged", None


def _native_obligations(evidence: str, mutation: MutationState = MutationState.NOT_ATTEMPTED) -> EnvelopeObligations:
    return EnvelopeObligations(
        ExecutionStatus(ExecutionState.COMPLETE, evidence),
        DataCompleteness(CompletenessState.NOT_APPLICABLE, "HOST_SKILL_FILES_ONLY"),
        SemanticValidity(SemanticState.NOT_APPLICABLE, ()),
        DiagnosticEvidence(DiagnosticState.INCOMPLETE, ("HOST_DISCOVERY_NOT_MEASURED",)),
        MutationCertainty(mutation, evidence),
    )


def readback_native_install(plan: Mapping[str, Any], project_root: Path) -> dict[str, Any]:
    """Verify target bytes independently of CAS and host loading evidence."""
    selected, _root, rows = _native_selection(plan, project_root)
    targets = []
    for _kind, item, entry, target in rows:
        observed = _native_snapshot(target)
        expected = _expected_native(entry)
        targets.append({
            "skill_uri": item["skill_uri"], "target_directory": str(target),
            "status": "absent" if observed is None else ("consistent" if observed == expected else "conflict"),
            "files": observed["files"] if observed is not None else [],
            "expected_digest": canonical_digest(expected), "observed_digest": canonical_digest(observed),
        })
    result = {
        "schema_version": "gravity.native-skill-readback.v1", "plan_digest": selected["plan_digest"],
        "status": "consistent" if targets and all(row["status"] == "consistent" for row in targets) else "not_installed",
        "targets": targets, "activation": "next_host_start", "host_discovery": "not_measured", "network_called": False,
    }
    return serialize_envelope(result, _native_obligations("HOST_SKILL_FILES_OBSERVED"))


def execute_native_install(
    plan: Mapping[str, Any], project_root: Path, *, approve: str, operation: str = "install",
) -> dict[str, Any]:
    """Commit whole directories; caught failures restore the transaction preimage."""
    preview = preview_native_install(plan, project_root, operation=operation)
    changes = [row for row in preview["targets"] if row["effect"] != "unchanged"]
    # Replaying a completed command is read-only; no new approval is needed.
    if preview["status"] == "ready" and not changes:
        return serialize_envelope(
            {"status": "unchanged", "preview_digest": preview["preview_digest"], "approval_required": False, "readback": readback_native_install(plan, project_root)},
            _native_obligations("HOST_SKILL_NO_MUTATION_NEEDED"),
        )
    if preview["preview_digest"] != approve:
        raise SkillHubContractError("HOST_SKILL_APPROVAL_STALE", "Source/target preimage changed; review a fresh preview")
    if preview["status"] != "ready":
        raise SkillHubContractError("HOST_SKILL_CONFLICT", "Preview conflicts block the entire transaction")
    project = _native_path(project_root.expanduser().absolute())
    root = Path(preview["host_root"])
    # A project-local lock serializes cooperating installers without touching CAS.
    guard = _native_path(project / ".gravity-native-install.lock")
    try:
        guard.mkdir()
    except FileExistsError as exc:
        raise SkillHubContractError("HOST_SKILL_INSTALL_BUSY", "Project installation is locked; inspect interrupted transactions before retrying") from exc
    staging = None
    clean = True
    created: list[Path] = []
    completed: list[tuple] = []
    try:
        staging = Path(tempfile.mkdtemp(prefix=".gravity-native-", dir=project))
        (staging / "preview.json").write_text(json.dumps(preview), encoding="utf-8")
        _stage_native(changes, operation, staging)
        if preview_native_install(plan, project_root, operation=operation) != preview:
            raise SkillHubContractError("HOST_SKILL_APPROVAL_STALE", "Preimages changed before commit")
        try:
            _commit_native(changes, operation, root, staging, created, completed)
            readback = _transaction_readback(plan, project_root, operation, completed)
        except BaseException:
            clean = False
            _rollback_native(completed, operation)
            for directory in reversed(created):
                directory.rmdir()
            clean = True
            raise
    finally:
        # Retain backups and guard on rollback conflict or abrupt process death.
        # They are outside discovery; preview.json records recovery destinations.
        if clean:
            if staging is not None:
                _native_path(staging)
                if staging.parent != project:
                    raise SkillHubContractError("HOST_SKILL_PATH_INVALID", "Invalid staging cleanup boundary")
                shutil.rmtree(staging)
            guard.rmdir()
    return serialize_envelope(
        {"status": "installed" if operation == "install" else "uninstalled", "preview_digest": approve, "readback": readback},
        _native_obligations("HOST_SKILL_MUTATION_READBACK", MutationState.CONFIRMED),
    )


def _stage_native(changes: list[dict], operation: str, staging: Path) -> None:
    if operation != "install":
        return
    # Stage bytes outside discovery; never execute content-package code.
    for index, row in enumerate(changes):
        staged = staging / str(index)
        staged.mkdir()
        source = Path(row["source_directory"])
        for file in row["expected"]["files"]:
            destination = staged / file["path"]
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(_native_path(source / file["path"]).read_bytes())
        if _native_snapshot(staged) != row["expected"]:
            raise SkillHubContractError("HOST_SKILL_SOURCE_CHANGED", "Source changed while staging")
        (staging / f"{index}.json").write_text(row["ownership_content"], encoding="utf-8", newline="")


def _commit_native(changes, operation, root, staging, created, completed):
    for directory in (root.parent, root):
        _native_path(directory)
        if not directory.exists():
            directory.mkdir()
            created.append(directory)
    for index, row in enumerate(changes):
        target = _native_path(Path(row["target_directory"]))
        owner = _native_path(Path(row["ownership_path"]))
        ownership = _ownership_bytes(owner)
        if _native_snapshot(target) != row["target_preimage"] or (
            hashlib.sha256(ownership).hexdigest() if ownership is not None else None
        ) != row["ownership_preimage_sha256"]:
            raise SkillHubContractError("HOST_SKILL_APPROVAL_STALE", "Target changed during commit")
        staged = staging / str(index)
        receipt = staging / f"{index}.json"
        if operation == "install":
            _native_rename(staged, target)
            completed.append((row, staged, receipt))
            _native_rename(receipt, owner)
        else:
            _native_rename(target, staged)
            completed.append((row, staged, receipt))
            _native_rename(owner, receipt)


def _transaction_readback(plan, project_root, operation, completed):
    readback = readback_native_install(plan, project_root)
    if operation == "uninstall":
        for row, staged, receipt in completed:
            if _native_snapshot(staged) != row["expected"] or _ownership_bytes(receipt) != row["ownership_content"].encode():
                raise SkillHubContractError("HOST_SKILL_READBACK_FAILED", "Removed files changed during commit; restore instead of deleting")
    wanted = "consistent" if operation == "install" else "absent"
    if any(row["status"] != wanted for row in readback["targets"]):
        raise SkillHubContractError("HOST_SKILL_READBACK_FAILED", "Native readback differs from approved transaction")
    return readback


def _native_rename(source: Path, target: Path) -> None:
    _native_path(source)
    _native_path(target)
    if target.exists():
        raise SkillHubContractError("HOST_SKILL_APPROVAL_STALE", "Rename target already exists")
    if os.name == "nt":
        source.rename(target)
        return
    # POSIX rename can overwrite an empty directory created after preimage check.
    # Require the platform's atomic no-replace operation, never emulate overwrite.
    import ctypes
    import sys

    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform == "darwin":
        rename = libc.renamex_np
        rename.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        result = rename(os.fsencode(source), os.fsencode(target), 4)
    elif hasattr(libc, "renameat2"):
        rename = libc.renameat2
        rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        result = rename(-100, os.fsencode(source), -100, os.fsencode(target), 1)
    else:
        raise SkillHubContractError("HOST_SKILL_PATH_INVALID", "Atomic no-replace rename is unavailable on this platform")
    if result:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))


def _rollback_native(completed: list[tuple], operation: str) -> None:
    for row, staged, receipt in reversed(completed):
        target = _native_path(Path(row["target_directory"]))
        owner = _native_path(Path(row["ownership_path"]))
        if operation == "install":
            if _native_snapshot(target) != row["expected"]:
                raise SkillHubContractError("HOST_SKILL_ROLLBACK_CONFLICT", "Local edits prevent rollback; preserve target and recovery staging")
            _native_rename(target, staged)
            if _ownership_bytes(owner) == row["ownership_content"].encode():
                _native_rename(owner, receipt)
        else:
            if target.exists() or (owner.exists() and receipt.exists()):
                raise SkillHubContractError("HOST_SKILL_ROLLBACK_CONFLICT", "New local files prevent rollback; preserve recovery staging")
            _native_rename(staged, target)
            if receipt.exists():
                _native_rename(receipt, owner)
