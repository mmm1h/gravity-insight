"""Idempotent bookkeeping for generated and manually reviewed parent bindings."""

from __future__ import annotations

from typing import Any, Mapping

from .parameter_types import MISSING, candidate_value


def automatic_parent_state(
    source: dict[str, Any], operation: dict[str, Any]
) -> tuple[dict[str, Any], list[Any], list[Any], bool]:
    contract = (
        source["draft"].setdefault("route_evidence", {})
        .setdefault("parameter_contract", {})
    )
    existing = list(operation.get("required_parent", []))
    automatic = "stable_parent_candidate_binding" in operation.get(
        "provenance", {}
    ).get("applied_overrides", [])
    prior = contract.get("stable_parent_candidates", [])
    prior = prior if isinstance(prior, list) else []
    if not automatic:
        return contract, existing, prior, False
    automatic_keys = {
        _binding_identity(item) for item in prior if isinstance(item, Mapping)
    }
    manual = [
        item
        for item in existing
        if not (
            isinstance(item, Mapping)
            and _binding_identity(item) in automatic_keys
        )
    ]
    return contract, manual, prior, True


def restore_removed_parent_inputs(
    source: Mapping[str, Any], operation: dict[str, Any],
    prior: list[Any], bindings: list[dict[str, Any]],
) -> None:
    old_fields = {
        str(item.get("input_field"))
        for item in prior
        if isinstance(item, Mapping) and item.get("input_field")
    }
    new_fields = {str(item["input_field"]) for item in bindings}
    metadata = {
        str(item.get("name")): item
        for item in source.get("draft", {})
        .get("route_evidence", {})
        .get("parameter_contract", {})
        .get("top_level_parameters", [])
        if isinstance(item, Mapping) and item.get("name")
    }
    for removed_field in sorted(old_fields - new_fields):
        parameter = metadata.get(removed_field)
        candidate = candidate_value(parameter) if parameter else 0
        operation["live_probe"]["inputs"][removed_field] = (
            0 if candidate is MISSING else candidate
        )


def _binding_identity(value: Mapping[str, Any]) -> tuple[str, str, str, str]:
    return tuple(
        str(value.get(name) or "")
        for name in ("operation_id", "input_field", "output_path", "selection")
    )


__all__ = [
    "automatic_parent_state",
    "restore_removed_parent_inputs",
]
