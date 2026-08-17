"""Truthful page facts derived from one upstream response."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .models import OperationSpec


def page_envelope(
    operation: OperationSpec,
    values: Mapping[str, Any],
    page_info: Mapping[str, Any],
    item_count: int,
) -> Mapping[str, Any] | None:
    if operation.pagination.kind == "none":
        return None
    page_number = page_info.get(
        operation.pagination.page_field,
        values.get(operation.pagination.page_field, 1),
    )
    page_size = page_info.get(
        operation.pagination.page_size_field,
        values.get(
            operation.pagination.page_size_field,
            operation.pagination.default_page_size,
        ),
    )
    total_pages = page_info.get(operation.pagination.total_page_field)
    total_items = page_info.get("total_number", page_info.get("total"))
    has_more = (
        page_number < total_pages
        if isinstance(page_number, int)
        and not isinstance(page_number, bool)
        and isinstance(total_pages, int)
        and not isinstance(total_pages, bool)
        else None
    )
    return {
        "number": page_number,
        "size": page_size,
        "item_count": item_count,
        "total_pages": total_pages,
        "total_items": total_items,
        "has_more": has_more,
    }


__all__ = ["page_envelope"]
