"""Separate CLI surface for Stage A Trusted Pack control-plane artifacts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .skill_hub_contract import SkillHubContractError
from .skill_hub_state import atomic_write_json, read_json
from .skill_hub_locks import compile_trusted_pack_install_plan
from .trusted_pack_hub import TrustedPackHubClient


def add_trusted_pack_commands(commands: Any) -> Any:
    root = commands.add_parser(
        "trusted-packs", help="Resolve exact reviewed Team Trusted Packs."
    )
    actions = root.add_subparsers(dest="trusted_packs_command", required=True)

    resolve = actions.add_parser("resolve")
    _requested(resolve)
    _local(resolve)

    lock = actions.add_parser("lock")
    _requested(lock)
    lock.add_argument("--output", required=True)
    lock.set_defaults(product_file_output=True)
    _local(lock)

    fetch = actions.add_parser("fetch")
    fetch.add_argument("--lock", required=True)
    fetch.add_argument("--source", required=True)
    fetch.add_argument("--repository")
    _local(fetch)

    verify = actions.add_parser("verify")
    verify.add_argument("--lock", required=True)
    _local(verify)

    plan = actions.add_parser("install-plan")
    plan.add_argument("--lock", required=True)
    plan.add_argument("--output", required=True)
    plan.set_defaults(product_file_output=True)
    _local(plan)

    for parser in (resolve, lock, fetch, verify, plan):
        parser.set_defaults(network_required=False, _gravity_handler=dispatch)
    return root


def dispatch(args: Any, _object_input: Any) -> dict[str, Any]:
    client = TrustedPackHubClient(args.state_root, cas_root=args.cas_root)
    command = args.trusted_packs_command
    if command == "resolve":
        return client.resolve(args.requested_packs, source_id=args.source_id)
    if command == "lock":
        return client.lock(
            args.requested_packs, args.output, source_id=args.source_id
        )
    if command == "fetch":
        return client.fetch(
            read_json(Path(args.lock)),
            read_json(Path(args.source)),
            repository=args.repository,
        )
    if command == "verify":
        return client.verify(read_json(Path(args.lock)))
    plan = client.install_plan(read_json(Path(args.lock)))
    output = Path(args.output).absolute()
    atomic_write_json(output, plan, private=False)
    if compile_trusted_pack_install_plan(read_json(output)) != plan:
        raise SkillHubContractError(
            "TRUSTED_PACK_PLAN_WRITE_FAILED", "Installer Plan readback changed"
        )
    return {
        "schema_version": "gravity.trusted-pack-install-plan-write.v1",
        "status": "written",
        "path": str(output),
        "plan_digest": plan["plan_digest"],
        "action_count": len(plan["actions"]),
        "network_called": False,
    }


def _local(parser: Any) -> None:
    parser.add_argument("--state-root", required=True)
    parser.add_argument("--cas-root")


def _requested(parser: Any) -> None:
    parser.add_argument("--pack", dest="requested_packs", action="append", required=True)
    parser.add_argument("--source-id")


__all__ = ["add_trusted_pack_commands", "dispatch"]
