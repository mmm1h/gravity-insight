"""CLI registration and dispatch for Stage A static Skill control-plane actions."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .skill_hub_client import SkillHubClient
from .skill_hub_state import read_json


def add_skill_hub_actions(actions: Any) -> None:
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

    for parser in (sync, search, resolve, lock, fetch, install, update, verify, audit):
        parser.set_defaults(network_required=False, _gravity_handler=dispatch)


def add_hub_show_options(parser: Any) -> None:
    parser.add_argument("--state-root")
    parser.add_argument("--cas-root")


def dispatch(args: Any, _object_input: Any) -> dict[str, Any]:
    client = SkillHubClient(args.state_root, cas_root=args.cas_root)
    command = args.skills_command
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
    return client.audit()


def hub_show(args: Any) -> dict[str, Any]:
    return SkillHubClient(args.state_root, cas_root=args.cas_root).show(args.skill)


def _local(parser: Any) -> None:
    parser.add_argument("--state-root", required=True)
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


__all__ = ["add_hub_show_options", "add_skill_hub_actions", "dispatch", "hub_show"]
