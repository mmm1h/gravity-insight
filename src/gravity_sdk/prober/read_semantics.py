"""Fail-closed read-semantics policy for online draft probes."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import date
from enum import Enum
from pathlib import Path
from typing import Any, NoReturn

from gravity_sdk.actionable_error_values import actual_value
from gravity_sdk.errors import PolicyViolation
from gravity_sdk.paths import CONTRACT_ROOT


CONFIRMATIONS_PATH = CONTRACT_ROOT / "routes" / "probe-read-confirmations.json"
_WEAK_PATH_EVIDENCE = "read_action_path_token"
_CONFIRMATIONS_DISPLAY = (
    "src/gravity_sdk/contracts/routes/probe-read-confirmations.json"
)
_READ_EVIDENCE = frozenset(
    {_WEAK_PATH_EVIDENCE, "safe_http_method", "route_registry:read_contract_not_verified"}
)
_UNSUPPORTED_ROUTE_STATUSES = frozenset(
    {"uncovered_auth_or_proxy", "uncovered_export", "unsupported_non_api"}
)


class ProbeSemanticStatus(str, Enum):
    VERIFIED_READ = "verified_read"
    VERIFIED_MUTATION = "verified_mutation"
    STATIC_READ_CANDIDATE = "static_read_candidate"
    UNSAFE_UNKNOWN = "unsafe_unknown"
    BLOCKED_BY_DATA = "blocked_by_data"
    UNSUPPORTED = "unsupported"


PROBE_SEMANTIC_STATUSES = tuple(status.value for status in ProbeSemanticStatus)


def _invalid_confirmation(path: Path, reason: str, observed: Any) -> NoReturn:
    raise PolicyViolation(
        f"Probe read-semantics confirmation is invalid ({reason}); actual value: "
        f"{actual_value({'file': str(path), 'observed': observed})}.",
        field="probe_read_confirmations",
        next_action=(
            "Record one exact method + path decision with reviewer, ISO review date, "
            "and non-empty static source/detail evidence before probing."
        ),
        code="PROBE_CONFIRMATION_INVALID",
    )


def _confirmation_key(record: Any, path: Path) -> tuple[str, str]:
    evidence = record.get("evidence") if isinstance(record, Mapping) else None
    valid_evidence = _valid_static_evidence(evidence)
    method = str(record.get("method", "")).upper() if isinstance(record, Mapping) else ""
    reviewed_at = record.get("reviewed_at") if isinstance(record, Mapping) else None
    try:
        valid_date = date.fromisoformat(reviewed_at).isoformat() == reviewed_at
    except (TypeError, ValueError):
        valid_date = False
    valid = (
        isinstance(record, Mapping)
        and record.get("decision") == "confirmed_read"
        and method in {"GET", "POST"}
        and str(record.get("path", "")).startswith("/")
        and bool(str(record.get("reviewer", "")).strip())
        and valid_date
        and valid_evidence
    )
    if not valid:
        _invalid_confirmation(path, "incomplete record", record)
    return method, str(record["path"])


def _valid_static_evidence(evidence: Any) -> bool:
    return (
        isinstance(evidence, list)
        and bool(evidence)
        and all(
            isinstance(item, Mapping)
            and bool(str(item.get("source", "")).strip())
            and bool(str(item.get("detail", "")).strip())
            for item in evidence
        )
    )


def confirmation_keys(path: Path) -> set[tuple[str, str]]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        _invalid_confirmation(path, "file unavailable or malformed", str(path))
    records = document.get("confirmations") if isinstance(document, Mapping) else None
    schema_version = document.get("schema_version") if isinstance(document, Mapping) else None
    if schema_version != "gravity-insight.probe-read-confirmations.v1" or not isinstance(records, list):
        _invalid_confirmation(path, "schema", schema_version)
    keys: set[tuple[str, str]] = set()
    for record in records:
        key = _confirmation_key(record, path)
        if key in keys:
            raise PolicyViolation(
                f"Duplicate probe read-semantics confirmation; actual value: {actual_value(key)}.",
                field="probe_read_confirmations",
                next_action="Keep exactly one reviewed confirmation for this method + path pair.",
                code="PROBE_CONFIRMATION_INVALID",
            )
        keys.add(key)
    return keys


def _registered_effect(operation: Mapping[str, Any]) -> str | None:
    """Return the effect only for an exact stable executable source contract."""

    operation_id = str(operation.get("operation_id", ""))
    if not operation_id:
        return None
    path = CONTRACT_ROOT / "operations" / f"{operation_id}.json"
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    registered = document.get("operation") if isinstance(document, Mapping) else None
    if not (
        isinstance(registered, Mapping)
        and registered == operation
        and registered.get("stability") == "stable"
        and registered.get("executable", True) is True
    ):
        return None
    effect = str(registered.get("effect", ""))
    return effect if effect in {"read", "mutation"} else None


def _has_data_block(source: Mapping[str, Any]) -> bool:
    draft = source.get("draft")
    evidence = draft.get("probe_evidence") if isinstance(draft, Mapping) else None
    latest = evidence[-1] if isinstance(evidence, list) and evidence else None
    return isinstance(latest, Mapping) and latest.get("conclusion") == "blocked_by_data"


def _needs_confirmation(source: Mapping[str, Any]) -> bool:
    operation = source.get("operation")
    return (
        isinstance(operation, Mapping)
        and str(operation.get("upstream_method", "")).upper() == "POST"
        and _registered_effect(operation) is None
    )


def _semantic_status(
    source: Mapping[str, Any], confirmations: set[tuple[str, str]] | None = None,
) -> ProbeSemanticStatus:
    operation = source.get("operation")
    if not isinstance(operation, Mapping):
        return ProbeSemanticStatus.UNSUPPORTED
    registered_effect = _registered_effect(operation)
    if registered_effect == "read":
        return ProbeSemanticStatus.VERIFIED_READ
    if registered_effect == "mutation":
        return ProbeSemanticStatus.VERIFIED_MUTATION
    draft = source.get("draft")
    route = draft.get("route_evidence") if isinstance(draft, Mapping) else None
    effect = str(operation.get("effect", ""))
    method = str(operation.get("upstream_method", "")).upper()
    path = str(operation.get("path_template", ""))
    if effect == "mutation":
        return ProbeSemanticStatus.UNSAFE_UNKNOWN
    if method == "POST":
        keys = confirmations if confirmations is not None else confirmation_keys(CONFIRMATIONS_PATH)
        return (
            ProbeSemanticStatus.VERIFIED_READ
            if (method, path) in keys
            else ProbeSemanticStatus.UNSAFE_UNKNOWN
        )
    if effect != "read":
        return ProbeSemanticStatus.UNSUPPORTED
    if _has_data_block(source):
        return ProbeSemanticStatus.BLOCKED_BY_DATA
    if method in {"GET", "HEAD", "OPTIONS"}:
        return ProbeSemanticStatus.VERIFIED_READ
    return _unverified_status(operation, route)


def _unverified_status(
    operation: Mapping[str, Any], route: Any,
) -> ProbeSemanticStatus:
    route_status = str(route.get("status", "")) if isinstance(route, Mapping) else ""
    evidence = route.get("semantic_evidence", []) if isinstance(route, Mapping) else []
    if route_status in _UNSUPPORTED_ROUTE_STATUSES:
        return ProbeSemanticStatus.UNSUPPORTED
    if route_status == "uncovered_read" or any(item in _READ_EVIDENCE for item in evidence):
        return ProbeSemanticStatus.STATIC_READ_CANDIDATE
    return ProbeSemanticStatus.UNSAFE_UNKNOWN


def probe_semantic_status(
    source: Mapping[str, Any], *, confirmations_path: Path = CONFIRMATIONS_PATH,
) -> str:
    """Classify one source without performing credential or network actions."""

    confirmations = None
    if _needs_confirmation(source):
        confirmations = confirmation_keys(confirmations_path)
    return _semantic_status(source, confirmations).value


def probe_semantic_status_distribution(
    sources: Sequence[Mapping[str, Any]], *, confirmations_path: Path = CONFIRMATIONS_PATH,
) -> dict[str, int]:
    confirmations = (
        confirmation_keys(confirmations_path)
        if any(_needs_confirmation(source) for source in sources)
        else set()
    )
    counts = Counter(_semantic_status(source, confirmations).value for source in sources)
    return {status: counts[status] for status in PROBE_SEMANTIC_STATUSES}


def assert_probe_read_semantics(
    source: Mapping[str, Any], *, confirmations_path: Path = CONFIRMATIONS_PATH
) -> None:
    """Reject unverified semantics before credentials or transport construction."""

    status = probe_semantic_status(source, confirmations_path=confirmations_path)
    if status in {"verified_read", "verified_mutation"}:
        return
    operation = source.get("operation")
    operation = operation if isinstance(operation, Mapping) else {}
    operation_id = str(operation.get("operation_id", "unknown"))
    observed = {
        "method": str(operation.get("upstream_method", "")),
        "path": str(operation.get("path_template", "")),
        "status": status,
    }
    if status == "unsafe_unknown" and operation.get("effect") == "mutation":
        message = "mutation is not an exact registered stable write operation"
        next_action = (
            "Do not probe this route. Register its exact mutation contract and use the "
            "product-owned dry-run/execute workflow, or keep it as evidence debt."
        )
    elif status == "unsafe_unknown":
        message = "POST or unknown route semantics have not been verified and may perform a write"
        next_action = (
            "Review static frontend control flow without sending a request. Record an exact "
            "confirmed_read decision only when reviewer, date, and static evidence prove it."
        )
    elif status == "static_read_candidate":
        message = "static evidence suggests a read but does not authorize a production probe"
        next_action = "Verify the exact method + path semantics from static control flow before probing."
    elif status == "blocked_by_data":
        message = "the route is blocked by unavailable parent or sample data"
        next_action = "Keep the route blocked until repository evidence resolves the data dependency."
    else:
        message = "the route class is unsupported by the read prober"
        next_action = "Use a repository-owned product workflow for this route class, or keep it unsupported."
    raise PolicyViolation(
        f"Probe blocked for {operation_id}: {message}; actual value: {actual_value(observed)}.",
        field="operation.route_semantics",
        next_action=f"{next_action} Confirmation owner: {_CONFIRMATIONS_DISPLAY}.",
        code="PROBE_UNSAFE_UNKNOWN" if status == "unsafe_unknown" else "PROBE_SEMANTICS_BLOCKED",
    )


def assert_probe_sources(
    sources: Sequence[Mapping[str, Any]], *, confirmations_path: Path = CONFIRMATIONS_PATH
) -> None:
    confirmations = (
        confirmation_keys(confirmations_path)
        if any(_needs_confirmation(source) for source in sources)
        else set()
    )
    for source in sources:
        status = _semantic_status(source, confirmations)
        if status not in {ProbeSemanticStatus.VERIFIED_READ, ProbeSemanticStatus.VERIFIED_MUTATION}:
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


def assert_available_probe_items(
    items: Sequence[Any], *, draft_root: Path = CONTRACT_ROOT / "drafts",
    confirmations_path: Path = CONFIRMATIONS_PATH,
) -> None:
    operation_ids = [
        str(item.get("operation_id", "")) if isinstance(item, Mapping) else str(item)
        for item in items
    ]
    available = [
        operation_id
        for operation_id in operation_ids
        if operation_id and (draft_root / f"{operation_id}.json").is_file()
    ]
    assert_probe_operation_ids(
        available, draft_root=draft_root, confirmations_path=confirmations_path
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
    "PROBE_SEMANTIC_STATUSES",
    "ProbeSemanticStatus",
    "confirmation_keys",
    "assert_probe_draft_directory",
    "assert_probe_operation_ids",
    "assert_probe_read_semantics",
    "assert_probe_sources",
    "probe_semantic_status",
    "probe_semantic_status_distribution",
]
