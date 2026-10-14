"""Execution owner for the bounded material performance product."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .composite_batch import ordered_results
from .errors import ErrorDetail, GravityInsightError, LocalIOError, PaginationError
from .material_metrics import DEFAULT_GRAVITY_METRICS
from .material_performance_result import (
    material_component_item_count,
    product_envelope,
    safe_component,
)
from .result_audit import project_result_audit
from .runtime import call_batch


def execute_material_performance(
    client: Any,
    app_ids: Sequence[str | int],
    start: str,
    end: str,
    *,
    platforms: Sequence[str],
    metrics: Mapping[str, Sequence[str]] | None,
    gravity_metrics: Sequence[str] = DEFAULT_GRAVITY_METRICS,
    date_grain: str,
    data_dimension: str,
    relate_dimensions: Sequence[str],
    statistics: Sequence[str],
    order_by: Mapping[str, Sequence[Mapping[str, Any]]] | None,
    decimal_point: int | None,
    time_lines: Mapping[str, str] | None,
    max_workers: int,
    max_pages: int,
    max_items: int,
) -> dict[str, Any]:
    from .material_performance import (
        _platform_request,
        validate_material_performance_request,
    )

    apps, window, selected, profiles, workers, pages, items = (
        validate_material_performance_request(
            app_ids,
            start,
            end,
            platforms=platforms,
            metrics=metrics,
            gravity_metrics=gravity_metrics,
            date_grain=date_grain,
            data_dimension=data_dimension,
            relate_dimensions=relate_dimensions,
            statistics=statistics,
            order_by=order_by,
            decimal_point=decimal_point,
            time_lines=time_lines,
            max_workers=max_workers,
            max_pages=max_pages,
            max_items=max_items,
        )
    )
    if not callable(getattr(client, "batch", None)):
        raise TypeError("material performance requires the public batch facade")
    requests = [_platform_request(profile, apps, window) for profile in profiles]
    ordered = _execute_batch(
        client,
        requests,
        workers=min(workers, len(requests)),
        max_pages=pages,
        max_items=items,
    )
    results, returned = _safe_results(profiles, ordered, pages, items)
    return product_envelope(
        results,
        app_count=len(apps),
        window=window,
        platforms=selected,
        max_pages=pages,
        max_items=items,
        max_workers=workers,
        returned_items=returned,
        profiles=profiles,
    )


def _safe_results(
    profiles: Sequence[Any],
    ordered: Sequence[Mapping[str, Any]],
    max_pages: int,
    max_items: int,
) -> tuple[list[dict[str, Any]], int]:
    results = [
        project_result_audit(
            safe_component(value, profile, max_pages=max_pages), value
        )
        for profile, value in zip(profiles, ordered, strict=True)
    ]
    share = max_items // len(profiles)
    if any(material_component_item_count(value) > share for value in results):
        raise PaginationError(
            "material performance exceeded a platform item share",
            next_action="Increase max_items or request fewer platforms.",
        )
    returned = sum(material_component_item_count(value) for value in results)
    if returned > max_items:
        raise PaginationError(
            "material performance exceeded its shared item safety bound",
            next_action="Reduce the date range or increase max_items within the limit.",
        )
    return results, returned


def _execute_batch(
    client: Any,
    requests: list[dict[str, Any]],
    *,
    workers: int,
    max_pages: int,
    max_items: int,
) -> list[dict[str, Any]]:
    try:
        raw = call_batch(
            client,
            requests,
            concurrency=workers,
            max_pages=max_pages,
            max_total_items=max_items,
            forward_var_kwargs=True,
        )
        return ordered_results(raw, requests, component="material performance")
    except GravityInsightError as exc:
        detail = exc.to_error_detail()
        safe = ErrorDetail.create(
            detail.code,
            "Material performance batch read failed.",
            category=detail.category,
            retryable=detail.retryable,
            retry_after_ms=detail.retry_after_ms,
        )
        raise GravityInsightError(
            safe.message, code=safe.code, next_action=safe.next_action
        ) from None
    except Exception:
        raise LocalIOError(
            "material performance batch client failed locally",
            next_action="Inspect the local Gravity client, then retry.",
        ) from None


__all__ = ["execute_material_performance"]
