"""Concurrent, fixed-scope business reporting for Agent and SDK callers.

The pulse deliberately composes existing stable report operations.  It does
not derive business conclusions, invent metric aliases, or add a second query
runtime.  The paginated business source is submitted through the public batch
facade, whose per-request pagination worker is fixed at one.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
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
from .composite_catalog import stable_operation
from .errors import InputValidationError


SCHEMA_VERSION = "gravity-insight.business-pulse.v1"
DEFAULT_CONCURRENCY = 6
MAX_CONCURRENCY = 24
DEFAULT_PLATFORMS = ("bytedance", "tencent", "kuaishou")
BUSINESS_METRICS = (
    "AdCost",
    "AppRevenue",
    "AppROI",
    "AppRealRegisterCnt",
    "AppGamePayUserCntReportingStandard",
    "AppDAUReco",
)
BUSINESS_DIMENSIONS = ("stat_datetime", "app_id", "ad_platform")


@dataclass(frozen=True)
class BusinessPulseSource:
    source: str
    operation_id: str
    scope: str
    paginated: bool


def _source(
    source: str,
    resource: str,
    action: str,
    scope: str,
) -> BusinessPulseSource:
    operation = stable_operation("report", resource, action=action)
    return BusinessPulseSource(
        source=source,
        operation_id=operation.operation_id,
        scope=scope,
        paginated=operation.paginated,
    )


OVERVIEW_SOURCE = _source("overview", "overview", "query", "app")
BUSINESS_SOURCE = _source("business", "business_report", "list", "app")
HOURLY_SOURCE = _source(
    "hourly_comparison", "hour_comparison", "query", "workspace"
)
BUSINESS_PULSE_SOURCES = (OVERVIEW_SOURCE, BUSINESS_SOURCE)


def business_pulse(
    client: Any,
    app_ids: Sequence[str | int],
    start: str,
    end: str,
    *,
    platforms: Sequence[str] = DEFAULT_PLATFORMS,
    include_hourly: bool = False,
    max_workers: int = DEFAULT_CONCURRENCY,
    max_pages: int = 1_000,
    max_items: int = 100_000,
) -> dict[str, Any]:
    """Return overview and business trends, plus optional workspace hourly data.

    Results always follow ``overview``, ``business``, ``hourly_comparison``
    order.  The hourly source is absent unless explicitly requested and is
    labelled ``scope=workspace`` because its upstream contract intentionally
    fixes the App filter to the authenticated workspace.
    """

    selected_apps = _app_ids(app_ids)
    date_range = _date_range(start, end)
    selected_platforms = _platforms(platforms)
    if not isinstance(include_hourly, bool):
        raise InputValidationError(
            "business pulse include_hourly must be a boolean",
            field="include_hourly",
        )
    workers = _workers(max_workers)
    sources = (
        (*BUSINESS_PULSE_SOURCES, HOURLY_SOURCE)
        if include_hourly
        else BUSINESS_PULSE_SOURCES
    )
    pages, items = validate_composite_bounds(
        max_pages,
        max_items,
        minimum_items=len(sources),
    )
    requests = [
        _request(
            source,
            app_ids=selected_apps,
            date_range=date_range,
            platforms=selected_platforms,
        )
        for source in sources
    ]
    raw_results = runtime.call_batch(
        client,
        requests,
        concurrency=workers,
        max_pages=pages,
        max_total_items=items,
    )
    ordered = ordered_results(
        raw_results,
        requests,
        component="business pulse",
    )
    enforce_composite_item_budget(ordered, items)
    results = [
        annotate_result(result, source=source.source, scope=source.scope)
        for source, result in zip(sources, ordered, strict=True)
    ]
    return composite_envelope(
        results,
        schema_version=SCHEMA_VERSION,
        extra={
            "app_count": len(selected_apps),
            "date_range": list(date_range),
            "platforms": list(selected_platforms),
            "include_hourly": include_hourly,
            "source_count": len(sources),
            "scopes": list(dict.fromkeys(source.scope for source in sources)),
        },
    )


def _request(
    source: BusinessPulseSource,
    *,
    app_ids: tuple[str, ...],
    date_range: tuple[str, str],
    platforms: tuple[str, ...],
) -> dict[str, Any]:
    if source is OVERVIEW_SOURCE:
        inputs: dict[str, Any] = {
            "app_ids": list(app_ids),
            "date_list": list(date_range),
            "use_cache": 0,
            "verbose": False,
        }
    elif source is BUSINESS_SOURCE:
        inputs = {
            "app_list": list(app_ids),
            "date_list": list(date_range),
            "metrics_list": list(BUSINESS_METRICS),
            "dims_list": list(BUSINESS_DIMENSIONS),
            "ad_platform_list": list(platforms),
            "need_ratio": True,
            "calc_diff": False,
            "page": 1,
            "page_size": 20,
        }
    else:
        inputs = {}
    return {
        "operation_id": source.operation_id,
        "request_id": source.source,
        "inputs": inputs,
        "read_all": source.paginated,
    }


def _app_ids(values: Sequence[str | int]) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise InputValidationError(
            "business pulse app_ids must be a non-empty array",
            field="app_ids",
        )
    normalized = tuple(
        dict.fromkeys(normalize_identifier(value, field="app_ids") for value in values)
    )
    if not normalized or len(normalized) > 100:
        raise InputValidationError(
            "business pulse app_ids must contain between 1 and 100 apps",
            field="app_ids",
        )
    return normalized


def _date_range(start: str, end: str) -> tuple[str, str]:
    try:
        first = date.fromisoformat(start)
        last = date.fromisoformat(end)
    except (TypeError, ValueError):
        raise InputValidationError(
            "business pulse dates must use YYYY-MM-DD",
            field="date_range",
        ) from None
    if first > last:
        raise InputValidationError(
            "business pulse start date must not be after end date",
            field="date_range",
        )
    return first.isoformat(), last.isoformat()


def _platforms(values: Sequence[str]) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise InputValidationError(
            "business pulse platforms must be an array",
            field="platforms",
        )
    if any(not isinstance(value, str) for value in values):
        raise InputValidationError(
            "business pulse platforms must contain strings",
            field="platforms",
        )
    selected = tuple(dict.fromkeys(values))
    unknown = [value for value in selected if value not in DEFAULT_PLATFORMS]
    if not selected or unknown:
        raise InputValidationError(
            "business pulse platforms must use bytedance, tencent, or kuaishou",
            field="platforms",
        )
    return selected


def _workers(value: int) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 1 <= value <= MAX_CONCURRENCY
    ):
        raise InputValidationError(
            f"business pulse max_workers must be between 1 and {MAX_CONCURRENCY}",
            field="max_workers",
        )
    return value


__all__ = [
    "BUSINESS_DIMENSIONS",
    "BUSINESS_METRICS",
    "BUSINESS_PULSE_SOURCES",
    "DEFAULT_PLATFORMS",
    "SCHEMA_VERSION",
    "business_pulse",
]
