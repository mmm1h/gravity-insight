"""Verified native Skill plans and explicit project-scope file installation."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import shlex
import shutil
import stat
import tempfile
from pathlib import Path
from typing import Any, Mapping

from .agent_runtime_contracts import (
    AgentRuntimeContractError,
    canonical_digest,
    validate_schema,
)
from .skill_hub_contract import SkillHubContractError
from .skill_hub_locks import build_skills_lock, compile_skills_lock
from .skill_hub_paths import assert_unlinked_path, is_reparse
from .skill_maintenance import maintenance_status
from .skill_seed import read_bundled_skill_seed, validate_bundled_skill_seed


def build_host_install_plan(
    client: Any,
    host: str,
    host_root: str | Path,
    content: bytes | None = None,
    *,
    selection: Mapping[str, Any] | None = None,
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
    entries = _selected_entries(
        validated, selection, client.runtime_version, client.state_root
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


def _selected_entries(
    validated: Mapping[str, Any],
    selection: Mapping[str, Any] | None,
    runtime_version: str,
    state_root: Path,
) -> list[dict[str, Any]]:
    entries = sorted(
        validated["agent_index"]["skills"], key=lambda value: value["skill_uri"]
    )
    if selection is None:
        return entries
    lock = compile_skills_lock(selection)
    remedy = _selection_remedy(
        lock, validated["source"]["source_id"], state_root
    )
    if lock["runtime_version"] != runtime_version:
        raise SkillHubContractError(
            "HUB_RUNTIME_INCOMPATIBLE",
            "Project lock runtime_version does not match this Runtime." + remedy,
        )
    index = validated["index"]
    for identity in lock["requested"]:
        if identity not in index["skills"]:
            raise SkillHubContractError(
                "HOST_SKILL_UNAVAILABLE",
                f"Locked URI {identity} is unavailable in the active seed." + remedy,
            )
    source = validated["source"]
    expected = build_skills_lock(
        index,
        {
            "source_id": source["source_id"],
            "transport": source["transport"],
            "source_descriptor_digest": validated["source_descriptor_digest"],
            "source_revision": source["https"]["source_revision"],
        },
        lock["requested"],
        runtime_version=runtime_version,
    )
    if lock["source"] != expected["source"]:
        raise SkillHubContractError(
            "HUB_SOURCE_SNAPSHOT_CHANGED",
            "Project lock source/index reference or digest mismatch." + remedy,
        )
    # Check every selected Runtime record before staging any Agent projection.
    for actual, wanted in zip(lock["skills"], expected["skills"]):
        changed = sorted(key for key in wanted if actual[key] != wanted[key])
        if changed:
            raise SkillHubContractError(
                "HOST_SKILL_LOCK_MISMATCH",
                f"Locked Skill {actual['skill_uri']} digest/metadata mismatch "
                f"({', '.join(changed)}); exact package unavailable in active seed."
                + remedy,
            )
    selected = [item for item in entries if item["skill_uri"] in lock["requested"]]
    for item in selected:
        package = index["skills"][item["skill_uri"]]["package"]
        if any(
            item[field] != package[field]
            for field in ("manifest_digest", "package_digest")
        ):
            raise SkillHubContractError(
                "HOST_SKILL_LOCK_MISMATCH",
                "Agent projection manifest/package digest mismatch." + remedy,
            )
    return selected


def _selection_remedy(
    lock: Mapping[str, Any], source_id: str, state_root: Path
) -> str:
    def command(*arguments: str) -> str:
        values = ["gravity", "skills", *arguments, "--state-root", str(state_root)]
        if os.name == "nt":
            return "gravity skills " + " ".join(
                "'" + value.replace("'", "''") + "'" for value in values[2:]
            )
        return shlex.join(values)

    relock = command(
        "lock", "--source-id", source_id,
        "--output", "gravity.skills.next.lock.json",
        *(value for identity in lock["requested"] for value in ("--skill", identity)),
    )
    return (
        " No Host Skills were staged. This API only serves the active bundled "
        "seed, not arbitrary historical Agent packages. Preserve the old lock "
        "and CAS with its matching Runtime/seed, or explicitly adopt the current "
        f"bundled source: run `{command('bootstrap')}`, then `{relock}` "
        "and review the new lock before retrying --lock. If a URI is absent, "
        f"first run `{command('list')}` and explicitly "
        "choose an available exact URI. No automatic fallback or lock rewrite."
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
    try:
        root_metadata = target.lstat()
    except FileNotFoundError:
        return "absent", None
    except OSError:
        return "unknown", None
    if target.is_symlink() or is_reparse(root_metadata) or not target.is_dir():
        return "conflict", None
    try:
        observed = _bounded_target_files(target)
    except OSError:
        return "unknown", None
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


def _bounded_target_files(target: Path, *, directories: list[str] | None = None) -> list[dict[str, Any]] | None:
    rows: list[dict[str, Any]] = []
    pending = [target]
    count = 0
    # Bound traversal before descent; never enumerate a linked subtree.
    while pending:
        with os.scandir(pending.pop()) as children:
            for child in children:
                count += 1
                if count > 64:
                    return None
                path = Path(child.path)
                metadata = path.lstat()
                if path.is_symlink() or is_reparse(metadata):
                    return None
                if stat.S_ISDIR(metadata.st_mode):
                    if directories is not None:
                        directories.append(path.relative_to(target).as_posix())
                    pending.append(path)
                    continue
                if not _bounded_regular_file(metadata):
                    return None
                content = path.read_bytes()
                rows.append({
                    "path": path.relative_to(target).as_posix(),
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "size_bytes": len(content),
                })
    return sorted(rows, key=lambda row: Path(row["path"]))


def inspect_host_skills(
    entries: list[dict[str, Any]], *, project_root: Path, home: Path,
    packages: Mapping[str, Mapping[str, bytes]] | None = None,
) -> list[dict[str, Any]]:
    """Compare only known bundle targets, without staging or host activation."""
    scopes = []
    for host, directory in (("codex", ".agents"), ("claude", ".claude")):
        for scope, base in (("user", home), ("project", project_root)):
            root = base / directory / "skills"
            label = f"<{scope}>/{directory}/skills"
            try:
                assert_unlinked_path(root, reason="HOST_SKILL_PATH_INVALID", label="Host root")
                root_status = "present" if stat.S_ISDIR(root.lstat().st_mode) else "invalid"
            except FileNotFoundError:
                root_status = "missing"
            except (OSError, SkillHubContractError):
                root_status = "unreadable_or_linked"
            skills = []
            for entry in entries:
                state, digest = (
                    _host_target_state(root / entry["directory"], entry)
                    if root_status in {"present", "missing"} else ("unknown", None)
                )
                status = {
                    "unchanged": "installed_consistent", "absent": "missing",
                    "conflict": "local_override_conflict", "unknown": "unknown",
                }[state]
                target = root / entry["directory"]
                details = _native_details(target, entry, host, packages) if state in {"unchanged", "conflict"} else {}
                next_action = {
                    "missing": "Review host-install-plan for this scope, then explicitly install with the native installer; a plan alone installs nothing.",
                    "local_override_conflict": "Compare local files with the locked bundle; preserve local edits and explicitly reconcile before installation.",
                    "unknown": "Check access and remove linked-path ambiguity for this exact target before retrying.",
                    "installed_consistent": "Check host enablement and obtain a host discovery observation; file consistency does not prove loading.",
                }[status]
                if details.get("missing_files"):
                    next_action = "Restore the listed missing_files from the reviewed host-install-plan with the native installer; preserve local edits in remaining files."
                next_action = details.get("policy_next_action") or details.get("version_next_action") or next_action
                skills.append({
                    "skill_uri": entry["skill_uri"],
                    "target": f"{label}/{entry['directory']}",
                    "status": status, "observed_digest": digest,
                    "expected_digest": canonical_digest(sorted(entry["files"], key=lambda row: Path(row["path"]))),
                    **details,
                    "next_action": next_action,
                })
            scopes.append({
                "host": host, "scope": scope, "root": label,
                "root_status": root_status, "skills": skills,
                "enablement": "unknown", "discovery": "unknown",
            })
    return scopes


def _native_details(
    target: Path, entry: Mapping[str, Any], host: str,
    packages: Mapping[str, Mapping[str, bytes]] | None,
) -> dict[str, Any]:
    try:
        assert_unlinked_path(target, reason="HOST_SKILL_PATH_INVALID", label="Host target")
        rows = _bounded_target_files(target) if target.is_dir() and not target.is_symlink() else None
    except (OSError, SkillHubContractError):
        return {}
    if rows is None:
        return {}
    paths = {row["path"] for row in rows}
    result: dict[str, Any] = {
        "missing_files": sorted(row["path"] for row in entry["files"] if row["path"] not in paths),
        "version_match": "unknown", "implicit_invocation": "unknown",
    }
    try:
        if "references/SCHEMA.json" in paths:
            result.update(_native_version(target, entry))
        if host == "claude" and packages and "SKILL.md" in paths:
            result.update(_native_policy(target, packages[entry["skill_uri"]]["SKILL.md"]))
    except (OSError, ValueError):
        pass
    return result


def _native_version(target: Path, entry: Mapping[str, Any]) -> dict[str, Any]:
    schema = json.loads((target / "references/SCHEMA.json").read_bytes())
    if not isinstance(schema, dict) or not isinstance(schema.get("skill_uri"), str):
        return {}
    observed = schema["skill_uri"]
    if observed.rsplit("@", 1)[0] != entry["skill_uri"].rsplit("@", 1)[0]:
        return {}
    if observed == entry["skill_uri"]:
        return {"version_match": "match"}
    return {
        "version_match": "mismatch",
        "version_next_action": "Installed declaration targets another Skill version; preserve it and explicitly reconcile with the selected lock and matching seed.",
    }


def _native_policy(target: Path, expected_content: bytes) -> dict[str, Any]:
    expected = expected_content.split(b"\n---\n", 1)[0]
    content = (target / "SKILL.md").read_bytes().replace(b"\r\n", b"\n")
    observed, separator, _body = content.partition(b"\n---\n")
    directive = b"\ndisable-model-invocation: true"
    # Recognize only an exact generated header plus this single policy
    # override. Other YAML remains unknown, never guessed as enabled.
    if separator and observed.count(directive) == 1 and observed.replace(directive, b"") == expected:
        return {"implicit_invocation": "disabled", "policy_next_action": "Claude's native header disables automatic invocation; explicitly review disable-model-invocation before enabling it. Manual invocation is a separate path."}
    return {}


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


def _native_path(path: Path) -> Path:
    if ".." in path.parts:
        raise SkillHubContractError("HOST_SKILL_PATH_INVALID", "Parent traversal is forbidden")
    return assert_unlinked_path(path, reason="HOST_SKILL_PATH_INVALID", label="Native Skill path")


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


def _native_selection(plan: Mapping[str, Any], project_root: Path) -> tuple[dict, Path, list]:
    selected = _compile_host_install_plan(plan)
    project = _native_path(project_root.expanduser().absolute())
    if not project.is_dir():
        raise SkillHubContractError("HOST_SKILL_PATH_INVALID", "Project root must exist")
    root = _native_path(project / (".agents" if selected["host"] == "codex" else ".claude") / "skills")
    if root in {Path.home() / ".agents/skills", Path.home() / ".claude/skills"}:
        raise SkillHubContractError("HOST_SKILL_PATH_INVALID", "User-global installation is not supported")
    validated = validate_bundled_skill_seed(read_bundled_skill_seed())
    if selected["seed_digest"] != validated["seed_digest"]:
        raise SkillHubContractError("HOST_SKILL_SEED_NOT_ACTIVE", "Plan requires the matching bundled Runtime seed")
    entries = {row["skill_uri"]: row for row in validated["agent_index"]["skills"]}
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
        reason = None
        effect = "unchanged"
        if kind == "conflicts":
            reason = "plan_contains_conflicts"
        elif observed is None and ownership is not None:
            reason = "owned_target_missing"
        elif observed is not None and observed != expected:
            reason = "local_override_conflict"
        elif operation == "uninstall":
            if observed is not None:
                if not owned:
                    reason = "unknown_ownership"
                else:
                    effect = "remove"
        elif observed is None:
            if kind != "actions":
                reason = "target_preimage_changed"
            else:
                effect = "install"
        elif kind == "actions" and not owned:
            reason = "unknown_ownership"
        elif kind == "unchanged" and item["target_preimage_digest"] != canonical_digest(observed["files"]):
            reason = "target_preimage_changed"
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
    return {**result, "preview_digest": canonical_digest(result)}


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
    return {
        "schema_version": "gravity.native-skill-readback.v1", "plan_digest": selected["plan_digest"],
        "status": "consistent" if targets and all(row["status"] == "consistent" for row in targets) else "not_installed",
        "targets": targets, "activation": "next_host_start", "host_discovery": "not_measured", "network_called": False,
    }


def execute_native_install(
    plan: Mapping[str, Any], project_root: Path, *, approve: str, operation: str = "install",
) -> dict[str, Any]:
    """Commit whole directories; caught failures restore the transaction preimage."""
    preview = preview_native_install(plan, project_root, operation=operation)
    if preview["preview_digest"] != approve:
        raise SkillHubContractError("HOST_SKILL_APPROVAL_STALE", "Source/target preimage changed; review a fresh preview")
    if preview["status"] != "ready":
        raise SkillHubContractError("HOST_SKILL_CONFLICT", "Preview conflicts block the entire transaction")
    changes = [row for row in preview["targets"] if row["effect"] != "unchanged"]
    if not changes:
        return {"status": "unchanged", "preview_digest": approve, "readback": readback_native_install(plan, project_root)}
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
        # Stage bytes outside discovery; never execute content-package code.
        for index, row in enumerate(changes):
            staged = staging / str(index)
            if operation == "install":
                staged.mkdir()
                source = Path(row["source_directory"])
                for file in row["expected"]["files"]:
                    destination = staged / file["path"]
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(_native_path(source / file["path"]).read_bytes())
                if _native_snapshot(staged) != row["expected"]:
                    raise SkillHubContractError("HOST_SKILL_SOURCE_CHANGED", "Source changed while staging")
                (staging / f"{index}.json").write_text(row["ownership_content"], encoding="utf-8", newline="")
        if preview_native_install(plan, project_root, operation=operation) != preview:
            raise SkillHubContractError("HOST_SKILL_APPROVAL_STALE", "Preimages changed before commit")
        try:
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
            readback = readback_native_install(plan, project_root)
            if operation == "uninstall":
                for row, staged, receipt in completed:
                    if _native_snapshot(staged) != row["expected"] or _ownership_bytes(receipt) != row["ownership_content"].encode():
                        raise SkillHubContractError("HOST_SKILL_READBACK_FAILED", "Removed files changed during commit; restore instead of deleting")
            wanted = "consistent" if operation == "install" else "absent"
            if any(row["status"] != wanted for row in readback["targets"]):
                raise SkillHubContractError("HOST_SKILL_READBACK_FAILED", "Native readback differs from approved transaction")
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
    return {"status": "installed" if operation == "install" else "uninstalled", "preview_digest": approve, "readback": readback}


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


__all__ = ["build_host_install_plan", "inspect_host_skills", "preview_native_install", "execute_native_install", "readback_native_install"]
