"""Deterministic prior-to-current diff for validated ThinkingAI snapshots."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .agent_runtime_contracts import canonical_digest, load_json_object
from .thinkingai_inventory_contract import (
    SOURCE_ADAPTER,
    _invalid,
    _schema_copy,
    _validate_digest,
    validate_inventory_snapshot,
)
from .thinkingai_inventory_policy import DIFF_FIELDS, DIFF_STATES


DIFF_SCHEMA_VERSION = "gravity.thinkingai-inventory-diff.v1"
_DIFF_SCHEMA = "thinkingai-inventory-diff-v1.schema.json"


def compile_inventory_diff(
    previous: Mapping[str, Any] | None,
    current: Mapping[str, Any],
) -> dict[str, Any]:
    prior = validate_inventory_snapshot(previous) if previous is not None else None
    selected = validate_inventory_snapshot(current)
    if prior is not None and prior["source_adapter"] != selected["source_adapter"]:
        _invalid(
            "THINKINGAI_DIFF_SOURCE_INVALID",
            "snapshots use different source adapters",
        )
    before = {item["source_id"]: item for item in prior["items"]} if prior else {}
    after = {item["source_id"]: item for item in selected["items"]}
    changes = [
        _diff_item(source_id, before.get(source_id), after.get(source_id))
        for source_id in sorted(before.keys() | after.keys())
    ]
    state_counts = Counter(change["state"] for change in changes)
    artifact = {
        "artifact_kind": "thinkingai_inventory_diff",
        "schema_version": DIFF_SCHEMA_VERSION,
        "source_adapter": dict(SOURCE_ADAPTER),
        "previous_snapshot": (
            _snapshot_reference(prior)
            if prior is not None
            else {"observed_at": None, "snapshot_sha256": None}
        ),
        "current_snapshot": _snapshot_reference(selected),
        "counts": {state: state_counts.get(state, 0) for state in DIFF_STATES}
        | {"total": len(changes)},
        "changes": changes,
        "network_called": False,
    }
    artifact["diff_sha256"] = canonical_digest(artifact)
    return validate_inventory_diff(artifact)


def validate_inventory_diff(value: Mapping[str, Any]) -> dict[str, Any]:
    selected = _schema_copy(
        value,
        _DIFF_SCHEMA,
        "THINKINGAI_DIFF_SCHEMA_INVALID",
        "ThinkingAI inventory diff",
    )
    _validate_digest(selected, "diff_sha256", "THINKINGAI_DIFF_DIGEST_INVALID")
    if selected["source_adapter"] != SOURCE_ADAPTER:
        _invalid("THINKINGAI_DIFF_SOURCE_INVALID", "diff source adapter changed")
    changes = selected["changes"]
    source_ids = [change["source_id"] for change in changes]
    if source_ids != sorted(source_ids) or len(source_ids) != len(set(source_ids)):
        _invalid(
            "THINKINGAI_DIFF_ORDER_INVALID",
            "diff changes must contain one sorted row per source ID",
        )
    expected_counts = Counter(change["state"] for change in changes)
    counts = {state: expected_counts.get(state, 0) for state in DIFF_STATES}
    counts["total"] = len(changes)
    if selected["counts"] != counts:
        _invalid("THINKINGAI_DIFF_COUNT_INVALID", "diff counts are not derived")
    for change in changes:
        _validate_diff_item(change)
    return selected


def verify_inventory_diff(
    value: Mapping[str, Any],
    previous: Mapping[str, Any] | None,
    current: Mapping[str, Any],
) -> dict[str, Any]:
    selected = validate_inventory_diff(value)
    if selected != compile_inventory_diff(previous, current):
        _invalid(
            "THINKINGAI_DIFF_SOURCE_INVALID",
            "diff does not match its previous and current snapshots",
        )
    return selected


def load_inventory_diff(path: str | Path) -> dict[str, Any]:
    selected = Path(path)
    return validate_inventory_diff(
        load_json_object(selected, "ThinkingAI inventory diff")
    )


def _diff_item(
    source_id: str,
    previous: Mapping[str, Any] | None,
    current: Mapping[str, Any] | None,
) -> dict[str, Any]:
    fields = _changed_fields(previous, current)
    state = _state(previous, current, fields)
    return {
        "source_id": source_id,
        "state": state,
        "changed_fields": fields,
        "previous_item_sha256": canonical_digest(previous) if previous else None,
        "current_item_sha256": canonical_digest(current) if current else None,
        "previous_url": previous["source_url"] if previous else None,
        "current_url": current["source_url"] if current else None,
    }


def _changed_fields(
    previous: Mapping[str, Any] | None, current: Mapping[str, Any] | None
) -> list[str]:
    if previous is None or current is None:
        return []
    return [field for field in DIFF_FIELDS if previous[field] != current[field]]


def _state(
    previous: Mapping[str, Any] | None,
    current: Mapping[str, Any] | None,
    fields: list[str],
) -> str:
    if previous is None:
        return "added"
    if current is None:
        return "removed"
    if not fields:
        return "unchanged"
    return "redirect" if "source_url" in fields else "changed"


def _validate_diff_item(change: Mapping[str, Any]) -> None:
    fields = change["changed_fields"]
    if fields != [field for field in DIFF_FIELDS if field in fields]:
        _invalid("THINKINGAI_DIFF_ORDER_INVALID", "changed fields are not sorted")
    validators = {
        "added": _valid_added,
        "removed": _valid_removed,
        "unchanged": _valid_unchanged,
        "redirect": _valid_redirect,
        "changed": _valid_changed,
    }
    if not validators[change["state"]](change):
        _invalid(
            "THINKINGAI_DIFF_STATE_INVALID",
            "diff state does not match its bounded references",
        )


def _valid_added(change: Mapping[str, Any]) -> bool:
    return (
        change["previous_item_sha256"] is None
        and change["previous_url"] is None
        and change["current_item_sha256"] is not None
        and not change["changed_fields"]
    )


def _valid_removed(change: Mapping[str, Any]) -> bool:
    return (
        change["current_item_sha256"] is None
        and change["current_url"] is None
        and change["previous_item_sha256"] is not None
        and not change["changed_fields"]
    )


def _valid_unchanged(change: Mapping[str, Any]) -> bool:
    return (
        change["previous_item_sha256"] is not None
        and change["previous_item_sha256"] == change["current_item_sha256"]
        and change["previous_url"] == change["current_url"]
        and not change["changed_fields"]
    )


def _valid_redirect(change: Mapping[str, Any]) -> bool:
    return (
        change["previous_item_sha256"] is not None
        and change["current_item_sha256"] is not None
        and change["previous_url"] != change["current_url"]
        and "source_url" in change["changed_fields"]
    )


def _valid_changed(change: Mapping[str, Any]) -> bool:
    return (
        change["previous_item_sha256"] is not None
        and change["current_item_sha256"] is not None
        and change["previous_item_sha256"] != change["current_item_sha256"]
        and bool(change["changed_fields"])
        and "source_url" not in change["changed_fields"]
    )


def _snapshot_reference(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "observed_at": snapshot["source_observation"]["observed_at"],
        "snapshot_sha256": snapshot["snapshot_sha256"],
    }


__all__ = [
    "DIFF_SCHEMA_VERSION",
    "compile_inventory_diff",
    "load_inventory_diff",
    "validate_inventory_diff",
    "verify_inventory_diff",
]
