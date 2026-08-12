"""Bounded catalog and exact-reference reads for Saved Analysis."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .composite_catalog import stable_operation
from .errors import ContractChangedError, PaginationError
from .runtime import call_read
from .saved_analysis_support import (
    DEFAULT_MAX_ITEMS,
    DEFAULT_MAX_PAGES,
    DEFAULT_MAX_WORKERS,
    bounds,
    catalog_rows,
    require_success,
    safe_metadata,
    select_reference,
    selected_workspace,
    workers,
)
from .workspace import Workspace
from .workspace_app import resolve_workspace_app


CATALOG_SCHEMA_VERSION = "gravity-insight.saved-analysis-catalog.v1"
LIST_OPERATION_ID = stable_operation(
    "analysis", "report_config", action="list"
).operation_id
GET_OPERATION_ID = stable_operation(
    "analysis", "report_config", action="get"
).operation_id


def list_saved_analyses(
    client: Any,
    app: str | int | None = None,
    *,
    workspace: Workspace | str | Any | None = None,
    max_pages: int = DEFAULT_MAX_PAGES,
    max_items: int = DEFAULT_MAX_ITEMS,
    max_workers: int = DEFAULT_MAX_WORKERS,
) -> dict[str, Any]:
    """Return the complete safe catalog using bounded parallel page reads."""

    selected = selected_workspace(workspace)
    app_id = str(resolve_workspace_app(selected, app))
    pages, items = bounds(max_pages, max_items)
    envelope = call_read(
        client,
        LIST_OPERATION_ID,
        {"app_id": app_id, "page": 1, "page_size": 1},
        read_all=True,
        max_pages=pages,
        max_items=items,
        max_workers=workers(max_workers),
    )
    require_success(envelope, LIST_OPERATION_ID, "saved Analysis catalog")
    _require_complete(envelope)
    rows = catalog_rows(envelope, app_id)
    return {
        "schema_version": CATALOG_SCHEMA_VERSION,
        "ok": True,
        "status": "empty" if not rows else "success",
        "exit_code": 0,
        "operation_id": LIST_OPERATION_ID,
        "app_id": app_id,
        "count": len(rows),
        "items": rows,
        "network_called": True,
        "next_action": (
            "Select one item by explicit id or exact name, then prepare or execute it."
            if rows
            else "Create a saved Analysis in Gravity or select another workspace App."
        ),
    }


def read_saved_definition(
    client: Any,
    reference: str | int | Mapping[str, Any],
    app: str | int | None,
    *,
    workspace: Workspace | str | Any | None,
    max_pages: int,
    max_items: int,
    max_workers: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    from .saved_analysis_support import normalize_reference

    normalize_reference(reference)
    selected_workspace_value = selected_workspace(workspace)
    catalog = list_saved_analyses(
        client,
        app,
        workspace=selected_workspace_value,
        max_pages=max_pages,
        max_items=max_items,
        max_workers=max_workers,
    )
    selected = select_reference(catalog["items"], reference)
    detail = call_read(
        client,
        GET_OPERATION_ID,
        {"app_id": catalog["app_id"], "id": selected["id"]},
    )
    require_success(detail, GET_OPERATION_ID, "saved Analysis definition")
    data = detail.get("data") if isinstance(detail, Mapping) else None
    if not isinstance(data, Mapping) or "config" not in data:
        raise ContractChangedError(
            "saved Analysis detail did not match its projected contract",
            next_action="Stop replay until analysis.report_config.get is re-verified.",
        )
    if data.get("name") is not None and data.get("name") != selected["name"]:
        raise ContractChangedError(
            "saved Analysis identity changed between catalog and detail reads",
            next_action="List saved analyses again and retry by explicit id.",
        )
    combined = {
        key: selected[key]
        for key in ("id", "app_id", "name", "subject", "modify_time")
        if key in selected
    }
    combined["config"] = data["config"]
    return combined, safe_metadata(combined, app_id=catalog["app_id"])


def _require_complete(value: Mapping[str, Any]) -> None:
    if value.get("truncated") is True or value.get("next_page_input") not in (None, {}):
        raise PaginationError(
            "saved Analysis catalog exceeded its discovery safety bound",
            next_action=(
                "Increase max_pages/max_items within the documented limits and retry; "
                "do not treat a truncated saved Analysis catalog as complete."
            ),
        )


__all__ = [
    "CATALOG_SCHEMA_VERSION",
    "GET_OPERATION_ID",
    "LIST_OPERATION_ID",
    "list_saved_analyses",
    "read_saved_definition",
]
