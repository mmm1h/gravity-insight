"""Deterministic, installation-state-free Stage A project locks and plans."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import __version__
from .agent_runtime_contracts import (
    AgentRuntimeContractError,
    canonical_digest,
    validate_schema,
)
from .runtime_compatibility import normalized_version, runtime_satisfies, runtime_within
from .skill_contract import skill_artifact
from .skill_hub_archive import validate_wheel_file
from .skill_hub_contract import SkillHubContractError, artifact_path


SKILLS_LOCK_SCHEMA_VERSION = "gravity.skills-lock.v1"
TRUSTED_LOCK_SCHEMA_VERSION = "gravity.trusted-packs-lock.v1"
INSTALL_PLAN_SCHEMA_VERSION = "gravity.trusted-pack-install-plan.v1"
_SKILLS_LOCK_SCHEMA = "skills-lock-v1.schema.json"
_TRUSTED_LOCK_SCHEMA = "trusted-packs-lock-v1.schema.json"
_INSTALL_PLAN_SCHEMA = "trusted-pack-install-plan-v1.schema.json"
_LOCAL_FIELDS = frozenset(
    {
        "installed_at",
        "last_verified_at",
        "local_path",
        "cache_path",
        "downloaded_at",
        "health",
    }
)


def build_skills_lock(
    index: Mapping[str, Any],
    source: Mapping[str, Any],
    requested: Sequence[str],
    *,
    runtime_version: str = __version__,
) -> dict[str, Any]:
    selected_runtime = normalized_version(runtime_version)
    identities = _requested(requested, "skill")
    entries: list[dict[str, Any]] = []
    for identity in identities:
        if skill_artifact(identity) is not None:
            raise SkillHubContractError(
                "HUB_BUILTIN_COLLISION", "Hub lock cannot override a Built-in Skill"
            )
        entry = index["skills"].get(identity)
        if entry is None:
            raise SkillHubContractError("HUB_SKILL_MISSING", "Exact Hub Skill is missing")
        manifest = entry["manifest"]
        if not runtime_satisfies(selected_runtime, manifest["runtime_requires"]):
            raise SkillHubContractError(
                "HUB_RUNTIME_INCOMPATIBLE", "Hub Skill does not support this Runtime"
            )
        entries.append(_skill_lock_entry(entry))
    body = {
        "artifact_kind": "skills_lock",
        "schema_version": SKILLS_LOCK_SCHEMA_VERSION,
        "source": _source_reference(source, index["digest"]),
        "runtime_version": selected_runtime,
        "requested": identities,
        "skills": sorted(entries, key=lambda item: item["skill_uri"]),
    }
    return compile_skills_lock({**body, "lock_digest": canonical_digest(body)})


def compile_skills_lock(value: Mapping[str, Any]) -> dict[str, Any]:
    contract = _contract(value, _SKILLS_LOCK_SCHEMA, "SKILLS_LOCK_INVALID")
    _reject_local_fields(contract)
    _validate_source_reference(contract["source"])
    identities = [item["skill_uri"] for item in contract["skills"]]
    if (
        contract["requested"] != sorted(contract["requested"])
        or identities != sorted(identities)
        or len(identities) != len(set(identities))
        or set(identities) != set(contract["requested"])
    ):
        raise SkillHubContractError(
            "SKILLS_LOCK_INVALID", "Skill lock identities are not exact and deterministic"
        )
    for item in contract["skills"]:
        artifact_path(item["artifact_path"])
        _validate_dependencies(item["dependencies"])
        try:
            compatible = runtime_satisfies(
                contract["runtime_version"], item["runtime_requires"]
            )
        except ValueError as exc:
            raise SkillHubContractError(
                "SKILLS_LOCK_INVALID", "Skill lock runtime range is invalid"
            ) from exc
        if not compatible:
            raise SkillHubContractError(
                "HUB_RUNTIME_INCOMPATIBLE", "Locked Skill is incompatible"
            )
    _digest(contract, "SKILLS_LOCK_DIGEST_MISMATCH")
    return contract


def build_trusted_packs_lock(
    index: Mapping[str, Any],
    source: Mapping[str, Any],
    requested: Sequence[str],
    *,
    runtime_version: str = __version__,
) -> dict[str, Any]:
    selected_runtime = normalized_version(runtime_version)
    identities = _requested(requested, "trusted pack")
    entries: list[dict[str, Any]] = []
    for identity in identities:
        entry = index["trusted_packs"].get(identity)
        if entry is None:
            raise SkillHubContractError(
                "HUB_TRUSTED_PACK_MISSING", "Exact Trusted Pack is missing"
            )
        descriptor = entry["descriptor"]
        compatibility = descriptor["runtime_compatibility"]
        try:
            compatible = runtime_within(
                selected_runtime,
                compatibility["minimum"],
                compatibility["maximum"],
            )
        except ValueError as exc:
            raise SkillHubContractError(
                "TRUSTED_PACK_LOCK_INVALID", "Runtime compatibility is invalid"
            ) from exc
        if not compatible:
            raise SkillHubContractError(
                "HUB_RUNTIME_INCOMPATIBLE", "Trusted Pack does not support this Runtime"
            )
        entries.append(_trusted_lock_entry(entry))
    body = {
        "artifact_kind": "trusted_packs_lock",
        "schema_version": TRUSTED_LOCK_SCHEMA_VERSION,
        "source": _source_reference(source, index["digest"]),
        "runtime_version": selected_runtime,
        "requested": identities,
        "packs": sorted(entries, key=lambda item: item["pack_id"]),
    }
    return compile_trusted_packs_lock(
        {**body, "lock_digest": canonical_digest(body)}
    )


def compile_trusted_packs_lock(value: Mapping[str, Any]) -> dict[str, Any]:
    contract = _contract(value, _TRUSTED_LOCK_SCHEMA, "TRUSTED_PACK_LOCK_INVALID")
    _reject_local_fields(contract)
    _validate_source_reference(contract["source"])
    identities = [item["pack_id"] for item in contract["packs"]]
    if (
        contract["requested"] != sorted(contract["requested"])
        or identities != sorted(identities)
        or len(identities) != len(set(identities))
        or set(identities) != set(contract["requested"])
    ):
        raise SkillHubContractError(
            "TRUSTED_PACK_LOCK_INVALID",
            "Trusted Pack lock identities are not exact and deterministic",
        )
    for item in contract["packs"]:
        artifact_path(item["artifact_path"])
        compatibility = item["runtime_compatibility"]
        if set(compatibility) != {"minimum", "maximum"}:
            raise SkillHubContractError(
                "TRUSTED_PACK_LOCK_INVALID", "Runtime compatibility fields changed"
            )
        try:
            compatible = runtime_within(
                contract["runtime_version"],
                compatibility["minimum"],
                compatibility["maximum"],
            )
        except ValueError as exc:
            raise SkillHubContractError(
                "TRUSTED_PACK_LOCK_INVALID", "Runtime compatibility is invalid"
            ) from exc
        if not compatible:
            raise SkillHubContractError(
                "HUB_RUNTIME_INCOMPATIBLE", "Locked Trusted Pack is incompatible"
            )
        for field in ("allowed_groups", "operators", "models"):
            _sorted_strings(item[field], field)
        expected_groups = {
            *({"gravity.operators"} if item["operators"] else set()),
            *({"gravity.models"} if item["models"] else set()),
        }
        if set(item["allowed_groups"]) != expected_groups:
            raise SkillHubContractError(
                "TRUSTED_PACK_LOCK_INVALID", "Locked allowed groups changed"
            )
    _digest(contract, "TRUSTED_PACK_LOCK_DIGEST_MISMATCH")
    return contract


def build_trusted_pack_install_plan(
    lock: Mapping[str, Any], wheel_paths: Mapping[str, str | Path]
) -> dict[str, Any]:
    selected = compile_trusted_packs_lock(lock)
    if set(wheel_paths) != set(selected["requested"]):
        raise SkillHubContractError(
            "TRUSTED_PACK_PLAN_INVALID", "Installer Plan wheel set is incomplete"
        )
    actions = sorted([
        _install_action(item, Path(wheel_paths[item["pack_id"]]))
        for item in selected["packs"]
    ], key=lambda item: item["action_id"])
    body = {
        "artifact_kind": "trusted_pack_install_plan",
        "schema_version": INSTALL_PLAN_SCHEMA_VERSION,
        "installation_owner": "external_installer",
        "activation": "runtime_restart_required",
        "lock_digest": selected["lock_digest"],
        "actions": actions,
        "network_called": False,
    }
    return compile_trusted_pack_install_plan(
        {**body, "plan_digest": canonical_digest(body)}
    )


def compile_trusted_pack_install_plan(value: Mapping[str, Any]) -> dict[str, Any]:
    contract = _contract(value, _INSTALL_PLAN_SCHEMA, "TRUSTED_PACK_PLAN_INVALID")
    identities = [item["action_id"] for item in contract["actions"]]
    if identities != sorted(identities) or len(identities) != len(set(identities)):
        raise SkillHubContractError(
            "TRUSTED_PACK_PLAN_INVALID", "Installer Plan actions are not deterministic"
        )
    for item in contract["actions"]:
        path = Path(item["wheel_path"])
        if (
            not path.is_absolute()
            or path.suffix.casefold() != ".whl"
            or item["action_id"] != f"install-{item['wheel_sha256'][:12]}"
        ):
            raise SkillHubContractError(
                "TRUSTED_PACK_PLAN_INVALID", "Installer Plan wheel path is not exact"
            )
        _sorted_strings(item["allowed_groups"], "allowed groups")
    _digest(contract, "TRUSTED_PACK_PLAN_DIGEST_MISMATCH", field="plan_digest")
    return contract


def _skill_lock_entry(entry: Mapping[str, Any]) -> dict[str, Any]:
    manifest = entry["manifest"]
    return {
        "skill_uri": entry["skill_uri"],
        "manifest_digest": entry["package"]["manifest_digest"],
        "package_digest": entry["package"]["package_digest"],
        "archive_sha256": entry["archive"]["sha256"],
        "artifact_path": entry["archive"]["path"],
        "artifact_size": entry["archive"]["size_bytes"],
        "runtime_requires": manifest["runtime_requires"],
        "dependencies": {
            "journeys": sorted(manifest["covers_journeys"]),
            "capabilities": sorted(
                copy.deepcopy(manifest["capability_dependencies"]),
                key=_capability_key,
            ),
            "semantics": sorted(manifest["semantic_dependencies"]),
            "operators": sorted(manifest["operator_dependencies"]),
            "models": sorted(manifest["model_dependencies"]),
            "context": {
                "required": sorted(manifest["context_dependencies"]["required"]),
                "optional": sorted(manifest["context_dependencies"]["optional"]),
            },
        },
    }


def _trusted_lock_entry(entry: Mapping[str, Any]) -> dict[str, Any]:
    descriptor = entry["descriptor"]
    return {
        "pack_id": entry["pack_id"],
        "descriptor_digest": entry["descriptor_digest"],
        "distribution": descriptor["distribution"],
        "version": descriptor["version"],
        "wheel_sha256": descriptor["wheel_sha256"],
        "artifact_path": entry["archive"]["path"],
        "artifact_size": entry["archive"]["size_bytes"],
        "runtime_compatibility": copy.deepcopy(descriptor["runtime_compatibility"]),
        "allowed_groups": copy.deepcopy(descriptor["allowed_groups"]),
        "operators": copy.deepcopy(descriptor["operators"]),
        "models": copy.deepcopy(descriptor["models"]),
    }


def _source_reference(source: Mapping[str, Any], index_digest: str) -> dict[str, str]:
    result = {
        "source_id": str(source["source_id"]),
        "transport": str(source["transport"]),
        "source_descriptor_digest": str(source["source_descriptor_digest"]),
        "source_revision": str(source["source_revision"]),
        "index_digest": index_digest,
    }
    _validate_source_reference(result)
    return result


def _validate_source_reference(value: Mapping[str, Any]) -> None:
    if set(value) != {
        "source_id",
        "transport",
        "source_descriptor_digest",
        "source_revision",
        "index_digest",
    }:
        raise SkillHubContractError("HUB_LOCK_SOURCE_INVALID", "Lock source fields changed")
    if value["transport"] not in {"git", "static_https"}:
        raise SkillHubContractError("HUB_LOCK_SOURCE_INVALID", "Lock transport changed")
    if not all(isinstance(value[name], str) and value[name] for name in value):
        raise SkillHubContractError("HUB_LOCK_SOURCE_INVALID", "Lock source is invalid")
    if not _hex_digest(value["index_digest"]) or not _hex_digest(
        value["source_descriptor_digest"]
    ):
        raise SkillHubContractError("HUB_LOCK_SOURCE_INVALID", "Index digest is invalid")


def _install_action(item: Mapping[str, Any], path: Path) -> dict[str, Any]:
    selected = validate_wheel_file(
        path,
        expected_sha256=item["wheel_sha256"],
        expected_size=item["artifact_size"],
    )
    return {
        "action_id": f"install-{item['wheel_sha256'][:12]}",
        "effect": "install_exact_wheel",
        "pack_id": item["pack_id"],
        "distribution": item["distribution"],
        "version": item["version"],
        "wheel_sha256": item["wheel_sha256"],
        "descriptor_digest": item["descriptor_digest"],
        "wheel_path": str(selected),
        "allowed_groups": copy.deepcopy(item["allowed_groups"]),
    }


def _requested(values: Sequence[str], label: str) -> list[str]:
    if isinstance(values, (str, bytes)) or not values:
        raise SkillHubContractError("HUB_RESOLUTION_INVALID", f"Exact {label} IDs are required")
    if any(not isinstance(item, str) or not item for item in values):
        raise SkillHubContractError("HUB_RESOLUTION_INVALID", f"Exact {label} IDs are invalid")
    selected = sorted(values)
    if len(selected) != len(set(selected)):
        raise SkillHubContractError("HUB_RESOLUTION_INVALID", f"Exact {label} IDs are invalid")
    return selected


def _contract(value: Mapping[str, Any], schema: str, reason: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise SkillHubContractError(reason, "Contract must be an object")
    contract = copy.deepcopy(dict(value))
    try:
        validate_schema(contract, schema, reason)
    except AgentRuntimeContractError as exc:
        raise SkillHubContractError(reason, str(exc)) from exc
    return contract


def _digest(contract: Mapping[str, Any], reason: str, *, field: str = "lock_digest") -> None:
    body = copy.deepcopy(dict(contract))
    actual = body.pop(field)
    if actual != canonical_digest(body):
        raise SkillHubContractError(reason, "Contract digest changed")


def _reject_local_fields(value: Any) -> None:
    if isinstance(value, Mapping):
        if set(value).intersection(_LOCAL_FIELDS):
            raise SkillHubContractError(
                "HUB_LOCK_LOCAL_STATE", "Project lock contains installation-local state"
            )
        for item in value.values():
            _reject_local_fields(item)
    elif isinstance(value, list):
        for item in value:
            _reject_local_fields(item)


def _validate_dependencies(value: Mapping[str, Any]) -> None:
    expected = {
        "journeys",
        "capabilities",
        "semantics",
        "operators",
        "models",
        "context",
    }
    if not isinstance(value, Mapping) or set(value) != expected:
        raise SkillHubContractError(
            "SKILLS_LOCK_INVALID", "Skill dependency fields changed"
        )
    if not isinstance(value["context"], Mapping) or set(value["context"]) != {
        "required",
        "optional",
    }:
        raise SkillHubContractError(
            "SKILLS_LOCK_INVALID", "Skill Context dependency fields changed"
        )
    for field in ("journeys", "semantics", "operators", "models"):
        _sorted_strings(value[field], field)
    for field in ("required", "optional"):
        _sorted_strings(value["context"][field], field)
    capabilities = value["capabilities"]
    if not isinstance(capabilities, list):
        raise SkillHubContractError(
            "SKILLS_LOCK_INVALID", "Skill Capability dependencies changed"
        )
    keys = [_capability_key(item) for item in capabilities]
    if keys != sorted(keys) or len(keys) != len(set(keys)):
        raise SkillHubContractError(
            "SKILLS_LOCK_INVALID", "Skill Capability dependencies are not deterministic"
        )


def _capability_key(value: Any) -> tuple[str, ...]:
    fields = (
        "identity_kind",
        "selector",
        "contract_version",
        "minimum_trust",
        "completeness",
        "data_quality",
    )
    if not isinstance(value, Mapping) or set(value) != set(fields):
        raise SkillHubContractError(
            "SKILLS_LOCK_INVALID", "Skill Capability dependency fields changed"
        )
    selected = tuple(value[field] for field in fields)
    if (
        any(not isinstance(item, str) or not item for item in selected)
        or value["identity_kind"] not in {"operation", "product", "composite"}
        or value["minimum_trust"] not in {"stable", "degraded"}
        or value["completeness"] not in {"complete", "prefix", "unknown"}
        or value["data_quality"] not in {"pass", "warn", "unknown"}
    ):
        raise SkillHubContractError(
            "SKILLS_LOCK_INVALID", "Skill Capability dependency is invalid"
        )
    return selected


def _sorted_strings(
    values: Any, label: str, *, require_sorted: bool = True
) -> None:
    if (
        not isinstance(values, list)
        or any(not isinstance(item, str) or not item for item in values)
        or len(values) != len(set(values))
        or (require_sorted and values != sorted(values))
    ):
        raise SkillHubContractError(
            "HUB_LOCK_INVALID", f"Locked {label} values are not deterministic"
        )


def _hex_digest(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


__all__ = [
    "INSTALL_PLAN_SCHEMA_VERSION",
    "SKILLS_LOCK_SCHEMA_VERSION",
    "TRUSTED_LOCK_SCHEMA_VERSION",
    "build_skills_lock",
    "build_trusted_pack_install_plan",
    "build_trusted_packs_lock",
    "compile_skills_lock",
    "compile_trusted_pack_install_plan",
    "compile_trusted_packs_lock",
]
