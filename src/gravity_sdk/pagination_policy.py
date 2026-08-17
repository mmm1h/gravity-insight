"""Fail-closed continuation rules for ``page_info`` reads.

A full first page is not evidence of another page.  Continuation without an
observed ``total_page`` requires an explicit caller opt-in.
"""

from __future__ import annotations


STOPPED_MISSING_TOTAL_PAGE = "stopped_missing_total_page"
SERIAL_UNKNOWN_TOTAL = "serial_unknown_total"


def has_next_page(
    item_count: int,
    page_number: int | None,
    page_size: int | None,
    total_pages: int | None,
    *,
    continue_without_total: bool = False,
) -> bool:
    """Return whether another page request is justified."""

    if page_number is not None and total_pages is not None:
        return page_number < total_pages
    if not continue_without_total:
        return False
    return bool(page_size and item_count >= page_size)


def unknown_total_strategy(*, continue_without_total: bool) -> str:
    """Name the fetch strategy used when ``total_page`` is absent."""

    if continue_without_total:
        return SERIAL_UNKNOWN_TOTAL
    return STOPPED_MISSING_TOTAL_PAGE


__all__ = [
    "SERIAL_UNKNOWN_TOTAL",
    "STOPPED_MISSING_TOTAL_PAGE",
    "has_next_page",
    "unknown_total_strategy",
]
