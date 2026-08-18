"""Bounded four-platform material performance product.

The product deliberately composes one existing stable operation.  It owns the
platform fan-out, shared budgets, ordering, and public result envelope; the
registered operation continues to own request encoding and response privacy.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
import re
from typing import Any

from . import runtime
from .composite_batch import (
    ordered_results,
    validate_composite_bounds,
)
from .errors import (
    ErrorDetail,
    GravityInsightError,
    InputValidationError,
    LocalIOError,
    PaginationError,
)
from .material_performance_result import (
    MATERIAL_REPORT_OPERATION,
    MATERIAL_ROW_FIELDS,
    material_component_item_count,
    material_performance_item_count,
    product_envelope as _product_envelope,
    safe_component as _safe_component,
)
from .result_audit import project_result_audit
from .actionable_error_values import actual_value
from .process_limits import MAX_CONCURRENCY


SCHEMA_VERSION = "gravity-insight.material-performance.v1"
DEFAULT_PLATFORMS = ("bytedance", "tencent", "kuaishou", "bilibili")
DEFAULT_CONCURRENCY = 6
MAX_APPS = 100
_ISO_DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")


def material_performance(
    client: Any,
    app_ids: Sequence[str | int],
    start: str,
    end: str,
    *,
    platforms: Sequence[str] = DEFAULT_PLATFORMS,
    max_workers: int = DEFAULT_CONCURRENCY,
    max_pages: int = 1_000,
    max_items: int = 100_000,
) -> dict[str, Any]:
    """Read selected platform material rows under one shared item budget.

    Each platform is one outer batch item and always uses ``read_all``.  The
    public client fixes the pagination worker inside each batch item to one, so
    ``max_workers`` controls platform fan-out only.
    """

    (
        apps,
        window,
        selected_platforms,
        workers,
        pages,
        items,
    ) = validate_material_performance_request(
        app_ids,
        start,
        end,
        platforms=platforms,
        max_workers=max_workers,
        max_pages=max_pages,
        max_items=max_items,
    )
    if not callable(getattr(client, "batch", None)):
        raise TypeError("material performance requires the public batch facade")
    requests = [
        _platform_request(platform, apps, window)
        for platform in selected_platforms
    ]
    ordered = _execute_batch(
        client, requests, workers=min(workers, len(requests)),
        max_pages=pages, max_items=items,
    )
    results = [
        project_result_audit(
            _safe_component(value, platform, max_pages=pages), value
        )
        for platform, value in zip(selected_platforms, ordered, strict=True)
    ]
    per_platform_items = items // len(selected_platforms)
    if any(
        material_component_item_count(value) > per_platform_items
        for value in results
    ):
        raise PaginationError(
            "material performance exceeded a platform item share",
            next_action="Increase max_items or request fewer platforms.",
        )
    returned = sum(material_component_item_count(value) for value in results)
    if returned > items:
        raise PaginationError(
            "material performance exceeded its shared item safety bound",
            next_action="Reduce the date range or increase max_items within the limit.",
        )
    return _product_envelope(
        results,
        app_count=len(apps),
        window=window,
        platforms=selected_platforms,
        max_pages=pages,
        max_items=items,
        max_workers=workers,
        returned_items=returned,
    )


def validate_material_performance_request(
    app_ids: Sequence[str | int],
    start: str,
    end: str,
    *,
    platforms: Sequence[str] = DEFAULT_PLATFORMS,
    max_workers: int = DEFAULT_CONCURRENCY,
    max_pages: int = 1_000,
    max_items: int = 100_000,
) -> tuple[
    tuple[str, ...], tuple[str, str], tuple[str, ...], int, int, int
]:
    """Validate every local request rule without constructing a client."""

    apps = normalize_material_apps(app_ids)
    window = normalize_material_window(start, end)
    selected_platforms = normalize_material_platforms(platforms)
    workers = normalize_material_workers(max_workers)
    pages, items = validate_composite_bounds(
        max_pages,
        max_items,
        minimum_items=len(selected_platforms),
    )
    return apps, window, selected_platforms, workers, pages, items


def normalize_material_apps(values: Sequence[str | int]) -> tuple[str, ...]:
    """Normalize resolved positive App ids without exposing them in results."""

    if isinstance(values, (str, bytes, bytearray, memoryview)) or not isinstance(
        values, Sequence
    ):
        raise InputValidationError(
            f"actual value: {actual_value(values)}; " + ("material performance apps must be a non-empty array"),
            field="apps",
        )
    selected: list[str] = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, (str, int)):
            raise InputValidationError(
                f"actual value: {actual_value(value)}; " + ("material performance apps must contain positive App ids"),
                field="apps",
            )
        rendered = str(value).strip()
        if (
            not rendered
            or len(rendered) > 128
            or not rendered.isascii()
            or not rendered.isdecimal()
            or int(rendered) <= 0
        ):
            raise InputValidationError(
                f"actual value: {actual_value(rendered)}; " + ("material performance apps must contain positive App ids"),
                field="apps",
            )
        normalized = str(int(rendered))
        if normalized in selected:
            raise InputValidationError(
                f"actual value: {actual_value(normalized)}; " + ("material performance apps must be unique"),
                field="apps",
            )
        selected.append(normalized)
    if not 1 <= len(selected) <= MAX_APPS:
        raise InputValidationError(
            f"actual value: {actual_value(normalized)}; " + (f"material performance apps must contain 1 through {MAX_APPS} unique ids"),
            field="apps",
        )
    return tuple(selected)


def normalize_material_window(start: Any, end: Any) -> tuple[str, str]:
    """Return an inclusive ISO date pair without inventing a business window."""

    if not all(
        isinstance(value, str) and _ISO_DATE.fullmatch(value)
        for value in (start, end)
    ):
        raise InputValidationError(
            f"actual value: {actual_value((start, end))}; " + ("material performance dates must use YYYY-MM-DD"),
            field="start/end",
        )
    try:
        first = date.fromisoformat(start)
        last = date.fromisoformat(end)
    except (TypeError, ValueError):
        raise InputValidationError(
            f"actual value: {actual_value((start, end))}; " + ("material performance dates must use YYYY-MM-DD"),
            field="start/end",
        ) from None
    if first > last:
        raise InputValidationError(
            f"actual value: {actual_value((start, end))}; " + ("material performance start must not follow end"),
            field="start/end",
        )
    normalized = first.isoformat(), last.isoformat()
    if normalized != (start, end):
        raise InputValidationError(
            f"actual value: {actual_value(normalized)}; " + ("material performance dates must use YYYY-MM-DD"),
            field="start/end",
        )
    return normalized


def normalize_material_platforms(values: Sequence[str]) -> tuple[str, ...]:
    """Validate the closed platform list while preserving caller order."""

    if isinstance(values, (str, bytes, bytearray)) or not isinstance(values, Sequence):
        raise InputValidationError(
            f"actual value: {actual_value(values)}; " + ("material performance platforms must be an array"),
            field="platforms",
        )
    selected: list[str] = []
    for value in values:
        if not isinstance(value, str) or value not in DEFAULT_PLATFORMS:
            raise InputValidationError(
                "material performance platform is outside the supported set",
                field="platforms", next_action="Use one of the documented platforms and retry.",
            )
        if value in selected:
            raise InputValidationError(
                f"actual value: {actual_value(value)}; " + ("material performance platforms must be unique"),
                field="platforms",
            )
        selected.append(value)
    if not selected:
        raise InputValidationError(
            f"actual value: {actual_value(selected)}; " + ("material performance requires at least one platform"),
            field="platforms",
        )
    return tuple(selected)


def normalize_material_workers(value: Any) -> int:
    if type(value) is not int or not 1 <= value <= MAX_CONCURRENCY:
        raise InputValidationError(
            f"actual value: {actual_value(value)}; " + (f"material performance max_workers must be between 1 and {MAX_CONCURRENCY}"),
            field="max_workers",
        )
    return value


def _platform_request(
    platform: str,
    apps: tuple[str, ...],
    window: tuple[str, str],
) -> dict[str, Any]:
    return {
        "operation_id": MATERIAL_REPORT_OPERATION,
        "request_id": platform,
        "inputs": {
            "app_list": list(apps),
            "date_list": list(window),
            "platform": platform,
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
            client, requests, concurrency=workers,
            max_pages=max_pages, max_total_items=max_items,
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


__all__ = [
    "DEFAULT_PLATFORMS",
    "MATERIAL_REPORT_OPERATION",
    "MATERIAL_ROW_FIELDS",
    "SCHEMA_VERSION",
    "material_component_item_count",
    "material_performance",
    "material_performance_item_count",
    "normalize_material_apps",
    "normalize_material_platforms",
    "normalize_material_window",
    "normalize_material_workers",
    "validate_material_performance_request",
]
