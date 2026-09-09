"""CLI registration and dispatch for Stage A static Skill control-plane actions."""

from __future__ import annotations

import os
from pathlib import Path
import shlex
import stat
from typing import Any
from types import SimpleNamespace

from .agent_runtime_contracts import canonical_digest
from .skill_hub_client import SkillHubClient
from .skill_hub_contract import SkillHubContractError
from .skill_hub_locks import compile_skills_lock
from .skill_hub_paths import assert_unlinked_path
from .skill_hub_state import read_json


def add_skill_hub_actions(actions: Any) -> None:
    listed = actions.add_parser("list", help="List Skills from synced Hub sources.")
    listed.add_argument("--maximum", type=_positive, default=100)
    _local(listed)

    show = actions.add_parser("show", help="Show one exact synced Hub Skill.")
    show.add_argument("skill")
    _local(show)

    sync = actions.add_parser("sync", help="Sync one explicit Stage A Hub Source.")
    _source(sync)
    _local(sync)

    search = actions.add_parser("search", help="Search synced Hub Skill metadata.")
    search.add_argument("query")
    search.add_argument("--maximum", type=_positive, default=20)
    _local(search)

    resolve = actions.add_parser("resolve", help="Resolve exact Skill IDs offline.")
    _requested(resolve)
    _local(resolve)

    lock = actions.add_parser("lock", help="Write an exact reproducible Skill lock.")
    _requested(lock)
    lock.add_argument("--output", required=True)
    lock.set_defaults(product_file_output=True)
    _local(lock)

    fetch = actions.add_parser("fetch", help="Fetch lock artifacts into verified CAS.")
    _source(fetch)
    fetch.add_argument("--lock", required=True)
    _local(fetch)

    install = actions.add_parser(
        "install", help="Materialize static Skills from populated local CAS."
    )
    install.add_argument("--lock", required=True)
    install.add_argument("--install-root")
    _local(install)

    update = actions.add_parser("update", help="Explicitly recompute one Skill lock.")
    _requested(update)
    update.add_argument("--output", required=True)
    update.set_defaults(product_file_output=True)
    _local(update)

    verify = actions.add_parser("verify", help="Verify a Skill lock and local CAS.")
    verify.add_argument("--lock", required=True)
    _local(verify)

    audit = actions.add_parser("audit", help="Audit synced Hub snapshots offline.")
    _local(audit)

    status = actions.add_parser(
        "status", help="Read bundled maintenance and project lock Runtime drift offline."
    )
    status.add_argument("--lock", help="Project Skill lock; defaults to workspace root or cwd.")
    status.add_argument("--diagnose", action="store_true", help="Read layered Runtime, lock and native Host diagnostics; never install.")
    _local(status, required=False)

    bootstrap = actions.add_parser(
        "bootstrap", help="Retry bundled Skill bootstrap offline."
    )
    _local(bootstrap, required=False)

    repair = actions.add_parser(
        "repair", help="Force bundled Skill validation and CAS repair offline."
    )
    _local(repair, required=False)

    host_plan = _host_install_parser(actions)

    for parser in (
        listed,
        show,
        sync,
        search,
        resolve,
        lock,
        fetch,
        install,
        update,
        verify,
        audit,
        status,
        bootstrap,
        repair,
        host_plan,
    ):
        parser.set_defaults(network_required=False, _gravity_handler=dispatch)


def dispatch(args: Any, _object_input: Any) -> dict[str, Any]:
    workspace = None
    state_root = args.state_root
    if state_root is None:
        from .workspace import load_workspace

        workspace = load_workspace()
        state_root = workspace.state_root
    command = args.skills_command
    if command == "status":
        from . import __version__

        client = SimpleNamespace(
            state_root=assert_unlinked_path(Path(state_root), reason="HUB_STATE_INVALID", label="State root"), runtime_version=__version__,
            cas=SimpleNamespace(root=Path(args.cas_root or Path(state_root) / "skill-hub-cas")),
        )
        return _maintenance_dispatch(command, client, args, workspace)
    client = SkillHubClient(state_root, cas_root=args.cas_root)
    if command == "list":
        return client.list(maximum=args.maximum)
    if command == "show":
        return client.show(args.skill)
    if command == "sync":
        return client.sync(_json(args.source), repository=args.repository)
    if command == "search":
        return client.search(args.query, maximum=args.maximum)
    if command == "resolve":
        return client.resolve(args.requested_skills, source_id=args.source_id)
    if command == "lock":
        return client.lock(
            args.requested_skills, args.output, source_id=args.source_id
        )
    if command == "fetch":
        return client.fetch(
            _json(args.lock),
            _json(args.source),
            repository=args.repository,
        )
    if command == "install":
        return client.install(_json(args.lock), install_root=args.install_root)
    if command == "update":
        return client.update(
            args.requested_skills, args.output, source_id=args.source_id
        )
    if command == "verify":
        return client.verify(_json(args.lock))
    if command in {"status", "bootstrap", "repair", "host-install-plan"}:
        return _maintenance_dispatch(command, client, args, workspace)
    return client.audit()


