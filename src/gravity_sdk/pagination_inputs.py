"""Input validation for declared and compatibility-only page controls."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .errors import InputValidationError


def validate_page_inputs(
    fields: Mapping[str, Any], pagination: Any, values: Mapping[str, Any]
) -> None:
    """Keep positive page controls even when an operation is not paginated."""

    if pagination.kind == "page_info":
        page_field, page_size_field = pagination.page_field, pagination.page_size_field
    elif "page" in fields and "page_size" in fields:
        page_field, page_size_field = "page", "page_size"
    else:
        return
    page, size = values.get(page_field), values.get(page_size_field)
    if not isinstance(page, int) or isinstance(page, bool) or page < 1:
        raise InputValidationError(
            "page must be a positive integer",
            field=page_field,
        )
    if not isinstance(size, int) or isinstance(size, bool) or size < 1:
        raise InputValidationError(
            "page_size must be a positive integer",
            field=page_size_field,
        )
    if (
        pagination.kind == "page_info"
        and pagination.max_page_size
        and size > pagination.max_page_size
    ):
        raise InputValidationError(
            f"requested page size must stay at or below {pagination.max_page_size}",
            field=page_size_field,
        )


def pagination_schema(pagination: Any) -> dict[str, Any]:
    """Caller-facing pagination fields, including wire names for page_info."""

    if pagination.kind == "none":
        return {
            "kind": "none",
            "page_field": pagination.page_field,
            "page_size_field": pagination.page_size_field,
        }
    return {
        "kind": pagination.kind,
        "page_field": pagination.page_field,
        "page_size_field": pagination.page_size_field,
        "total_page_field": pagination.total_page_field,
        "list_path": pagination.list_path,
        "page_info_path": pagination.page_info_path,
        "default_page_size": pagination.default_page_size,
        "max_page_size": pagination.max_page_size,
    }


__all__ = ["pagination_schema", "validate_page_inputs"]
