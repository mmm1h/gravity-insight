"""Bounded cross-platform Promotion Performance v1 product.

The product fans one explicit App/window/metric selection out to the closed set
of homogeneous stable promotion primary operations.  It never normalizes or
interprets platform-native metrics; the existing public client and FieldPolicy
remain the authority for live metric membership.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from . import runtime
from .composite_batch import ordered_results
from .errors import (
    GravityInsightError,
    LocalIOError,
    PaginationError,
)
from .promotion_performance_request import (
    DEFAULT_CONCURRENCY,
    INPUT_SCHEMA_VERSION,
    MAX_CONCURRENCY,
    MAX_METRICS,
    normalize_promotion_app,
    normalize_promotion_metrics,
    normalize_promotion_platforms,
    normalize_promotion_window,
    normalize_promotion_workers,
    promotion_performance_input_schema,
    validate_promotion_performance_request,
)
from .promotion_performance_error import safe_batch_error
from .promotion_performance_result import (
    PROMOTION_NON_METRIC_FIELDS,
    PROMOTION_PLATFORM_OPERATIONS,
    PROMOTION_PLATFORM_RESOURCES,
    SCHEMA_VERSION,
    SUPPORTED_PLATFORMS,
    product_envelope as _product_envelope,
    promotion_component_item_count,
    promotion_performance_item_count,
    safe_component as _safe_component,
)
from .promotion_snapshot_compat import promotion_snapshot_compat
from .result_audit import project_result_audit


_PROMOTION_EQUALS_OPERATOR = 1


def promotion_performance(
    client: Any,
    app_id: str | int,
    start: str,
    end: str,
    *,
    platforms: Sequence[str],
    metrics: Sequence[str],
    max_workers: int = DEFAULT_CONCURRENCY,
    max_pages: int = 1_000,
    max_items: int = 100_000,
) -> dict[str, Any]:
    """Read native performance rows under deterministic platform shares."""

    (
        app,
        window,
        selected_platforms,
        selected_metrics,
        workers,
        pages,
        items,
    ) = validate_promotion_performance_request(
        app_id,
        start,
        end,
        platforms=platforms,
        metrics=metrics,
        max_workers=max_workers,
        max_pages=max_pages,
        max_items=max_items,
    )
    if not callable(getattr(client, "batch", None)):
        raise TypeError(
            "promotion performance requires the public batch facade"
        )
    results, returned = _read_platform_results(
        client,
        app=app,
        window=window,
        platforms=selected_platforms,
        metrics=selected_metrics,
        workers=workers,
        max_pages=pages,
        max_items=items,
    )
    return _product_envelope(
        results,
        app_id=app,
        window=window,
        platforms=selected_platforms,
        metric_count=len(selected_metrics),
        max_pages=pages,
        max_items=items,
        max_workers=workers,
        returned_items=returned,
    )


def _read_platform_results(
    client: Any,
    *,
    app: str,
    window: tuple[str, str],
    platforms: tuple[str, ...],
    metrics: tuple[str, ...],
    workers: int,
    max_pages: int,
    max_items: int,
) -> tuple[list[dict[str, Any]], int]:
    requests = [
        _platform_request(platform, app, window, metrics)
        for platform in platforms
    ]
    ordered = _execute_batch(
        client,
        requests,
        workers=min(workers, len(requests)),
        max_pages=max_pages,
        max_items=max_items,
    )
    results = [
        project_result_audit(
            _safe_component(
                value,
                platform,
                metrics=metrics,
                expected_app_id=app,
                expected_window=window,
                max_pages=max_pages,
            ),
            value,
        )
        for platform, value in zip(platforms, ordered, strict=True)
    ]
    per_platform_items = max_items // len(platforms)
    if any(
        promotion_component_item_count(value) > per_platform_items
        for value in results
    ):
        raise PaginationError(
            "promotion performance exceeded a platform item share",
            next_action=(
                "Increase max_items or request fewer platforms; unused shares "
                "cannot be borrowed."
            ),
        )
    returned = sum(promotion_component_item_count(value) for value in results)
    if returned > max_items:
        raise PaginationError(
            "promotion performance exceeded its shared item safety bound",
            next_action=(
                "Reduce the date range or increase max_items within the limit."
            ),
        )
    return results, returned


def _platform_request(
    platform: str,
    app_id: str,
    window: tuple[str, str],
    metrics: tuple[str, ...],
) -> dict[str, Any]:
    return {
        "operation_id": PROMOTION_PLATFORM_OPERATIONS[platform],
        "request_id": platform,
        "inputs": {
            "date_list": list(window),
            "query_fields": list(metrics),
            "filters": [
                {
                    "field": "app_id",
                    "operator": _PROMOTION_EQUALS_OPERATOR,
                    "values": [app_id],
                }
            ],
            "page": 1,
            "page_size": 10,
        },
        "read_all": True,
    }


def _execute_batch(
    client: Any,
    requests: list[dict[str, Any]],
    *,
    workers: int,
    max_pages: int,
    max_items: int,
) -> list[dict[str, Any]]:
    try:
        raw = runtime.call_batch(
            client,
            requests,
            concurrency=workers,
            max_pages=max_pages,
            max_total_items=max_items,
            forward_var_kwargs=True,
        )
        return ordered_results(raw, requests, component="promotion performance")
    except GravityInsightError as exc:
        safe = safe_batch_error(exc.to_error_detail())
        raise GravityInsightError(
            safe.message,
            code=safe.code,
            retry_after_ms=safe.retry_after_ms,
            next_action=safe.next_action,
        ) from None
    except Exception:
        raise LocalIOError(
            "promotion performance batch client failed locally",
            next_action="Inspect the local Gravity client, then retry.",
        ) from None


__all__ = [
    "DEFAULT_CONCURRENCY",
    "INPUT_SCHEMA_VERSION",
    "MAX_CONCURRENCY",
    "MAX_METRICS",
    "PROMOTION_PLATFORM_OPERATIONS",
    "PROMOTION_PLATFORM_RESOURCES",
    "PROMOTION_NON_METRIC_FIELDS",
    "SCHEMA_VERSION",
    "SUPPORTED_PLATFORMS",
    "normalize_promotion_app",
    "normalize_promotion_metrics",
    "normalize_promotion_platforms",
    "normalize_promotion_window",
    "normalize_promotion_workers",
    "promotion_component_item_count",
    "promotion_performance",
    "promotion_performance_input_schema",
    "promotion_performance_item_count",
    "promotion_snapshot_compat",
    "validate_promotion_performance_request",
]
