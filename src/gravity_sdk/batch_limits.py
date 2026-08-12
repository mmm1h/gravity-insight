"""Shared aggregate limits for the public concurrent read batch."""

from __future__ import annotations

from .http_runtime import MAX_CONCURRENCY


MAX_READ_PAGES = 1_000
MAX_READ_ITEMS = 100_000


def validate_batch_limits(
    *, max_workers: int, max_pages: int, max_total_items: int, request_count: int
) -> None:
    for field, value, upper in (
        ("max_workers", max_workers, MAX_CONCURRENCY),
        ("max_pages", max_pages, MAX_READ_PAGES),
        ("max_total_items", max_total_items, MAX_READ_ITEMS),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= upper:
            raise ValueError(f"batch {field} must be between 1 and {upper}")
    if request_count > max_total_items:
        raise ValueError("batch request count exceeds its aggregate item safety bound")


__all__ = ["MAX_READ_ITEMS", "MAX_READ_PAGES", "validate_batch_limits"]
