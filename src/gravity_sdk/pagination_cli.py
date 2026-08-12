"""Argparse and runtime option helpers for paginated CLI reads."""

from __future__ import annotations

import argparse
from typing import Any

from .cli_limits import concurrency, positive_int


DEFAULT_STDOUT_MAX_PAGES = 5
DEFAULT_STDOUT_MAX_ITEMS = 200
MAX_ALL_PAGES = 1_000
MAX_ALL_ITEMS = 100_000


def add_pagination_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--all-pages",
        action="store_true",
        help="Follow the manifest pagination contract.",
    )
    parser.add_argument(
        "--max-pages",
        type=positive_int,
        help=f"Maximum pages (stdout default: {DEFAULT_STDOUT_MAX_PAGES}).",
    )
    parser.add_argument(
        "--max-items",
        type=positive_int,
        help=f"Maximum returned items (stdout default: {DEFAULT_STDOUT_MAX_ITEMS}).",
    )
    parser.add_argument(
        "--concurrency",
        type=concurrency,
        default=6,
        help="Parallel page workers when total pages are known (default: 6).",
    )
    parser.add_argument("--output", help="Write JSON or NDJSON to this local path.")
    parser.add_argument(
        "--format",
        choices=("json", "ndjson"),
        default="json",
        help="Output encoding; NDJSON may stream to stdout.",
    )


def page_limits(args: Any, *, all_pages: bool) -> tuple[int, int]:
    defaults = (
        (MAX_ALL_PAGES, MAX_ALL_ITEMS)
        if all_pages
        else (DEFAULT_STDOUT_MAX_PAGES, DEFAULT_STDOUT_MAX_ITEMS)
    )
    return (
        int(getattr(args, "max_pages", None) or defaults[0]),
        int(getattr(args, "max_items", None) or defaults[1]),
    )


def page_options(
    args: Any, *, all_pages: bool, active: bool
) -> dict[str, int | None]:
    if not active:
        return {"max_pages": None, "max_items": None, "max_workers": None}
    max_pages, max_items = page_limits(args, all_pages=all_pages)
    return {
        "max_pages": max_pages,
        "max_items": max_items,
        "max_workers": getattr(args, "concurrency", None),
    }


__all__ = [
    "DEFAULT_STDOUT_MAX_ITEMS",
    "DEFAULT_STDOUT_MAX_PAGES",
    "add_pagination_arguments",
    "page_limits",
    "page_options",
]
