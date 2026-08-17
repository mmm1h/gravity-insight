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
        raise InputValidationError("page must be a positive integer")
    if not isinstance(size, int) or isinstance(size, bool) or size < 1:
        raise InputValidationError("page_size must be a positive integer")
    if (
        pagination.kind == "page_info"
        and pagination.max_page_size
        and size > pagination.max_page_size
    ):
        raise InputValidationError("requested page size exceeds the operation limit")


__all__ = ["validate_page_inputs"]
