"""Merge fetched pages into one caller-facing read envelope."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .drift import aggregate_contract_status
from .fingerprints import shape_fingerprint
from .models import OperationSpec, ReadResult
from .result_audit import add_result_audit
from .response_drift import merge_response_drifts


def merge_pages(
    operation: OperationSpec,
    pages: Sequence[ReadResult],
    items: Sequence[Any],
    *,
    page_size: int | None,
    total_pages: int | None,
    has_more: bool | None,
    strategy: str,
    max_workers: int,
) -> dict[str, Any]:
    """Collapse ordered page results without changing fetch strategy."""

    result = pages[0].to_dict()
    item_field = operation.pagination.list_path.rsplit(".", 1)[-1] or "list"
    if isinstance(result["data"], Mapping):
        result["data"] = dict(result["data"])
        result["data"][item_field] = list(items)
    else:
        result["data"] = list(items)
    result["fetched_at"] = pages[-1].fetched_at
    result["warnings"] = list(
        dict.fromkeys(warning for page in pages for warning in page.warnings)
    )
    result["status"] = (
        contract_status
        if (contract_status := aggregate_contract_status({page.status for page in pages}))
        else "empty"
        if not items
        else "success"
    )
    final_page = pages[-1].page or {}
    first_page = pages[0].page or {}
    result["page"] = {
        "number": first_page.get("number", 1),
        "size": page_size,
        "item_count": len(items),
        "total_pages": total_pages,
        "total_items": final_page.get("total_items"),
        "has_more": has_more,
        "pages_fetched": len(pages),
        "fetch_strategy": strategy,
        "max_workers": max_workers,
    }
    result["schema_fingerprint"] = shape_fingerprint(result["data"])
    return add_result_audit(
        result,
        [reference for page in pages for reference in page.http_receipts],
        response_drift=merge_response_drifts([page.response_drift for page in pages]),
    )


def truncate_nonpaginated_result(
    result: dict[str, Any], max_items: int
) -> tuple[int, int]:
    data = result.get("data")
    if isinstance(data, list):
        original = len(data)
        result["data"] = data[:max_items]
        return len(result["data"]), original
    if isinstance(data, Mapping):
        for key in ("list", "items"):
            rows = data.get(key)
            if isinstance(rows, list):
                original = len(rows)
                result["data"] = {**dict(data), key: rows[:max_items]}
                return min(original, max_items), original
    count = envelope_item_count(result)
    return count, count


def envelope_item_count(envelope: Mapping[str, Any]) -> int:
    page = envelope.get("page")
    if isinstance(page, Mapping):
        count = page.get("item_count")
        if isinstance(count, int) and not isinstance(count, bool) and count >= 0:
            return count
    data = envelope.get("data")
    if isinstance(data, list):
        return len(data)
    if isinstance(data, Mapping):
        for key in ("list", "items"):
            rows = data.get(key)
            if isinstance(rows, list):
                return len(rows)
    return 0


__all__ = ["envelope_item_count", "merge_pages", "truncate_nonpaginated_result"]
