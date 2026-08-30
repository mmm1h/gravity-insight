"""Offline input-validation result envelope."""

from __future__ import annotations

from typing import Any

from .errors import (
    ErrorCode,
    ErrorDetail,
    GravityInsightError,
    PolicyViolation,
    error_detail_from_exception,
)


def validation_error(
    operation_id: str, error: GravityInsightError
) -> dict[str, Any]:
    detail: ErrorDetail
    if isinstance(error, PolicyViolation) and "catalog-only" in str(error):
        detail = ErrorDetail.create(
            ErrorCode.NOT_IMPLEMENTED, error, operation_id=operation_id
        )
    else:
        detail = error_detail_from_exception(error, operation_id=operation_id)
    return {
        "schema_version": "gravity-insight.validation.v1",
        "ok": False,
        "status": "invalid",
        "operation_id": operation_id,
        "network_called": False,
        "normalized_input": None,
        "live_metadata_dependencies": [],
        "error": detail.to_dict(),
    }


__all__ = ["validation_error"]
