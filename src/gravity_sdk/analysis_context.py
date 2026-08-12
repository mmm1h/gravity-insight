"""Fixed, concurrent analysis metadata context for SDK and Agent callers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from . import runtime
from .composite_batch import (
    annotate_result,
    composite_envelope,
    enforce_composite_item_budget,
    normalize_identifier,
    ordered_results,
    validate_composite_bounds,
)
from .composite_catalog import identity_contains, identity_excludes, stable_operation
from .errors import InputValidationError


SCHEMA_VERSION = "gravity-insight.analysis-context.v1"
DEFAULT_CONCURRENCY = 6
MAX_CONCURRENCY = 24


@dataclass(frozen=True)
class AnalysisContextSource:
    source: str
    operation_id: str
    scope: str
    paginated: bool


def _source(
    source: str,
    domain: str,
    resource: str,
    scope: str,
    *,
    identity: str | None = None,
    excludes: str | None = None,
) -> AnalysisContextSource:
    predicate = (
        identity_contains(identity)
        if identity is not None
        else identity_excludes(excludes)
        if excludes is not None
        else None
    )
    operation = stable_operation(domain, resource, action="list", predicate=predicate)
    return AnalysisContextSource(
        source, operation.operation_id, scope, operation.paginated
    )


ANALYSIS_CONTEXT_SOURCES = (
    _source("events", "analysis", "event", "app"),
    _source("event_properties", "analysis", "event_property", "app"),
    _source("event_property_groups", "analysis", "event_property_group", "app"),
    _source("user_properties", "analysis", "user_property", "app"),
    _source("report_metrics", "report", "metric", "workspace", identity="multidim"),
    _source("custom_metrics", "report", "custom_metric", "workspace", excludes="shared"),
    _source(
        "shared_custom_metrics", "report", "custom_metric", "workspace", identity="shared"
    ),
    _source("metric_tags", "report", "metric_tag", "workspace"),
    _source("metric_tag_categories", "report", "metric_tag_category", "workspace"),
    _source("media_enums", "report", "media_enum", "workspace"),
    _source("mine_templates", "report", "template", "workspace", identity="mine"),
    _source("shared_templates", "report", "template", "workspace", identity="shared"),
    _source("preset_templates", "report", "template", "workspace", identity="preset"),
)


def analysis_context(
    client: Any,
    app_id: str | int,
    *,
    max_workers: int = DEFAULT_CONCURRENCY,
    max_pages: int = 1_000,
    max_items: int = 100_000,
) -> dict[str, Any]:
    """Read the complete contracted analysis vocabulary with failure isolation."""

    normalized_app_id = normalize_identifier(app_id, field="app_id")
    workers = _workers(max_workers)
    pages, items = validate_composite_bounds(
        max_pages, max_items, minimum_items=len(ANALYSIS_CONTEXT_SOURCES)
    )
    requests = [_request(source, normalized_app_id) for source in ANALYSIS_CONTEXT_SOURCES]
    raw_results = runtime.call_batch(
        client,
        requests,
        concurrency=workers,
        max_pages=pages,
        max_total_items=items,
    )
    ordered = ordered_results(raw_results, requests, component="analysis context")
    enforce_composite_item_budget(ordered, items)
    results = [
        annotate_result(result, source=source.source, scope=source.scope)
        for source, result in zip(ANALYSIS_CONTEXT_SOURCES, ordered, strict=True)
    ]
    return composite_envelope(
        results,
        schema_version=SCHEMA_VERSION,
        extra={
            "app_id": normalized_app_id,
            "source_count": len(ANALYSIS_CONTEXT_SOURCES),
            "scopes": ["app", "workspace"],
        },
    )


def _request(source: AnalysisContextSource, app_id: str) -> dict[str, Any]:
    inputs = {"app_id": app_id} if source.scope == "app" else {}
    return {
        "operation_id": source.operation_id,
        "request_id": source.source,
        "inputs": inputs,
        "read_all": source.paginated,
    }


def _workers(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_CONCURRENCY:
        raise InputValidationError(
            f"analysis context max_workers must be between 1 and {MAX_CONCURRENCY}",
            field="max_workers",
        )
    return value


__all__ = ["ANALYSIS_CONTEXT_SOURCES", "SCHEMA_VERSION", "analysis_context"]
