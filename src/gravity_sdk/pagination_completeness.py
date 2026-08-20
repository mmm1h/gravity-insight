"""Contract and result semantics for collection completeness."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from .actionable_error_values import actual_value
from .errors import ErrorCategory, ErrorDetail, ManifestError, exit_code_for_error


COMPLETE = "complete"
PREFIX = "prefix"
UNKNOWN = "unknown"
COMPLETENESS_VALUES = frozenset({COMPLETE, PREFIX, UNKNOWN})
PAGINATION_EVIDENCE_VALUES = frozenset({"production", "wire", "template", "none"})
_COMPLETE_EVIDENCE = frozenset({"production", "wire"})


def contract_dimensions(value: Mapping[str, Any]) -> tuple[str, str]:
    """Parse fail-closed pagination dimensions from a runtime manifest."""

    completeness = str(value.get("completeness", UNKNOWN)).strip().lower()
    evidence = str(value.get("pagination_evidence", "none")).strip().lower()
    if completeness not in COMPLETENESS_VALUES:
        raise ManifestError(
            f"actual value: {actual_value(completeness)}; pagination.completeness "
            "must be complete, prefix, or unknown",
            field="pagination.completeness",
            next_action="Correct the operation pagination contract and recompile manifests.",
        )
    if evidence not in PAGINATION_EVIDENCE_VALUES:
        raise ManifestError(
            f"actual value: {actual_value(evidence)}; pagination.pagination_evidence "
            "must be production, wire, template, or none",
            field="pagination.pagination_evidence",
            next_action="Correct the operation pagination contract and recompile manifests.",
        )
    if completeness == COMPLETE and evidence not in _COMPLETE_EVIDENCE:
        raise ManifestError(
            f"actual value: {actual_value({'completeness': completeness, 'pagination_evidence': evidence})}; "
            "template or absent pagination evidence cannot prove a complete collection",
            field="pagination.completeness",
            next_action="Set completeness to unknown or cite existing production/wire evidence.",
        )
    return completeness, evidence


def page_completeness(
    contract: str,
    page: Mapping[str, Any] | None,
    *,
    all_pages: bool,
) -> str:
    """Classify one returned collection without promoting contract evidence."""

    if page is None:
        return COMPLETE if contract == COMPLETE else UNKNOWN
    has_more = page.get("has_more")
    number = page.get("number")
    if has_more is True and (all_pages or number in (None, 1)):
        return PREFIX
    if contract != COMPLETE or has_more is not False:
        return UNKNOWN
    if not all_pages and number not in (None, 1):
        return UNKNOWN
    returned, total = page.get("item_count"), page.get("total_items")
    if not _nonnegative_int(returned) or not _nonnegative_int(total):
        return UNKNOWN
    return COMPLETE if returned == total else PREFIX


def force_prefix(result: dict[str, Any], truncated: bool) -> None:
    """Mark a known bounded truncation without changing other result fields."""

    if truncated:
        result["completeness"] = PREFIX


def aggregate_completeness(value: Any) -> str:
    """Propagate any nested result completeness into an aggregate envelope."""

    observed: list[str] = []
    _collect_completeness(value, observed)
    if PREFIX in observed:
        return PREFIX
    if UNKNOWN in observed or not observed:
        return UNKNOWN
    return COMPLETE


def require_complete_product(
    result: Mapping[str, Any], *, operation_id: str, product: str
) -> dict[str, Any]:
    """Return a machine-readable gap when a product requires a full collection."""

    selected = copy.deepcopy(dict(result))
    observed = aggregate_completeness(selected)
    if observed == COMPLETE:
        return selected
    detail = ErrorDetail.create(
        "COMPLETENESS_UNPROVEN",
        f"actual value: {actual_value(observed)}; {product} requires a proven complete collection.",
        category=ErrorCategory.CALLER,
        field="completeness",
        operation_id=operation_id,
        next_action=(
            "Use returned rows only as a prefix, or obtain production/wire pagination "
            "evidence and update the operation contract before retrying this product."
        ),
    )
    selected.update(
        ok=False,
        status="capability_gap",
        exit_code=exit_code_for_error(detail),
        required_completeness=COMPLETE,
        error=detail.to_dict(),
        next_action=detail.next_action,
    )
    return selected


def collection_claims(completeness: str) -> tuple[list[str], list[str]]:
    """Expose only claims justified by the operation completeness contract."""

    allowed = ["returned_items"]
    forbidden: list[str] = []
    if completeness == COMPLETE:
        allowed.extend(["complete_collection", "complete_collection_count"])
    else:
        forbidden.extend(["complete_collection", "complete_collection_count"])
    return allowed, forbidden


def _collect_completeness(value: Any, observed: list[str]) -> None:
    if isinstance(value, Mapping):
        status = value.get("completeness")
        if status in COMPLETENESS_VALUES:
            observed.append(str(status))
        for nested in value.values():
            if isinstance(nested, (Mapping, list, tuple)):
                _collect_completeness(nested, observed)
    elif isinstance(value, (list, tuple)):
        for nested in value:
            _collect_completeness(nested, observed)


def _nonnegative_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


__all__ = [
    "COMPLETE",
    "COMPLETENESS_VALUES",
    "PAGINATION_EVIDENCE_VALUES",
    "PREFIX",
    "UNKNOWN",
    "aggregate_completeness",
    "collection_claims",
    "contract_dimensions",
    "force_prefix",
    "page_completeness",
    "require_complete_product",
]