def _maintenance_dispatch(
    command: str, client: SkillHubClient, args: Any, workspace: Any
) -> dict[str, Any]:
    if command == "status":
        if workspace is None:
            from .workspace import load_workspace

            workspace = load_workspace()
        root = workspace.root if workspace.configured else Path.cwd()
        if args.lock is not None:
            lock_path = Path(args.lock)
        else:
            lock_path = root / "gravity.skills.lock.json"
        if getattr(args, "diagnose", False):
            from .doctor_cli import diagnose_skills

            return diagnose_skills(
                state_root=client.state_root, cas_root=client.cas.root,
                project_root=root, lock_path=lock_path,
            )
        from .skill_maintenance import maintenance_status

        result = maintenance_status(client)
        result["project_lock"] = _project_lock_status(client, lock_path)
        # This observation includes transient project state, not a persisted receipt update.
        result.pop("receipt_digest")
        return {**result, "receipt_digest": canonical_digest(result)}
    if command == "host-install-plan":
        return client.host_install_plan(
            args.host, args.host_root,
            selection=_json(args.lock) if args.lock is not None else None,
        )
    project_root = (
        workspace.root
        if workspace is not None and workspace.configured
        else None
    )
    return client.bootstrap_bundled(
        force=command == "repair",
        project_root=project_root,
    )


def _project_lock_status(client: SkillHubClient, path: Path) -> dict[str, Any]:
    path = assert_unlinked_path(
        path.expanduser(), reason="SKILLS_LOCK_INVALID", label="Project Skill lock"
    )
    result = {
        "status": "not_checked",
        "reason": "no_lock",
        "lock_path": "<project-lock>",
        "runtime_version": client.runtime_version,
        "locked_runtime_version": None,
        "next_action": None,
    }
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return result
    except OSError as exc:
        raise SkillHubContractError(
            "SKILLS_LOCK_INVALID", "Project Skill lock is unreadable"
        ) from exc
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_nlink != 1
        or not 1 <= metadata.st_size <= 1_048_576
    ):
        raise SkillHubContractError("SKILLS_LOCK_INVALID", "Project Skill lock boundary is invalid")
    try:
        lock = compile_skills_lock(read_json(path))
    except OSError as exc:
        raise SkillHubContractError(
            "SKILLS_LOCK_INVALID", "Project Skill lock is unreadable"
        ) from exc
    mismatch = lock["runtime_version"] != client.runtime_version
    result.update(
        status="mismatch" if mismatch else "match",
        reason="HUB_RUNTIME_INCOMPATIBLE" if mismatch else None,
        locked_runtime_version=lock["runtime_version"],
    )
    if mismatch:
        arguments = [
            "--state-root", "<state-root>",
            "--source-id", lock["source"]["source_id"],
            "--output", "gravity.skills.next.lock.json",
        ]
        for identity in lock["requested"]:
            arguments.extend(("--skill", identity))
        if os.name == "nt":
            rendered = " ".join("'" + value.replace("'", "''") + "'" for value in arguments)
        else:
            rendered = shlex.join(arguments)
        result["next_action"] = "gravity skills lock " + rendered
    return result


def _host_install_parser(actions: Any) -> Any:
    parser = actions.add_parser(
        "host-install-plan",
        help="Prepare verified Codex or Claude native Skill install actions.",
    )
    parser.add_argument("--host", choices=("codex", "claude"), required=True)
    parser.add_argument("--host-root", required=True)
    parser.add_argument(
        "--lock",
        help=(
            "Select exact Skills from a project lock matching this Runtime and "
            "active bundled source/index and package digests; omit to stage the "
            "full bundle. Offline; does not install or remove Host files."
        ),
    )
    _local(parser, required=False)
    return parser


def _local(parser: Any, *, required: bool = True) -> None:
    parser.add_argument("--state-root", required=required)
    parser.add_argument("--cas-root")


def _source(parser: Any) -> None:
    parser.add_argument("--source", required=True)
    parser.add_argument("--repository")


def _requested(parser: Any) -> None:
    parser.add_argument(
        "--skill", dest="requested_skills", action="append", required=True
    )
    parser.add_argument("--source-id")


def _json(value: str) -> dict[str, Any]:
    return read_json(Path(value))


def _positive(value: str) -> int:
    selected = int(value)
    if selected < 1:
        raise ValueError("value must be positive")
    return selected


__all__ = ["add_skill_hub_actions", "dispatch"]
