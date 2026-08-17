"""Governed report-directory and subscription-list products."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from .account_permission_profile import (
    PERMISSION_EMPTY_NEXT_ACTION,
    PERMISSION_EMPTY_NOTE,
)
from .errors import ContractChangedError, InputValidationError
from .report_contracts import REPORT_DETAIL, REPORT_LIST, SUBSCRIBE_LIST
from .result_source import GOVERNED_PRODUCT, result_source


DIRECTORY_SCHEMA_VERSION = "gravity-insight.report-directory.v1"
SUBSCRIPTION_SCHEMA_VERSION = "gravity-insight.report-subscriptions.v1"
SUBSCRIPTION_LIST = SUBSCRIBE_LIST
_SUCCESS = frozenset({"success", "empty", "contract_changed_additive"})


def report_directory(
    client: Any, *, max_pages: int = 1_000, max_items: int = 100_000,
    max_workers: int = 6,
) -> dict[str, Any]:
    """Read every owned report and its definition with bounded detail fan-out."""

    pages, items, workers = _bounds(max_pages, max_items, max_workers)
    listing = _read_list(client, REPORT_LIST, pages, items)
    rows = _rows(listing, REPORT_LIST)
    details: list[dict[str, Any]] = []
    if rows:
        with ThreadPoolExecutor(max_workers=min(workers, len(rows))) as pool:
            futures = [pool.submit(_report_detail, client, _identifier(row.get("id"))) for row in rows]
            details = [future.result() for future in futures]
    empty = not rows
    return {
        "schema_version": DIRECTORY_SCHEMA_VERSION,
        "result_source": result_source(GOVERNED_PRODUCT),
        "ok": True,
        "status": "empty" if empty else "success",
        "source_count": 1,
        "sources": ["owned"],
        "item_count": len(rows),
        "items": [
            {"summary": copy.deepcopy(dict(row)), "definition": detail}
            for row, detail in zip(rows, details)
        ],
        "truncated": False,
        "error": None,
        **(
            {
                "empty_result_note": PERMISSION_EMPTY_NOTE,
                "next_action": PERMISSION_EMPTY_NEXT_ACTION,
            }
            if empty
            else {}
        ),
    }


def report_subscriptions(
    client: Any, *, max_pages: int = 1_000, max_items: int = 100_000,
) -> dict[str, Any]:
    """Read the complete bounded account-level report subscription catalog."""

    pages, items, _workers = _bounds(max_pages, max_items, 1)
    listing = _read_list(client, SUBSCRIPTION_LIST, pages, items)
    rows = _rows(listing, SUBSCRIPTION_LIST)
    empty = not rows
    return {
        "schema_version": SUBSCRIPTION_SCHEMA_VERSION,
        "result_source": result_source(GOVERNED_PRODUCT),
        "ok": True,
        "status": "empty" if empty else "success",
        "item_count": len(rows),
        "items": copy.deepcopy([dict(row) for row in rows]),
        "truncated": False,
        "error": None,
        **(
            {
                "empty_result_note": PERMISSION_EMPTY_NOTE,
                "next_action": PERMISSION_EMPTY_NEXT_ACTION,
            }
            if empty
            else {}
        ),
    }


def _read_list(client: Any, operation_id: str, pages: int, items: int) -> Mapping[str, Any]:
    value = client.read_all(
        operation_id,
        {"filters": [], "page": 1, "page_size": min(100, items)},
        max_pages=pages,
        max_items=items,
        max_workers=1,
    )
    if not isinstance(value, Mapping) or value.get("error") is not None or value.get("status") not in _SUCCESS:
        raise ContractChangedError(
            f"{operation_id} did not return a consumable read envelope",
            next_action="Stop automation and re-verify the exact report list contract before retrying.",
        )
    if value.get("truncated") is True or value.get("next_page_input") not in (None, {}):
        raise InputValidationError(
            "actual value: report catalog exceeded its configured bound; allowed value: a complete bounded catalog",
            field="max_items",
            next_action="Raise max_pages or max_items within the documented limit, then retry the read.",
        )
    return value


def _rows(value: Mapping[str, Any], operation_id: str) -> list[Mapping[str, Any]]:
    data = value.get("data")
    rows = data.get("list") if isinstance(data, Mapping) else None
    if not isinstance(rows, list) or any(not isinstance(row, Mapping) for row in rows):
        raise ContractChangedError(
            f"{operation_id} no longer returns data.list",
            next_action="Stop automation until the report item contract is re-verified.",
        )
    return rows


def _report_detail(client: Any, report_id: str) -> dict[str, Any]:
    value = client.read(REPORT_DETAIL, {"id": report_id})
    if not isinstance(value, Mapping) or value.get("error") is not None or value.get("status") not in _SUCCESS:
        raise ContractChangedError(
            "report detail did not return a consumable read envelope",
            next_action="Read the exact report ID again only after the detail contract is re-verified.",
        )
    data = value.get("data")
    if not isinstance(data, Mapping) or _identifier(data.get("id")) != report_id:
        raise ContractChangedError(
            "report detail identity changed",
            next_action="Stop automation until report detail identity is re-verified.",
        )
    return copy.deepcopy(dict(data))


def _identifier(value: Any) -> str:
    selected = str(value).strip() if isinstance(value, (str, int)) and not isinstance(value, bool) else ""
    if not selected.isdecimal() or int(selected or 0) < 1 or len(selected) > 64:
        raise ContractChangedError(
            "report identity is not a positive integer",
            next_action="Stop automation until the report item identity contract is re-verified.",
        )
    return selected


def _bounds(max_pages: Any, max_items: Any, max_workers: Any) -> tuple[int, int, int]:
    selected: list[int] = []
    for field, value, maximum in (
        ("max_pages", max_pages, 1_000),
        ("max_items", max_items, 100_000),
        ("max_workers", max_workers, 24),
    ):
        if type(value) is not int or not 1 <= value <= maximum:
            raise InputValidationError(
                f"actual value: {value!r}; allowed range: 1 through {maximum}",
                field=field,
                next_action=f"Set {field} within the documented range and retry.",
            )
        selected.append(value)
    return selected[0], selected[1], selected[2]


__all__ = [
    "DIRECTORY_SCHEMA_VERSION", "REPORT_DETAIL", "REPORT_LIST",
    "SUBSCRIPTION_LIST", "SUBSCRIPTION_SCHEMA_VERSION", "report_directory",
    "report_subscriptions",
]
