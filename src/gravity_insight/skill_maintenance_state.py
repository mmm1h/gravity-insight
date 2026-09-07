"""Atomic active-pointer state for bundled Skill maintenance."""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .agent_runtime_contracts import (
    AgentRuntimeContractError,
    canonical_digest,
    validate_schema,
)
from .skill_hub_contract import SkillHubContractError, compile_hub_index
from .skill_hub_locks import compile_skills_lock
from .skill_hub_state import atomic_write_json, compile_hub_snapshot, read_json


MAINTENANCE_RECEIPT_SCHEMA_VERSION = "gravity.skill-maintenance-receipt.v1"
MAINTENANCE_GENERATION_SCHEMA_VERSION = "gravity.skill-maintenance-generation.v1"
MAINTENANCE_DIRECTORY = "skill-maintenance"
MAINTENANCE_GENERATIONS_DIRECTORY = "generations"
MAINTENANCE_RECEIPT_NAME = "maintenance-receipt.json"
_RECEIPT_SCHEMA = "skill-maintenance-receipt-v1.schema.json"
_GENERATION_SCHEMA = "skill-maintenance-generation-v1.schema.json"


def build_skill_maintenance_receipt(
    *,
    status: str,
    bootstrap_checked: bool,
    active_source: Mapping[str, Any] | None,
    active_index_digest: str | None,
    active_seed_digest: str | None,
    managed_lock_digest: str | None,
    skill_count: int,
    last_attempt_at: str | None,
    last_success_at: str | None,
    network_called: bool,
    reason_codes: Sequence[str],
    update_available: bool | None,
    host_restart_required: bool,
) -> dict[str, Any]:
    body = {
        "artifact_kind": "skill_maintenance_receipt",
        "schema_version": MAINTENANCE_RECEIPT_SCHEMA_VERSION,
        "status": status,
        "bootstrap_checked": bootstrap_checked,
        "active_source": (
            copy.deepcopy(dict(active_source)) if active_source is not None else None
        ),
        "active_index_digest": active_index_digest,
        "active_seed_digest": active_seed_digest,
        "managed_lock_digest": managed_lock_digest,
        "skill_count": skill_count,
        "last_attempt_at": last_attempt_at,
        "last_success_at": last_success_at,
        "network_called": network_called,
        "reason_codes": sorted(reason_codes),
        "update_available": update_available,
        "host_restart_required": host_restart_required,
    }
    return compile_skill_maintenance_receipt(
        {**body, "receipt_digest": canonical_digest(body)}
    )


