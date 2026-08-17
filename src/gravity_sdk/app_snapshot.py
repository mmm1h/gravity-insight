"""Application governance snapshot composed from six stable read contracts."""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Mapping
from typing import Any

from . import runtime
from .composite_batch import (
    annotate_result,
    composite_envelope,
    enforce_composite_item_budget,
    ordered_results,
    parent_required_result,
    validate_composite_bounds,
)
from .composite_catalog import stable_operation
from .errors import InputValidationError
from .actionable_error_values import actual_value


SCHEMA_VERSION = "gravity-insight.app-snapshot.v1"
DEFAULT_CONCURRENCY = 6
MAX_CONCURRENCY = 24


@dataclass(frozen=True)
class AppSnapshotSource:
    source: str
    operation_id: str
    scope: str
    paginated: bool


def _source(source: str, resource: str, action: str, scope: str) -> AppSnapshotSource:
    operation = stable_operation("app", resource, action=action)
    return AppSnapshotSource(
        source, operation.operation_id, scope, operation.paginated
    )


APP_SNAPSHOT_SOURCES = (
    _source("app", "detail", "get", "app"),
    _source("realtime_events", "realtime_event", "list", "app"),
    _source("capacity", "capacity", "list", "company"),
    _source("permission_menu", "permission_menu", "list", "workspace"),
    _source("roles", "role", "list", "workspace"),
    _source("templates", "template", "list", "workspace"),
)


def app_snapshot(
    client: Any,
    app_id: str | int,
    *,
    max_workers: int = DEFAULT_CONCURRENCY,
    max_pages: int = 1_000,
    max_items: int = 100_000,
) -> dict[str, Any]:
    """Return six fixed sources, using app detail as the capacity parent."""

    normalized_app_id = _positive_identifier(app_id, field="app_id")
    workers = _workers(max_workers)
    pages, items = validate_composite_bounds(
        max_pages, max_items, minimum_items=len(APP_SNAPSHOT_SOURCES)
    )
    per_source_items = max(1, items // len(APP_SNAPSHOT_SOURCES))
    first_items = per_source_items * (len(APP_SNAPSHOT_SOURCES) - 1)
    # Only capacity depends on app.detail. All other reads share the first
    # concurrency window instead of waiting behind parent discovery.
    first_sources = [
        source for source in APP_SNAPSHOT_SOURCES if source.source != "capacity"
    ]
    first_requests = [
        _request(source, app_id=normalized_app_id, company_id=None)
        for source in first_sources
    ]
    first_results = ordered_results(
        runtime.call_batch(
            client,
            first_requests,
            concurrency=workers,
            max_pages=pages,
            max_total_items=first_items,
        ),
        first_requests,
        component="app snapshot",
    )
    by_source = dict(
        (source.source, result)
        for source, result in zip(first_sources, first_results, strict=True)
    )
    detail = by_source["app"]
    company_id = _company_id(detail)

    if company_id is not None:
        capacity = APP_SNAPSHOT_SOURCES[2]
        capacity_request = _request(
            capacity, app_id=normalized_app_id, company_id=company_id
        )
        by_source[capacity.source] = ordered_results(
            runtime.call_batch(
                client,
                [capacity_request],
                concurrency=1,
                max_pages=pages,
                max_total_items=items - first_items,
            ),
            [capacity_request],
            component="app snapshot",
        )[0]
    else:
        capacity = APP_SNAPSHOT_SOURCES[2]
        by_source[capacity.source] = parent_required_result(
            capacity.operation_id,
            capacity.source,
            parent="company_id",
            component="app snapshot capacity",
        )

    enforce_composite_item_budget(list(by_source.values()), items)
    results = [
        annotate_result(by_source[source.source], source=source.source, scope=source.scope)
        for source in APP_SNAPSHOT_SOURCES
    ]
    return composite_envelope(
        results,
        schema_version=SCHEMA_VERSION,
        extra={
            "app_id": normalized_app_id,
            "company_id": company_id,
            "source_count": len(APP_SNAPSHOT_SOURCES),
            "scopes": ["app", "company", "workspace"],
        },
    )


def _request(
    source: AppSnapshotSource,
    *,
    app_id: int,
    company_id: int | None,
) -> dict[str, Any]:
    if source.scope == "app":
        inputs: dict[str, Any] = {
            "app_id": str(app_id) if source.source == "app" else app_id
        }
    elif source.scope == "company":
        if company_id is None:
            raise RuntimeError("company-scoped app snapshot request has no parent")
        inputs = {"company_id": company_id}
    else:
        inputs = {}
    return {
        "operation_id": source.operation_id,
        "request_id": source.source,
        "inputs": inputs,
        "read_all": source.paginated,
    }


def _company_id(detail_result: Mapping[str, Any]) -> int | None:
    if detail_result.get("ok") is not True:
        return None
    envelope = detail_result.get("data")
    if not isinstance(envelope, Mapping):
        return None
    data = envelope.get("data")
    if not isinstance(data, Mapping):
        return None
    app = data.get("app")
    candidate = app.get("cid") if isinstance(app, Mapping) else data.get("cid")
    try:
        return _positive_identifier(candidate, field="company_id")
    except InputValidationError:
        return None


def _positive_identifier(value: Any, *, field: str) -> int:
    if isinstance(value, bool):
        raise InputValidationError(f"actual value: {actual_value(value)}; " + (f"{field} must be a positive integer"), field=field)
    rendered = str(value).strip() if isinstance(value, (str, int)) else ""
    if not rendered.isascii() or not rendered.isdigit() or int(rendered) <= 0:
        raise InputValidationError(f"actual value: {actual_value(value)}; " + (f"{field} must be a positive integer"), field=field)
    return int(rendered)


def _workers(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_CONCURRENCY:
        raise InputValidationError(
            f"actual value: {actual_value(value)}; " + (f"app snapshot max_workers must be between 1 and {MAX_CONCURRENCY}"),
            field="max_workers",
        )
    return value


__all__ = ["APP_SNAPSHOT_SOURCES", "SCHEMA_VERSION", "app_snapshot"]
