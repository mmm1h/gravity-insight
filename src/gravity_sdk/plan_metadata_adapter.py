"""Offline metadata-search implementation for the controlled Plan adapter."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

from .find_metadata import search_metadata
from .metadata_lineage import search_table_lineage
from .plan import AdapterContext, PlanAdapter
from .plan_adapter_support import (
    bounded_optional,
    has_dynamic,
    input_error,
    metadata_projection,
    request_object,
    validate_exact_targets,
    validate_selected_fields,
)


REQUEST_FIELDS = frozenset(
    {"query", "app_id", "kind", "limit", "offset", "max_age_hours"}
)
OUTPUT_FIELDS = frozenset(
    {
        "backend", "kind", "scope", "source", "app_id", "operation_id",
        "name", "cname", "payload", "score",
        "table_id", "observed", "versions", "operations",
        "synced_at", "age_seconds", "expires_at", "stale", "fresh",
        "sync_status", "row_count", "operation_rows", "failure_count", "failures",
    }
)
VOCABULARY_KINDS = frozenset(
    {
        "metric",
        "custom_metric",
        "metric_tag",
        "metric_tag_category",
        "media_enum",
        "template",
        "vocabulary",
    }
)
KINDS = frozenset(
    {"all", "event", "property", "table_lineage", "status"}
) | VOCABULARY_KINDS


def validate_metadata_plan(
    request: Mapping[str, Any], context: AdapterContext
) -> None:
    request_object(request, REQUEST_FIELDS, "metadata_search")
    validate_exact_targets(
        context, frozenset({"/query", "/app_id", "/limit", "/offset"})
    )
    query = request.get("query", "")
    if not isinstance(query, str) and not has_dynamic(context, "/query"):
        raise input_error("metadata query must be a string", "query")
    kind = request.get("kind", "all")
    if kind not in KINDS:
        raise input_error("metadata kind is unsupported", "kind")
    app_id = request.get("app_id")
    if kind in VOCABULARY_KINDS | {"table_lineage"} and (
        app_id is not None or has_dynamic(context, "/app_id")
    ):
        raise input_error(
            f"metadata kind {kind} is not App-scoped and does not accept app_id",
            "app_id",
        )
    if app_id is not None and (
        isinstance(app_id, bool) or not isinstance(app_id, (str, int))
    ):
        raise input_error("metadata app_id must be a string or integer", "app_id")
    limit = request.get("limit", min(20, context.max_items))
    bounded_optional(limit, 1, min(100, context.max_items), "limit")
    bounded_optional(request.get("offset", 0), 0, 2**31 - 1, "offset")
    if kind == "status":
        bounded_optional(request.get("max_age_hours", 24), 1, 8_760, "max_age_hours")
    validate_selected_fields(context.output_fields, OUTPUT_FIELDS, "output_fields")


def execute_metadata_plan(
    request: Mapping[str, Any],
    context: AdapterContext,
    *,
    database: Path | None,
) -> dict[str, Any]:
    validate_metadata_plan(request, replace(context, dynamic_targets=()))
    limit = request.get("limit", min(20, context.max_items))
    bounded_optional(limit, 1, min(100, context.max_items), "limit")
    kind = str(request.get("kind", "all"))
    options = {
        "database": database,
        "limit": limit,
        "offset": request.get("offset", 0),
    }
    if kind == "status":
        from .metadata_status import metadata_status

        result = metadata_status(
            database=database,
            app_id=request.get("app_id"),
            max_age_hours=request.get("max_age_hours", 24),
        )
    elif kind == "table_lineage":
        result = search_table_lineage(str(request.get("query", "")), **options)
    else:
        result = search_metadata(
            str(request.get("query", "")),
            app_id=request.get("app_id"),
            kind=kind,
            **options,
        )
    fields = context.output_fields or tuple(sorted(OUTPUT_FIELDS))
    return metadata_projection(result, fields, context)


def build_metadata_plan_adapter(
    database: str | Path | None = None,
) -> PlanAdapter:
    """Bind the offline adapter without touching either network client.

    The general adapter set needs Insight contracts for ``run`` and
    ``composite`` preflight.  Metadata-only plans should not pay that cost, so
    the unified SDK can use this small adapter directly.
    """

    selected = Path(database) if database is not None else None

    def execute(request: Mapping[str, Any], context: AdapterContext) -> dict[str, Any]:
        return execute_metadata_plan(request, context, database=selected)

    return PlanAdapter(
        execute=execute,
        validate=validate_metadata_plan,
        project=metadata_projection,
    )


__all__ = [
    "KINDS", "OUTPUT_FIELDS", "VOCABULARY_KINDS",
    "build_metadata_plan_adapter", "execute_metadata_plan", "validate_metadata_plan",
]
