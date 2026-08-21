"""Exact R01 project binding over the generic Business Semantic Registry."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from datetime import date
from typing import Any

from .agent_runtime_contracts import canonical_digest
from .reference_journey_contract import SEMANTIC_URI
from .semantic_contract import SemanticContractError
from .semantic_registry import SemanticRegistry


class ReferenceSemanticAdapterError(ValueError):
    """The generic registry cannot preserve the exact R01 Semantic meaning."""


def resolve_reference_semantic(
    source: Mapping[str, Any],
    *,
    project_id: str,
    owner: str,
    uri: str,
    app_alias: str,
    current: tuple[date, date],
    reference: tuple[date, date],
) -> dict[str, Any]:
    try:
        registry = SemanticRegistry([source])
        resolutions = [
            registry.resolve(
                uri,
                project_id=project_id,
                app_alias=app_alias,
                start=window[0].isoformat(),
                end=window[1].isoformat(),
            )
            for window in (current, reference)
        ]
    except SemanticContractError as exc:
        raise ReferenceSemanticAdapterError(exc.reason_code) from exc
    for resolution in resolutions:
        _require_resolved(resolution)
        _validate_reference_semantic(
            resolution, project_id=project_id, owner=owner, app_alias=app_alias
        )
    _require_same_identity(resolutions)
    return _public_semantic(uri, registry.digest, resolutions[0])


def _require_resolved(resolution: Mapping[str, Any]) -> None:
    if resolution.get("status") == "resolved":
        return
    reasons = resolution.get("reason_codes", [])
    raise ReferenceSemanticAdapterError(
        str(reasons[0]) if reasons else "SEMANTIC_DEFINITION_INVALID"
    )


def _require_same_identity(resolutions: list[dict[str, Any]]) -> None:
    identities = {
        (resolution["definition"]["digest"], resolution["binding"]["digest"])
        for resolution in resolutions
    }
    if len(identities) != 1:
        raise ReferenceSemanticAdapterError("SEMANTIC_EFFECTIVE_RANGE_MISMATCH")


def _public_semantic(
    uri: str, registry_digest: str, resolution: Mapping[str, Any]
) -> dict[str, Any]:
    definition = resolution["definition"]
    binding = resolution["binding"]
    return {
        "uri": uri,
        "digest": canonical_digest(
            {"definition": definition["digest"], "binding": binding["digest"]}
        ),
        "registry_digest": registry_digest,
        "source_id": definition["source_id"],
        "source_digest": definition["source_digest"],
        "definition": copy.deepcopy(definition["contract"]),
        "binding": copy.deepcopy(binding["contract"]),
        "network_called": False,
    }


def _validate_reference_semantic(
    resolution: Mapping[str, Any],
    *,
    project_id: str,
    owner: str,
    app_alias: str,
) -> None:
    definition_artifact = resolution.get("definition")
    binding_artifact = resolution.get("binding")
    if not isinstance(definition_artifact, Mapping) or not isinstance(
        binding_artifact, Mapping
    ):
        raise ReferenceSemanticAdapterError("SEMANTIC_BINDING_MISSING")
    definition = definition_artifact["contract"]
    binding = binding_artifact["contract"]
    _validate_definition(definition, owner)
    _validate_binding(binding, project_id, owner, app_alias)


def _validate_definition(definition: Mapping[str, Any], owner: str) -> None:
    expected = {
        "uri": SEMANTIC_URI,
        "kind": "metric",
        "version": 1,
        "owner": owner,
        "authority": "project",
        "unit": {
            "kind": "currency",
            "symbol": "platform_reported_cost",
            "currency": None,
            "scale": 2,
        },
        "aggregation": {"method": "sum", "additivity": "additive"},
        "time": {
            "grains": ["total"],
            "timezone": "unknown",
            "attribution_window": None,
        },
        "entity_uri": "entity://gravity/app@1",
        "formula": {"operator": "source", "dependencies": [], "parameters": []},
        "binding_required": True,
    }
    if any(definition.get(key) != value for key, value in expected.items()):
        raise ReferenceSemanticAdapterError("project Semantic identity changed")
    claims = definition.get("claim_policy")
    if not isinstance(claims, Mapping):
        raise ReferenceSemanticAdapterError("project Semantic claims changed")
    _unique_strings(claims.get("allowed"), "semantic allowed claims")
    _unique_strings(claims.get("forbidden"), "semantic forbidden claims")


def _validate_binding(
    binding: Mapping[str, Any], project_id: str, owner: str, app_alias: str
) -> None:
    identity = (
        binding.get("semantic_uri"),
        binding.get("project_id"),
        binding.get("owner"),
        binding.get("app_alias"),
        binding.get("parameters"),
    )
    if identity != (SEMANTIC_URI, project_id, owner, app_alias, {}):
        raise ReferenceSemanticAdapterError("project Semantic binding changed")
    provider = binding.get("provider")
    if not isinstance(provider, Mapping) or provider.get("kind") != "semantic_compose":
        raise ReferenceSemanticAdapterError("project Semantic provider changed")
    _reference(
        provider.get("definition"), "report.ap-cost-observation", 2, "semantic definition"
    )
    members = provider.get("members")
    expected = {
        "metric": ("report.metric.ap-cost", 1),
        "dimension": ("report.dimension.click-company", 1),
        "filter": ("report.filter.click-company", 1),
        "grain": ("report.grain.total", 1),
        "join": ("report.join.adreport-click-company", 1),
    }
    if not isinstance(members, Mapping) or set(members) != set(expected):
        raise ReferenceSemanticAdapterError("physical_binding fields are invalid")
    for name, (definition_id, version) in expected.items():
        _reference(members[name], definition_id, version, name)


def _reference(value: Any, definition_id: str, version: int, label: str) -> None:
    if value != {"definition_id": definition_id, "version": version}:
        raise ReferenceSemanticAdapterError(f"{label} reference changed")


def _unique_strings(value: Any, label: str) -> None:
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(item, str) or not item for item in value)
        or len(value) != len(set(value))
    ):
        raise ReferenceSemanticAdapterError(f"{label} must be a unique string array")


__all__ = [
    "ReferenceSemanticAdapterError",
    "resolve_reference_semantic",
]
