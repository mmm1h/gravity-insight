"""Small helpers for constructing governed read-result envelopes."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .analysis_projection_contract import missing_funnel_grouping_fields
from .errors import ErrorCode, ErrorDetail, error_for_status
from .models import OperationSpec
from .pagination_completeness import page_completeness

ANALYSIS_FUNNEL_GROUPING_REMEDY = (
    "Set calculate_each_day=false, issue one request per known group value with "
    "exactly one user-property equality filter, verify each request-to-filter "
    "binding offline, and consume only aggregate_date.total; do not retry "
    "group_by until grouped readback is re-verified."
)


def analysis_read_error(
    operation: OperationSpec,
    projected: Mapping[str, Any],
    values: Mapping[str, Any],
    status: str,
) -> Mapping[str, Any] | None:
    """Prefer the Funnel grouping contract error over the generic status error."""

    missing = missing_funnel_grouping_fields(
        operation.response_projection, projected, values
    )
    if not missing:
        return error_for_status(status, operation_id=operation.operation_id)
    return ErrorDetail.create(
        ErrorCode.CONTRACT_CHANGED,
        "The upstream Funnel response returned date-priority aggregates without "
        "the requested grouping dimension.",
        operation_id=operation.operation_id,
        field="group_by_list",
        next_action=ANALYSIS_FUNNEL_GROUPING_REMEDY,
        unsupported_items=[
            {"field": field, "type": "unsupported_grouping"} for field in missing
        ],
    ).to_dict()


def pagination_result_dimensions(
    operation: OperationSpec,
    page: Mapping[str, Any] | None,
    *,
    all_pages: bool,
) -> dict[str, str]:
    return {
        "completeness": page_completeness(
            operation.pagination.completeness, page, all_pages=all_pages
        ),
        "pagination_evidence": operation.pagination.pagination_evidence,
    }


def result_warnings(
    operation: OperationSpec, drift_warnings: Sequence[str]
) -> tuple[str, ...]:
    warnings: list[str] = list(drift_warnings)
    if operation.stability == "experimental":
        warnings.append("operation contract is experimental")
    for name, note in operation.response_projection.unreliable_item_keys.items():
        warnings.append(
            f"do not use {name} as a decision metric; "
            f"{note['reason']}; use {note['use_instead']}"
        )
    return tuple(warnings)


__all__ = [
    "ANALYSIS_FUNNEL_GROUPING_REMEDY",
    "analysis_read_error",
    "pagination_result_dimensions",
    "result_warnings",
]
