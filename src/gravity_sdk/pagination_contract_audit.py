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
from dataclasses import fields
from pathlib import Path
from typing import Any

from .errors import ManifestError
from .models import ResponseProjection


ROOT = Path(__file__).resolve().parents[2]
AUDIT_PATH = ROOT / "evidence/forensics/20260817_pagination_contract_audit.json"
OPERATIONS_ROOT = Path(__file__).resolve().parent / "contracts" / "operations"

_DISPOSITION_STATUSES = frozenset({"repaired", "drifted"})
_UNPROVEN_EVIDENCE = frozenset({"template_default"})
_COMPLETENESS_SIGNAL_FIELDS = frozenset({
    "has_more",
    "next_page",
    "page_info",
    "total",
    "total_number",
    "total_page",
})
_NOT_COLLECTION = "not_collection_semantics"
_NO_FALSIFIABLE_SIGNAL = "no_falsifiable_completeness_signal"
_RESPONSE_PROJECTION_FIELD_NAMES = frozenset(
    item.name for item in fields(ResponseProjection)
)


def load_pagination_audit(path: Path | None = None) -> dict[str, Any]:
    """Load the dated pagination-audit snapshot."""

    return json.loads((path or AUDIT_PATH).read_text(encoding="utf-8"))


def current_operation_pagination() -> dict[str, dict[str, Any]]:
    """Read pagination and its evidence context from current contracts."""

    current: dict[str, dict[str, Any]] = {}
    for path in sorted(OPERATIONS_ROOT.glob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        operation = document["operation"]
        pagination = operation.get("pagination")
        if not isinstance(pagination, Mapping):
            pagination = {}
        request = operation.get("request")
        projection = operation.get("response_projection")
        request_fields = set()
        if isinstance(request, Mapping):
            for field in ("body_fields", "path_fields", "query_fields"):
                values = request.get(field)
                if isinstance(values, Sequence) and not isinstance(values, (str, bytes)):
                    request_fields.update(str(item) for item in values)
        current[str(operation["operation_id"])] = {
            **dict(pagination),
            "_evidence_context": {
                "action": operation.get("action"),
                "effect": operation.get("effect"),
                "projected_fields": sorted(_field_names(projection)),
                "request_fields": sorted(request_fields),
                "response_data_shape": (
                    projection.get("data_shape")
                    if isinstance(projection, Mapping)
                    else None
                ),
                "response_scalar_only": _response_scalar_only(projection),
                "stability": operation.get("stability"),
            },
        }
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
        "current_completeness": _dimension_counts(records, "completeness"),
        "current_pagination_evidence": _dimension_counts(
            records, "pagination_evidence"
        ),
        **_evidence_reconciliation(records),
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
    context = (
        pagination.get("_evidence_context")
        if isinstance(pagination, Mapping)
        else None
    )
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
        "completeness": None if pagination is None else pagination.get("completeness"),
        "pagination_evidence": (
            None if pagination is None else pagination.get("pagination_evidence")
        ),
        "current_stability": (
            context.get("stability") if isinstance(context, Mapping) else None
        ),
        "disposition_status": status,
        "kind_alignment": _alignment(declared, current_kind, status, expected),
        "shape_unproven": pagination_shape_unproven(record, current_kind),
        "unknown_evidence_disposition": _unknown_evidence_disposition(
            record, pagination
        ),
    }


def _unknown_evidence_disposition(
    record: Mapping[str, Any], pagination: Mapping[str, Any] | None
) -> str | None:
    context = _permanent_unknown_context(pagination)
    if context is None:
        return None
    review_status = record.get("review_status")
    if review_status == "not_collection_semantics":
        return _static_unknown_disposition(context)
    if (
        review_status == "collection_completeness_unknown"
        and _static_scalar_query(context)
    ):
        return _NOT_COLLECTION
    if _production_no_signal(record, pagination):
        return _NO_FALSIFIABLE_SIGNAL
    return None


