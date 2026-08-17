"""Reconcile the historical pagination audit against current contracts.

The forensic snapshot is a dated verdict, not a live mirror of HEAD.  This
module is the machine-decidable join: every current ``pagination.kind`` must
either match the audit-time declaration or carry an explicit repaired/drifted
disposition.  Counts of current kinds are computed here, never stored as
HEAD facts inside the snapshot.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
AUDIT_PATH = ROOT / "evidence/forensics/20260817_pagination_contract_audit.json"
OPERATIONS_ROOT = Path(__file__).resolve().parent / "contracts" / "operations"

_DISPOSITION_STATUSES = frozenset({"repaired", "drifted"})
_UNPROVEN_EVIDENCE = frozenset({"template_default"})


def load_pagination_audit(path: Path | None = None) -> dict[str, Any]:
    """Load the dated pagination-audit snapshot."""

    return json.loads((path or AUDIT_PATH).read_text(encoding="utf-8"))


def current_operation_pagination() -> dict[str, dict[str, Any]]:
    """Read ``pagination`` from every current operation contract."""

    current: dict[str, dict[str, Any]] = {}
    for path in sorted(OPERATIONS_ROOT.glob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        operation = document["operation"]
        pagination = operation.get("pagination")
        if not isinstance(pagination, Mapping):
            pagination = {}
        current[str(operation["operation_id"])] = dict(pagination)
    return current


def pagination_shape_unproven(
    record: Mapping[str, Any], current_kind: str | None = None
) -> bool:
    """True when a live ``page_info`` contract still has only template evidence."""

    kind = current_kind if current_kind is not None else record.get("declared_kind")
    return (
        kind == "page_info"
        and record.get("evidence_level") in _UNPROVEN_EVIDENCE
        and _disposition_status(record) != "repaired"
    )


def reconcile_pagination_audit(
    audit: Mapping[str, Any] | None = None,
    current: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Join audit-time verdicts to current contract pagination kinds."""

    snapshot = dict(audit or load_pagination_audit())
    contracts = {
        operation_id: dict(pagination)
        for operation_id, pagination in (
            current or current_operation_pagination()
        ).items()
    }
    records = [_reconcile_record(item, contracts) for item in snapshot["records"]]
    return {
        "schema_version": snapshot.get("schema_version"),
        "audit_baseline_commit": snapshot.get("baseline_commit"),
        "relationship": snapshot.get("relationship"),
        "records": records,
        "coverage": _coverage(records, contracts),
        "audit_baseline_declared_kinds": dict(
            snapshot.get("summary", {}).get("audit_baseline_declared_kinds")
            or snapshot.get("summary", {}).get("declared_kinds")
            or {}
        ),
        "current_declared_kinds": dict(sorted(Counter(
            item["current_declared_kind"]
            for item in records
            if item["current_declared_kind"] is not None
        ).items())),
        "page_info_shapes": dict(snapshot.get("summary", {}).get("page_info_shapes") or {}),
        "unproven_page_info": sorted(
            item["operation_id"]
            for item in records
            if pagination_shape_unproven(item, item["current_declared_kind"])
        ),
        "unexpected_kind_drift": [
            {
                "operation_id": item["operation_id"],
                "declared_kind": item["declared_kind"],
                "current_declared_kind": item["current_declared_kind"],
                "disposition_status": item["disposition_status"],
            }
            for item in records
            if item["kind_alignment"] == "unexpected"
        ],
    }


def _coverage(
    records: Sequence[Mapping[str, Any]], contracts: Mapping[str, Mapping[str, Any]]
) -> dict[str, Any]:
    audited = {item["operation_id"] for item in records}
    return {
        "audit_records": len(records),
        "current_operations": len(contracts),
        "missing_from_audit": sorted(set(contracts) - audited),
        "missing_from_contracts": sorted(audited - set(contracts)),
    }


def _reconcile_record(
    record: Mapping[str, Any], current: Mapping[str, Mapping[str, Any]]
) -> dict[str, Any]:
    operation_id = str(record["operation_id"])
    declared = record.get("declared_kind")
    pagination = current.get(operation_id)
    current_kind = None if pagination is None else pagination.get("kind")
    disposition = record.get("declared_kind_disposition")
    status = _disposition_status(record)
    expected = (
        disposition.get("current_kind")
        if isinstance(disposition, Mapping)
        else None
    )
    return {
        **dict(record),
        "current_declared_kind": current_kind,
        "current_total_page_field": (
            None if pagination is None else pagination.get("total_page_field")
        ),
        "disposition_status": status,
        "kind_alignment": _alignment(declared, current_kind, status, expected),
        "shape_unproven": pagination_shape_unproven(record, current_kind),
    }


def _disposition_status(record: Mapping[str, Any]) -> str | None:
    disposition = record.get("declared_kind_disposition")
    if not isinstance(disposition, Mapping):
        return None
    status = disposition.get("status")
    return status if status in _DISPOSITION_STATUSES else None


def _alignment(
    declared: Any, current_kind: Any, status: str | None, expected: Any
) -> str:
    if current_kind is None:
        return "missing_contract"
    if declared == current_kind:
        return "unexpected" if status is not None else "unchanged"
    if status is None or expected != current_kind:
        return "unexpected"
    return status


__all__ = [
    "AUDIT_PATH",
    "OPERATIONS_ROOT",
    "current_operation_pagination",
    "load_pagination_audit",
    "pagination_shape_unproven",
    "reconcile_pagination_audit",
]
