"""Offline metadata-search implementation for the controlled Plan adapter."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

from .find_metadata import search_metadata
from .metadata_lineage import search_table_lineage
from .plan import AdapterContext
from .plan_adapter_support import (
    bounded_optional,
    has_dynamic,
    input_error,
    metadata_projection,
    request_object,
    validate_exact_targets,
    validate_selected_fields,
)


REQUEST_FIELDS = frozenset({"query", "app_id", "kind", "limit", "offset"})
OUTPUT_FIELDS = frozenset(
    {
        "kind", "app_id", "operation_id", "name", "cname", "payload", "score",
        "table_id", "observed", "versions", "operations",
    }
)
KINDS = frozenset({"all", "event", "property", "table_lineage"})


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
    if kind == "table_lineage" and (
        app_id is not None or has_dynamic(context, "/app_id")
    ):
        raise input_error(
            "table lineage is account-scoped and does not accept app_id", "app_id"
        )
    if app_id is not None and not isinstance(app_id, str):
        raise input_error("metadata app_id must be a string", "app_id")
    limit = request.get("limit", min(20, context.max_items))
    bounded_optional(limit, 1, min(100, context.max_items), "limit")
    bounded_optional(request.get("offset", 0), 0, 2**31 - 1, "offset")
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
    if kind == "table_lineage":
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


__all__ = ["execute_metadata_plan", "validate_metadata_plan"]