def _permanent_unknown_context(
    pagination: Mapping[str, Any] | None,
) -> Mapping[str, Any] | None:
    if not isinstance(pagination, Mapping):
        return None
    context = pagination.get("_evidence_context")
    expected = (
        pagination.get("kind") == "none",
        pagination.get("completeness") == "unknown",
        isinstance(context, Mapping),
    )
    if not all(expected) or context.get("stability") != "stable":
        return None
    return context


def _static_unknown_disposition(context: Mapping[str, Any]) -> str | None:
    detail_read = (
        context.get("effect") == "read"
        and context.get("action") in {"detail", "get"}
        and context.get("response_data_shape") != "list"
    )
    if context.get("effect") == "mutation" or detail_read:
        return _NOT_COLLECTION
    unpageable_list = (
        context.get("effect") == "read"
        and context.get("response_data_shape") == "list"
        and not _has_completeness_signal(context)
    )
    return _NO_FALSIFIABLE_SIGNAL if unpageable_list else None


def _static_scalar_query(context: Mapping[str, Any]) -> bool:
    return (
        context.get("effect") == "read"
        and context.get("action") == "query"
        and context.get("response_scalar_only") is True
    )


def _production_no_signal(
    record: Mapping[str, Any], pagination: Mapping[str, Any]
) -> bool:
    review_status = record.get("review_status")
    supported_status = (
        review_status == "no_page_info_in_observed_response"
        or review_status == "shape_verified" and record.get("observed_shape") == "B"
    )
    return (
        supported_status
        and record.get("evidence_level") == "production"
        and pagination.get("pagination_evidence") == "production"
    )


def _has_completeness_signal(context: Mapping[str, Any]) -> bool:
    request = set(context.get("request_fields") or ())
    projected = set(context.get("projected_fields") or ())
    return bool({"page", "page_size"} & request or _COMPLETENESS_SIGNAL_FIELDS & projected)


def _unknown_evidence_action(record: Mapping[str, Any]) -> str | None:
    if record.get("completeness") != "unknown":
        return None
    if record.get("current_stability") != "stable":
        return "not_scheduled_non_stable"
    if record.get("unknown_evidence_disposition") is not None:
        return "not_scheduled_without_new_signal"
    return "collect_production_or_wire"


def _evidence_reconciliation(
    records: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    permanent_unknown = [
        item for item in records
        if item["unknown_evidence_disposition"] is not None
    ]
    actions = [
        action for item in records
        if (action := _unknown_evidence_action(item)) is not None
    ]
    return {
        "permanent_unknown": sorted(
            item["operation_id"] for item in permanent_unknown
        ),
        "permanent_unknown_dispositions": _dimension_counts(
            permanent_unknown, "unknown_evidence_disposition"
        ),
        "production_evidence_targets": sorted(
            item["operation_id"]
            for item in records
            if _unknown_evidence_action(item) == "collect_production_or_wire"
        ),
        "unknown_evidence_actions": dict(sorted(Counter(actions).items())),
    }


def _field_names(value: Any) -> set[str]:
    if isinstance(value, Mapping):
        result = {str(key) for key in value}
        for nested in value.values():
            result.update(_field_names(nested))
        return result
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        result: set[str] = set()
        for nested in value:
            result.update(_field_names(nested))
        return result
    return {str(value)} if isinstance(value, str) else set()


def _response_scalar_only(value: Any) -> bool:
    if (
        not isinstance(value, Mapping)
        or set(value) - _RESPONSE_PROJECTION_FIELD_NAMES
    ):
        return False
    try:
        projection = ResponseProjection.from_dict(value)
    except ManifestError:
        return False
    return bool(projection.data_keys) and projection == ResponseProjection(
        data_keys=projection.data_keys,
        required_data_keys=projection.data_keys,
        numeric_paths=projection.data_keys,
    )


def _disposition_status(record: Mapping[str, Any]) -> str | None:
    disposition = record.get("declared_kind_disposition")
    if not isinstance(disposition, Mapping):
        return None
    status = disposition.get("status")
    return status if status in _DISPOSITION_STATUSES else None


def _dimension_counts(records: Sequence[Mapping[str, Any]], field: str) -> dict[str, int]:
    return dict(sorted(Counter(
        str(item[field]) for item in records if item.get(field) is not None
    ).items()))


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