def compile_skill_maintenance_receipt(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    contract = _contract(
        value, _RECEIPT_SCHEMA, "SKILL_MAINTENANCE_RECEIPT_INVALID"
    )
    for field in ("last_attempt_at", "last_success_at"):
        if contract[field] is not None:
            _timestamp(contract[field])
    reasons = contract["reason_codes"]
    if reasons != sorted(reasons) or len(reasons) != len(set(reasons)):
        raise SkillHubContractError(
            "SKILL_MAINTENANCE_RECEIPT_INVALID",
            "Skill maintenance reason codes are not deterministic",
        )
    _maintenance_semantics(contract)
    _digest(
        contract,
        "receipt_digest",
        "SKILL_MAINTENANCE_RECEIPT_DIGEST_MISMATCH",
    )
    return contract


def not_bootstrapped_skill_maintenance_receipt() -> dict[str, Any]:
    return build_skill_maintenance_receipt(
        status="not_bootstrapped",
        bootstrap_checked=False,
        active_source=None,
        active_index_digest=None,
        active_seed_digest=None,
        managed_lock_digest=None,
        skill_count=0,
        last_attempt_at=None,
        last_success_at=None,
        network_called=False,
        reason_codes=["SKILL_BOOTSTRAP_NOT_ATTEMPTED"],
        update_available=None,
        host_restart_required=False,
    )


def build_skill_maintenance_generation(
    *,
    seed_digest: str,
    managed_lock: Mapping[str, Any],
    snapshot: Mapping[str, Any],
) -> dict[str, Any]:
    body = {
        "artifact_kind": "skill_maintenance_generation",
        "schema_version": MAINTENANCE_GENERATION_SCHEMA_VERSION,
        "seed_digest": seed_digest,
        "managed_lock": copy.deepcopy(dict(managed_lock)),
        "snapshot": copy.deepcopy(dict(snapshot)),
    }
    return compile_skill_maintenance_generation(
        {**body, "generation_digest": canonical_digest(body)}
    )


def compile_skill_maintenance_generation(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    contract = _contract(
        value,
        _GENERATION_SCHEMA,
        "SKILL_MAINTENANCE_GENERATION_INVALID",
    )
    snapshot = compile_hub_snapshot(contract["snapshot"])
    index = compile_hub_index(snapshot["index"])
    lock = compile_skills_lock(contract["managed_lock"])
    if lock["source"] != snapshot["source"]:
        raise SkillHubContractError(
            "SKILL_MAINTENANCE_GENERATION_INVALID",
            "Maintenance generation lock and snapshot source disagree",
        )
    if set(lock["requested"]) != set(index["skills"]):
        raise SkillHubContractError(
            "SKILL_MAINTENANCE_GENERATION_INVALID",
            "Maintenance generation lock and snapshot Skills disagree",
        )
    _digest(
        contract,
        "generation_digest",
        "SKILL_MAINTENANCE_GENERATION_DIGEST_MISMATCH",
    )
    return contract


def skill_maintenance_generation_path(state_root: Path, seed_digest: str) -> Path:
    if not isinstance(seed_digest, str) or not _is_full_digest(seed_digest):
        raise SkillHubContractError(
            "SKILL_MAINTENANCE_GENERATION_INVALID",
            "Maintenance generation seed digest is invalid",
        )
    return (
        state_root
        / MAINTENANCE_DIRECTORY
        / MAINTENANCE_GENERATIONS_DIRECTORY
        / f"{seed_digest}.json"
    )


def write_skill_maintenance_generation(
    state_root: Path, value: Mapping[str, Any]
) -> Path:
    selected = compile_skill_maintenance_generation(value)
    path = skill_maintenance_generation_path(state_root, selected["seed_digest"])
    atomic_write_json(path, selected)
    if compile_skill_maintenance_generation(read_json(path)) != selected:
        raise SkillHubContractError(
            "HUB_STATE_WRITE_FAILED", "Skill maintenance generation readback changed"
        )
    return path


def load_skill_maintenance_generation(
    state_root: Path, seed_digest: str
) -> dict[str, Any]:
    path = skill_maintenance_generation_path(state_root, seed_digest)
    return compile_skill_maintenance_generation(read_json(path))


def write_skill_maintenance_receipt(
    state_root: Path, value: Mapping[str, Any]
) -> Path:
    selected = compile_skill_maintenance_receipt(value)
    path = state_root / MAINTENANCE_DIRECTORY / MAINTENANCE_RECEIPT_NAME
    atomic_write_json(path, selected)
    if compile_skill_maintenance_receipt(read_json(path)) != selected:
        raise SkillHubContractError(
            "HUB_STATE_WRITE_FAILED", "Skill maintenance receipt readback changed"
        )
    return path


def _maintenance_semantics(value: Mapping[str, Any]) -> None:
    if value["network_called"]:
        _invalid_semantics("Offline Skill maintenance network boundary changed")
    if value["active_source"] is not None and not _valid_active_source(
        value["active_source"]
    ):
        _invalid_semantics("Active Skill source reference changed")
    validators: Mapping[str, Callable[[Mapping[str, Any]], bool]] = {
        "not_bootstrapped": _valid_not_bootstrapped,
        "empty": _valid_empty,
        "ready": _valid_ready,
        "degraded": _valid_degraded,
        "unavailable": _valid_unavailable,
    }
    if not validators[value["status"]](value):
        _invalid_semantics("Skill maintenance status fields disagree")


def _valid_active_source(value: Mapping[str, Any]) -> bool:
    return set(value) == {
        "source_id",
        "transport",
        "source_descriptor_digest",
        "source_revision",
    } and value["transport"] in {"git", "static_https"}


def _active_fields(value: Mapping[str, Any], *, present: bool) -> bool:
    fields = (
        value["active_source"],
        value["active_index_digest"],
        value["active_seed_digest"],
    )
    return all(item is not None for item in fields) if present else all(
        item is None for item in fields
    )


def _valid_not_bootstrapped(value: Mapping[str, Any]) -> bool:
    return (
        not value["bootstrap_checked"]
        and _active_fields(value, present=False)
        and value["managed_lock_digest"] is None
        and value["skill_count"] == 0
        and value["last_attempt_at"] is None
        and value["last_success_at"] is None
        and value["reason_codes"] == ["SKILL_BOOTSTRAP_NOT_ATTEMPTED"]
        and value["update_available"] is None
        and not value["host_restart_required"]
    )


def _valid_empty(value: Mapping[str, Any]) -> bool:
    return (
        value["bootstrap_checked"]
        and _active_fields(value, present=True)
        and value["managed_lock_digest"] is None
        and value["skill_count"] == 0
        and value["last_attempt_at"] is not None
        and value["last_success_at"] is not None
        and not value["reason_codes"]
        and isinstance(value["update_available"], bool)
    )


def _valid_ready(value: Mapping[str, Any]) -> bool:
    return (
        value["bootstrap_checked"]
        and _active_fields(value, present=True)
        and value["managed_lock_digest"] is not None
        and value["skill_count"] > 0
        and value["last_attempt_at"] is not None
        and value["last_success_at"] is not None
        and not value["reason_codes"]
        and isinstance(value["update_available"], bool)
    )


def _valid_degraded(value: Mapping[str, Any]) -> bool:
    count_and_lock_agree = (
        value["skill_count"] == 0 and value["managed_lock_digest"] is None
    ) or (value["skill_count"] > 0 and value["managed_lock_digest"] is not None)
    return (
        value["bootstrap_checked"]
        and _active_fields(value, present=True)
        and count_and_lock_agree
        and value["last_attempt_at"] is not None
        and value["last_success_at"] is not None
        and bool(value["reason_codes"])
    )


def _valid_unavailable(value: Mapping[str, Any]) -> bool:
    return (
        value["bootstrap_checked"]
        and _active_fields(value, present=False)
        and value["managed_lock_digest"] is None
        and value["skill_count"] == 0
        and value["last_attempt_at"] is not None
        and value["last_success_at"] is None
        and bool(value["reason_codes"])
        and value["update_available"] is None
        and not value["host_restart_required"]
    )


def _invalid_semantics(message: str) -> None:
    raise SkillHubContractError("SKILL_MAINTENANCE_RECEIPT_INVALID", message)


def _contract(value: Mapping[str, Any], schema: str, reason: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise SkillHubContractError(reason, "State contract must be an object")
    contract = copy.deepcopy(dict(value))
    try:
        validate_schema(contract, schema, reason)
    except AgentRuntimeContractError as exc:
        raise SkillHubContractError(reason, str(exc)) from exc
    return contract


def _digest(value: Mapping[str, Any], field: str, reason: str) -> None:
    body = copy.deepcopy(dict(value))
    actual = body.pop(field)
    if actual != canonical_digest(body):
        raise SkillHubContractError(reason, "State digest changed")


def _timestamp(value: str) -> str:
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


def _is_full_digest(value: str) -> bool:
    return len(value) == 64 and all(
        character in "0123456789abcdef" for character in value
    )


__all__ = [
    "MAINTENANCE_DIRECTORY",
    "MAINTENANCE_GENERATIONS_DIRECTORY",
    "MAINTENANCE_GENERATION_SCHEMA_VERSION",
    "MAINTENANCE_RECEIPT_NAME",
    "MAINTENANCE_RECEIPT_SCHEMA_VERSION",
    "build_skill_maintenance_generation",
    "build_skill_maintenance_receipt",
    "compile_skill_maintenance_generation",
    "compile_skill_maintenance_receipt",
    "load_skill_maintenance_generation",
    "not_bootstrapped_skill_maintenance_receipt",
    "skill_maintenance_generation_path",
    "write_skill_maintenance_generation",
    "write_skill_maintenance_receipt",
]
