"""Plan composite adapter for bounded single-App metadata synchronization."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

from .metadata_onboarding import MAX_APP_SYNC_PAGES
from .plan import AdapterContext
from .plan_adapter_support import (
    bounded_optional,
    has_dynamic,
    request_object,
    validate_exact_targets,
    validate_selected_fields,
)


NAME = "metadata_sync"
REQUEST_FIELDS = frozenset({"name", "app"})
OUTPUT_FIELDS = frozenset(
    {
        "app_id",
        "app_count",
        "catalog_app_count",
        "database",
        "failure_count",
        "failures",
        "failures_truncated",
        "http_receipts_available",
        "http_requests_observed",
        "logical_requests_made",
        "operation_count",
        "operation_pages",
        "operation_rows",
        "request_budget",
        "retry_count_observed",
        "rows_written",
        "scope",
        "synced_at",
    }
)


def is_metadata_sync(name: Any) -> bool:
    return name == NAME


def validate_metadata_sync(
    request: Mapping[str, Any], context: AdapterContext
) -> None:
    request_object(request, REQUEST_FIELDS, NAME)
    validate_exact_targets(context, frozenset({"/app"}))
    bounded_optional(context.max_pages, 1, MAX_APP_SYNC_PAGES, "limits.max_pages")
    validate_selected_fields(context.output_fields, OUTPUT_FIELDS, "output_fields")
    if not has_dynamic(context, "/app"):
        context.workspace.resolve_app(request.get("app"))


def execute_metadata_sync(
    sdk: Any,
    request: Mapping[str, Any],
    context: AdapterContext,
    *,
    database: Path | None,
) -> dict[str, Any]:
    validate_metadata_sync(request, replace(context, dynamic_targets=()))
    app_id = context.workspace.resolve_app(request.get("app"))
    with context.borrow_workers(4) as workers:
        return sdk.sync_metadata_app(
            app_id,
            database=database,
            max_pages=context.max_pages,
            concurrency=workers,
        )


__all__ = [
    "NAME",
    "OUTPUT_FIELDS",
    "execute_metadata_sync",
    "is_metadata_sync",
    "validate_metadata_sync",
]
