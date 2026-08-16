"""Additive caller-facing evidence for a paginated read result."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .result_audit import result_receipt_references


def pagination_audit(
    result: Mapping[str, Any], inputs: Mapping[str, Any], *, all_pages: bool,
    bounded: bool = False,
    http_requests_made: int | None = None,
) -> dict[str, Any]:
    """Summarize actual page work without changing the raw result envelope."""

    page = result.get("page")
    page = page if isinstance(page, Mapping) else {}
    request = result.get("request")
    request_inputs = request.get("inputs") if isinstance(request, Mapping) else {}
    request_inputs = request_inputs if isinstance(request_inputs, Mapping) else {}
    requested_size = inputs.get("page_size")
    effective_size = request_inputs.get("page_size")
    returned_items = page.get("item_count")
    total_items = page.get("total_items")
    has_more = _has_more(page)
    return {
        "mode": "all_pages" if all_pages else "bounded" if bounded else "single_page",
        "operation_requests_made": _operation_request_count(result, page),
        "http_requests_made": (
            http_requests_made
            if http_requests_made is not None
            else len(result_receipt_references(result))
        ),
        "requested_page_size": requested_size,
        "effective_page_size": effective_size,
        "page_size_clamped": _page_size_clamped(requested_size, effective_size),
        "completeness": {
            "criterion": "has_more=false and returned_items=total_items",
            "status": _completeness_status(has_more, returned_items, total_items),
            "has_more": has_more,
            "returned_items": returned_items,
            "total_items": total_items,
        },
    }


def _operation_request_count(result: Mapping[str, Any], page: Mapping[str, Any]) -> int:
    fetched = page.get("pages_fetched")
    if isinstance(fetched, int) and not isinstance(fetched, bool) and fetched >= 0:
        return fetched
    return 1 if result.get("ok") is True else 0


def _has_more(page: Mapping[str, Any]) -> bool | None:
    value = page.get("has_more")
    if isinstance(value, bool):
        return value
    number, total_pages = page.get("number"), page.get("total_pages")
    if (
        isinstance(number, int)
        and not isinstance(number, bool)
        and isinstance(total_pages, int)
        and not isinstance(total_pages, bool)
    ):
        return number < total_pages
    return None


def _page_size_clamped(requested: Any, effective: Any) -> bool:
    return (
        isinstance(requested, int)
        and not isinstance(requested, bool)
        and isinstance(effective, int)
        and not isinstance(effective, bool)
        and requested != effective
    )


def _completeness_status(
    has_more: bool | None, returned_items: Any, total_items: Any
) -> str:
    if has_more is None or not isinstance(returned_items, int) or not isinstance(total_items, int):
        return "unknown"
    return "complete" if not has_more and returned_items == total_items else "partial"


__all__ = ["pagination_audit"]
