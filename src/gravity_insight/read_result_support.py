"""Small helpers for constructing governed read-result envelopes."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .models import OperationSpec
from .pagination_completeness import page_completeness


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


__all__ = ["pagination_result_dimensions", "result_warnings"]
