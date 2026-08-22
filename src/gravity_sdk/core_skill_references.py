"""Value-free references projected from resolved Core Skill dependencies."""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from typing import Any

from .agent_runtime_contracts import canonical_digest


def journey_reference(artifact: Mapping[str, Any]) -> dict[str, Any]:
    contract = artifact["contract"]
    return {
        "journey_id": contract["journey_id"],
        "version": contract["version"],
        "digest": artifact["digest"],
    }


def skill_reference(artifact: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if artifact is None:
        return None
    contract = artifact["contract"]
    binding = artifact.get("runtime_binding")
    if not isinstance(binding, Mapping):
        binding = {
            "resolution": "unlocked",
            "team_lock_digest": None,
            "hub_source_digest": None,
            "hub_source_reference": None,
            "trusted_pack_lock_digest": None,
            "trusted_pack_state_digest": None,
            "trusted_pack_verification_digest": None,
        }
    return {
        "uri": artifact["skill_uri"],
        "version": contract["version"],
        "manifest_digest": artifact["digest"],
        "package_digest": artifact["package_digest"],
        "resolution": binding["resolution"],
        "team_lock_digest": binding["team_lock_digest"],
        "hub_source_digest": binding["hub_source_digest"],
        "hub_source_reference": copy.deepcopy(binding["hub_source_reference"]),
        "trusted_pack_lock_digest": binding["trusted_pack_lock_digest"],
        "trusted_pack_state_digest": binding["trusted_pack_state_digest"],
        "trusted_pack_verification_digest": binding[
            "trusted_pack_verification_digest"
        ],
        "lifecycle": contract["lifecycle"],
        "readiness": contract["readiness"],
        "validation": contract["validation"],
    }


def overlay_reference(value: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    contract = value["contract"]
    return {
        "uri": contract["overlay_uri"],
        "version": contract["version"],
        "digest": value["digest"],
        "source_revision": value["source_revision"],
    }


def capability_reference(
    result: Mapping[str, Any], requirement: Mapping[str, Any], status: str
) -> dict[str, Any]:
    return {
        "identity_kind": requirement["identity_kind"],
        "selector": requirement["selector"],
        "contract_version": result.get("contract_version"),
        "contract_digest": result.get("contract_digest"),
        "trust_digest": canonical_digest(result),
        "status": status,
    }


def semantic_reference(result: Mapping[str, Any]) -> dict[str, Any]:
    definition = result.get("definition") if isinstance(result, Mapping) else None
    binding = result.get("binding") if isinstance(result, Mapping) else None
    contract = definition.get("contract") if isinstance(definition, Mapping) else None
    return {
        "uri": str(result.get("uri")),
        "version": contract.get("version") if isinstance(contract, Mapping) else None,
        "definition_digest": (
            definition.get("digest") if isinstance(definition, Mapping) else None
        ),
        "binding_digest": (
            binding.get("digest") if isinstance(binding, Mapping) else None
        ),
        "source_digest": (
            definition.get("source_digest")
            if isinstance(definition, Mapping)
            else None
        ),
        "registry_digest": result.get("registry_digest"),
        "status": str(result.get("status", "unresolved")),
    }


def operator_reference(result: Mapping[str, Any]) -> dict[str, Any]:
    operator = result.get("operator") if isinstance(result, Mapping) else None
    return {
        "uri": str(result.get("uri") or (operator or {}).get("uri")),
        "version": (operator or {}).get("version"),
        "digest": (operator or {}).get("digest"),
        "assumptions_digest": (operator or {}).get("assumptions_digest"),
        "status": str(result.get("status", "unresolved")),
    }


def model_reference(result: Mapping[str, Any]) -> dict[str, Any]:
    model = result.get("model") if isinstance(result, Mapping) else None
    return {
        "uri": str(result.get("uri") or (model or {}).get("uri")),
        "version": (model or {}).get("version"),
        "digest": (model or {}).get("digest"),
        "status": str(result.get("status", "unresolved")),
    }


def context_reference(pack: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "requirement_uri": pack["requirement"]["requirement_id"],
        "requirement_digest": pack["requirement"]["digest"],
        "provider_uri": pack["provider"]["uri"],
        "provider_digest": pack["provider"]["digest"],
        "source_revision": pack["provider"]["source_revision"],
        "pack_digest": pack["pack_digest"],
        "status": pack["status"],
    }


def unresolved_semantics(values: Sequence[str]) -> list[dict[str, Any]]:
    return [
        {
            "schema_version": "gravity.semantic-resolution.v1",
            "status": "unresolved",
            "ok": False,
            "uri": uri,
            "registry_digest": None,
            "definition": None,
            "binding": None,
            "reason_codes": ["SEMANTIC_DEFINITION_MISSING"],
            "network_called": False,
        }
        for uri in values
    ]


__all__ = [
    "capability_reference",
    "context_reference",
    "journey_reference",
    "model_reference",
    "operator_reference",
    "overlay_reference",
    "semantic_reference",
    "skill_reference",
    "unresolved_semantics",
]
