"""Strict value-free execution snapshots for Journey dependency freezing."""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from typing import Any

from . import __version__
from .agent_runtime_contracts import (
    AgentRuntimeContractError,
    canonical_digest,
    validate_schema,
)


SCHEMA_VERSION = "gravity.execution-snapshot.v1"
_SCHEMA_NAME = "execution-snapshot-v1.schema.json"


class ExecutionSnapshotError(AgentRuntimeContractError):
    """An execution snapshot is malformed, value-bearing, or tampered."""


def build_execution_snapshot(
    *,
    status: str,
    journey: Mapping[str, Any],
    skill: Mapping[str, Any] | None,
    project_overlay: Mapping[str, Any] | None,
    capabilities: Sequence[Mapping[str, Any]],
    semantics: Sequence[Mapping[str, Any]],
    operators: Sequence[Mapping[str, Any]],
    models: Sequence[Mapping[str, Any]],
    context_packs: Sequence[Mapping[str, Any]],
    contracts: Mapping[str, Any],
    runtime_version: str = __version__,
) -> dict[str, Any]:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "runtime": {"version": runtime_version},
        "journey": copy.deepcopy(dict(journey)),
        "skill": copy.deepcopy(dict(skill)) if skill is not None else None,
        "project_overlay": (
            copy.deepcopy(dict(project_overlay))
            if project_overlay is not None
            else None
        ),
        "capabilities": _ordered(capabilities, "identity_kind", "selector"),
        "semantics": _ordered(semantics, "uri"),
        "operators": _ordered(operators, "uri"),
        "models": _ordered(models, "uri"),
        "context_packs": _ordered(context_packs, "requirement_uri"),
        "contracts": copy.deepcopy(dict(contracts)),
    }
    payload["snapshot_digest"] = canonical_digest(payload)
    return compile_execution_snapshot(payload)


def compile_execution_snapshot(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ExecutionSnapshotError("Execution snapshot must be an object")
    selected = copy.deepcopy(dict(value))
    try:
        validate_schema(selected, _SCHEMA_NAME, "Execution snapshot")
    except AgentRuntimeContractError as exc:
        raise ExecutionSnapshotError(str(exc)) from exc
    supplied = selected.pop("snapshot_digest")
    expected = canonical_digest(selected)
    selected["snapshot_digest"] = supplied
    if supplied != expected:
        raise ExecutionSnapshotError("Execution snapshot digest changed")
    _unique(selected["capabilities"], "identity_kind", "selector")
    for field, key in (
        ("semantics", "uri"),
        ("operators", "uri"),
        ("models", "uri"),
        ("context_packs", "requirement_uri"),
    ):
        _unique(selected[field], key)
    _reject_values(selected)
    return selected


def _ordered(
    values: Sequence[Mapping[str, Any]], *keys: str
) -> list[dict[str, Any]]:
    if isinstance(values, (str, bytes)):
        raise ExecutionSnapshotError("Execution snapshot references must be arrays")
    selected = [copy.deepcopy(dict(value)) for value in values]
    return sorted(selected, key=lambda value: tuple(str(value[key]) for key in keys))


def _unique(values: Sequence[Mapping[str, Any]], *keys: str) -> None:
    identities = [tuple(str(value[key]) for key in keys) for value in values]
    if identities != sorted(identities) or len(identities) != len(set(identities)):
        raise ExecutionSnapshotError("Execution snapshot references are not unique and ordered")


def _reject_values(value: Mapping[str, Any]) -> None:
    forbidden = {
        "question",
        "app",
        "app_alias",
        "current_window",
        "reference_window",
        "hypothesis",
        "inputs",
        "content",
        "rows",
        "contract_path",
        "source_path",
        "credential",
        "token",
        "password",
    }

    def walk(item: Any) -> None:
        if isinstance(item, Mapping):
            if forbidden.intersection(item):
                raise ExecutionSnapshotError("Execution snapshot contains caller or private values")
            for child in item.values():
                walk(child)
        elif isinstance(item, list):
            for child in item:
                walk(child)

    walk(value)


__all__ = [
    "ExecutionSnapshotError",
    "SCHEMA_VERSION",
    "build_execution_snapshot",
    "compile_execution_snapshot",
]
