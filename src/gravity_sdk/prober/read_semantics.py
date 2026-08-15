"""Fail-closed read-semantics policy for online draft probes."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from gravity_sdk.errors import PolicyViolation
from gravity_sdk.paths import CONTRACT_ROOT


CONFIRMATIONS_PATH = CONTRACT_ROOT / "routes" / "probe-read-confirmations.json"
_WEAK_PATH_EVIDENCE = "read_action_path_token"
_CONFIRMATIONS_DISPLAY = (
    "src/gravity_sdk/contracts/routes/probe-read-confirmations.json"
)


def _weak_post_route(source: Mapping[str, Any]) -> tuple[str, str] | None:
    operation = source.get("operation")
    draft = source.get("draft")
    route = draft.get("route_evidence") if isinstance(draft, Mapping) else None
    if not isinstance(operation, Mapping) or not isinstance(route, Mapping):
        return None
    method = str(operation.get("upstream_method", "")).upper()
    evidence = route.get("semantic_evidence")
    if method != "POST" or evidence != [_WEAK_PATH_EVIDENCE]:
        return None
    return method, str(operation.get("path_template", ""))


def _confirmation_key(record: Any, path: Path) -> tuple[str, str]:
    evidence = record.get("evidence") if isinstance(record, Mapping) else None
    valid_evidence = (
        isinstance(evidence, list)
        and bool(evidence)
        and all(
            isinstance(item, Mapping)
            and bool(str(item.get("source", "")).strip())
            and bool(str(item.get("detail", "")).strip())
            for item in evidence
        )
    )
    method = str(record.get("method", "")).upper() if isinstance(record, Mapping) else ""
    valid = (
        isinstance(record, Mapping)
        and record.get("decision") == "confirmed_read"
        and method in {"GET", "POST"}
        and str(record.get("path", "")).startswith("/")
        and bool(str(record.get("reviewer", "")).strip())
        and bool(str(record.get("reviewed_at", "")).strip())
        and valid_evidence
    )
    if not valid:
        raise PolicyViolation(
            f"Probe read-semantics confirmation is incomplete or invalid: {path}.",
            next_action="Record method, path, reviewer, reviewed_at, confirmed_read decision, and static evidence.",
        )
    return method, str(record["path"])


def confirmation_keys(path: Path) -> set[tuple[str, str]]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PolicyViolation(
            f"Probe read-semantics confirmations are unavailable or invalid: {path}.",
            next_action="Repair the repository-owned confirmation file before probing weak-evidence POST routes.",
        ) from exc
    records = document.get("confirmations") if isinstance(document, Mapping) else None
    schema_version = document.get("schema_version") if isinstance(document, Mapping) else None
    if schema_version != "gravity-insight.probe-read-confirmations.v1" or not isinstance(records, list):
        raise PolicyViolation(
            f"Probe read-semantics confirmations have an invalid schema: {path}.",
            next_action="Repair the repository-owned confirmation file before probing weak-evidence POST routes.",
        )
    keys: set[tuple[str, str]] = set()
    for record in records:
        key = _confirmation_key(record, path)
        if key in keys:
            raise PolicyViolation(
                f"Duplicate probe read-semantics confirmation: {key[0]} {key[1]}."
            )
        keys.add(key)
    return keys


def assert_probe_read_semantics(
    source: Mapping[str, Any], *, confirmations_path: Path = CONFIRMATIONS_PATH
) -> None:
    """Reject a weak-evidence POST before any probe transport is constructed."""

    operation = source.get("operation")
    if isinstance(operation, Mapping) and operation.get("effect") == "mutation":
        if _is_registered_mutation(operation):
            return
        operation_id = str(operation.get("operation_id", "unknown"))
        raise PolicyViolation(
            f"Probe blocked for {operation_id}: mutation is not an exact registered stable write operation.",
            next_action=(
                "Do not probe this POST. Register its exact mutation contract and use the product-owned dry-run/execute workflow, or keep it as a blocked_write reservation."
            ),
        )
    route = _weak_post_route(source)
    if route is None or route in confirmation_keys(confirmations_path):
        return
    operation_id = str(source.get("operation", {}).get("operation_id", "unknown"))
    raise PolicyViolation(
        f"Probe blocked for {operation_id}: this POST route's read semantics are inferred only from a path token and have not been verified; it may perform a write operation.",
        next_action=(
            "Review the frontend control flow and UI behavior without sending a request. If it proves a read, add a per-route confirmed_read record with reviewer and static evidence to "
            f"{_CONFIRMATIONS_DISPLAY}; if it proves a write, keep the route blocked and record mutation evidence instead."
        ),
    )


def _is_registered_mutation(operation: Mapping[str, Any]) -> bool:
    operation_id = str(operation.get("operation_id", ""))
    if not operation_id:
        return False
    path = CONTRACT_ROOT / "operations" / f"{operation_id}.json"
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    registered = document.get("operation") if isinstance(document, Mapping) else None
    return (
        isinstance(registered, Mapping)
        and registered == operation
        and registered.get("effect") == "mutation"
        and registered.get("stability") == "stable"
        and registered.get("executable", True) is True
        and registered.get("upstream_method") == "POST"
    )


def assert_probe_sources(
    sources: Sequence[Mapping[str, Any]], *, confirmations_path: Path = CONFIRMATIONS_PATH
) -> None:
    for source in sources:
        assert_probe_read_semantics(source, confirmations_path=confirmations_path)


def assert_probe_operation_ids(
    operation_ids: Sequence[str], *, draft_root: Path = CONTRACT_ROOT / "drafts",
    confirmations_path: Path = CONFIRMATIONS_PATH,
) -> None:
    assert_probe_sources(
        [
            json.loads((draft_root / f"{operation_id}.json").read_text(encoding="utf-8"))
            for operation_id in operation_ids
        ],
        confirmations_path=confirmations_path,
    )


def assert_probe_draft_directory(
    draft_root: Path = CONTRACT_ROOT / "drafts",
    *, confirmations_path: Path = CONFIRMATIONS_PATH,
) -> None:
    try:
        sources = [
            json.loads(path.read_text(encoding="utf-8"))
            for path in sorted(draft_root.glob("*.json"))
        ]
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PolicyViolation(
            f"Probe draft read-semantics preflight failed: {draft_root}.",
            next_action="Repair the draft inventory before running an online batch probe.",
        ) from exc
    assert_probe_sources(sources, confirmations_path=confirmations_path)


__all__ = [
    "CONFIRMATIONS_PATH",
    "confirmation_keys",
    "assert_probe_draft_directory",
    "assert_probe_operation_ids",
    "assert_probe_read_semantics",
    "assert_probe_sources",
]
