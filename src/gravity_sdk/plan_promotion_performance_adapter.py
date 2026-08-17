"""Request-bound Plan v1 boundary for Promotion Performance."""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from typing import Any

from .errors import InputValidationError
from .plan import AdapterContext
from .plan_adapter_support import (
    input_error,
    validate_exact_targets,
    validate_selected_fields,
)
from .promotion_performance import (
    normalize_promotion_app,
    normalize_promotion_metrics,
    normalize_promotion_platforms,
    normalize_promotion_window,
)
from .promotion_performance_result import (
    PROMOTION_PLATFORM_OPERATIONS,
    PROMOTION_PLATFORM_RESOURCES,
    SCHEMA_VERSION,
    contract_component,
    contract_result,
    product_envelope,
    promotion_component_item_count,
    promotion_performance_item_count,
    safe_component,
)
from .result_audit import project_result_audit
from .actionable_error_values import actual_value


PROMOTION_PERFORMANCE_NAME = "promotion_performance"
PROMOTION_PERFORMANCE_FIELDS = frozenset(
    {"name", "app", "start", "end", "platforms", "metrics"}
)
PROMOTION_PERFORMANCE_OUTPUT_FIELDS = frozenset(
    {
        "app_id", "date_range", "failure_count", "limits", "metric_count",
        "platform_count", "results", "returned_items", "success_count",
        "total_count",
    }
)
_TARGETS = frozenset({"/app", "/start", "/end"})
_PROJECT_STRUCTURAL = frozenset(
    {"schema_version", "ok", "status", "exit_code", "error", "next_action", "result_audit"}
)


class _VerifiedResults(list[Any]):
    """In-process marker added only after request-bound reconstruction."""


def validate_promotion_performance_plan(
    request: Mapping[str, Any],
    context: AdapterContext,
    workspace: Any,
) -> None:
    """Validate the closed request with scalar bindings and literal arrays."""

    if set(request) - PROMOTION_PERFORMANCE_FIELDS:
        raise input_error(
            "promotion_performance request contains unavailable fields", "request"
        )
    if request.get("name") != PROMOTION_PERFORMANCE_NAME:
        raise input_error("promotion_performance name is invalid", "name")
    validate_exact_targets(context, _TARGETS)
    platforms = _literal_platforms(request.get("platforms"))
    _literal_metrics(request.get("metrics"))
    _validate_app(request, set(context.dynamic_targets), workspace)
    _validate_dates(request, set(context.dynamic_targets))
    if context.max_items < len(platforms):
        raise input_error(
            "promotion_performance platforms exceed this node max_items",
            "limits.max_items",
        )
    validate_selected_fields(
        context.output_fields,
        PROMOTION_PERFORMANCE_OUTPUT_FIELDS,
        "output_fields",
    )


def execute_promotion_performance_plan(
    sdk: Any,
    request: Mapping[str, Any],
    context: AdapterContext,
) -> dict[str, Any]:
    """Execute with borrowed Plan capacity, then rebuild a request-bound envelope."""

    platforms = tuple(request["platforms"])
    metrics = tuple(request["metrics"])
    with context.borrow_workers(len(platforms)) as workers:
        result = sdk.promotion_performance(
            request["app"],
            request["start"],
            request["end"],
            platforms=platforms,
            metrics=metrics,
            max_workers=workers,
            max_pages=context.max_pages,
            max_items=context.max_items,
            workspace=context.workspace,
        )
    try:
        app_id = normalize_promotion_app(
            context.workspace.resolve_app(request["app"])
        )
        window = normalize_promotion_window(request["start"], request["end"])
    except (KeyError, TypeError, ValueError):
        raise input_error(
            "promotion_performance bound App or dates are invalid", "request"
        ) from None
    safe = sanitize_product_result(
        result,
        expected_app_id=app_id,
        expected_window=window,
        expected_platforms=platforms,
        expected_metrics=metrics,
        expected_max_pages=context.max_pages,
        expected_max_items=context.max_items,
        expected_max_workers=workers,
    )
    if promotion_performance_item_count(safe) > context.max_items:
        raise input_error(
            "promotion_performance exceeded its Plan item budget",
            "limits.max_items",
        )
    if isinstance(safe.get("results"), list):
        safe["results"] = _VerifiedResults(safe["results"])
    return safe


def sanitize_product_result(
    value: Any,
    *,
    expected_app_id: str,
    expected_window: tuple[str, str],
    expected_platforms: tuple[str, ...],
    expected_metrics: tuple[str, ...],
    expected_max_pages: int,
    expected_max_items: int,
    expected_max_workers: int,
) -> dict[str, Any]:
    """Rebuild only data verified against the exact Plan request."""

    if not isinstance(value, Mapping) or value.get("schema_version") != SCHEMA_VERSION:
        return contract_result()
    if not _matches_top_level(
        value,
        app_id=expected_app_id,
        window=expected_window,
        platforms=expected_platforms,
        metrics=expected_metrics,
        max_pages=expected_max_pages,
        max_items=expected_max_items,
        max_workers=expected_max_workers,
    ):
        return contract_result()
    results = value.get("results")
    if not isinstance(results, list) or len(results) != len(expected_platforms):
        return contract_result()
    safe = [
        _resanitize_component(
            item,
            platform,
            metrics=expected_metrics,
            expected_app_id=expected_app_id,
            expected_window=expected_window,
            max_pages=expected_max_pages,
        )
        for platform, item in zip(expected_platforms, results, strict=True)
    ]
    returned = sum(promotion_component_item_count(item) for item in safe)
    per_platform = expected_max_items // len(expected_platforms)
    if returned > expected_max_items or any(
        promotion_component_item_count(item) > per_platform for item in safe
    ):
        return contract_result()
    rebuilt = product_envelope(
        safe,
        app_id=expected_app_id,
        window=expected_window,
        platforms=expected_platforms,
        metric_count=len(expected_metrics),
        max_pages=expected_max_pages,
        max_items=expected_max_items,
        max_workers=expected_max_workers,
        returned_items=returned,
    )
    checked = (
        "ok", "status", "exit_code", "error", "app_id", "platform_count",
        "metric_count", "total_count", "success_count", "failure_count",
        "returned_items",
    )
    result = rebuilt if all(
        type(value.get(key)) is type(rebuilt[key])
        and value.get(key) == rebuilt[key]
        for key in checked
    ) else contract_result()
    return project_result_audit(result, value)


def is_promotion_performance_result(value: Any) -> bool:
    return isinstance(value, Mapping) and value.get("schema_version") == SCHEMA_VERSION


def project_promotion_performance_result(
    value: Any,
    fields: tuple[str, ...],
    _context: AdapterContext,
) -> dict[str, Any]:
    """Project an envelope already rebuilt by this adapter's executor."""

    if (
        not isinstance(value, Mapping)
        or not isinstance(value.get("results"), _VerifiedResults)
    ):
        return contract_result()
    if not fields or value.get("status") == "contract_changed":
        return copy.deepcopy(dict(value))
    allowed = _PROJECT_STRUCTURAL | set(fields)
    return {
        key: copy.deepcopy(item)
        for key, item in value.items()
        if key in allowed
    }


def _matches_top_level(
    value: Mapping[str, Any],
    *,
    app_id: str,
    window: tuple[str, str],
    platforms: tuple[str, ...],
    metrics: tuple[str, ...],
    max_pages: int,
    max_items: int,
    max_workers: int,
) -> bool:
    date_range = value.get("date_range")
    limits = value.get("limits")
    return bool(
        value.get("app_id") == app_id
        and isinstance(date_range, Mapping)
        and date_range == {
            "start": window[0], "end": window[1], "inclusive": True
        }
        and type(value.get("platform_count")) is int
        and value.get("platform_count") == len(platforms)
        and type(value.get("metric_count")) is int
        and value.get("metric_count") == len(metrics)
        and isinstance(limits, Mapping)
        and limits == {
            "max_pages_per_platform": max_pages,
            "max_items_shared": max_items,
            "max_items_per_platform": max_items // len(platforms),
            "platform_workers": min(max_workers, len(platforms)),
            "page_workers_per_platform": 1,
        }
    )


def _resanitize_component(
    value: Any,
    platform: str,
    *,
    metrics: Sequence[str],
    expected_app_id: str,
    expected_window: tuple[str, str],
    max_pages: int,
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return contract_component(platform)
    expected_identity = (
        platform,
        PROMOTION_PLATFORM_RESOURCES[platform],
        PROMOTION_PLATFORM_OPERATIONS[platform],
    )
    if (
        value.get("platform"), value.get("resource"), value.get("operation_id")
    ) != expected_identity:
        return contract_component(platform)
    batch: dict[str, Any] = {
        "operation_id": value.get("operation_id"),
        "request_id": platform,
        "ok": value.get("ok"),
        "status": value.get("status"),
        "error": value.get("error"),
    }
    if value.get("ok") is True:
        batch["data"] = {
            "schema_version": "gravity-insight.read.v1",
            "operation_id": value.get("operation_id"),
            "status": value.get("status"),
            "error": None,
            "data": value.get("data"),
            "page": value.get("page"),
        }
    safe = safe_component(
        batch,
        platform,
        metrics=metrics,
        expected_app_id=expected_app_id,
        expected_window=expected_window,
        max_pages=max_pages,
    )
    checked = (
        "ok", "status", "exit_code", "error", "window_applied",
        "returned_items",
    )
    return safe if all(
        type(value.get(key)) is type(safe[key]) and value.get(key) == safe[key]
        for key in checked
    ) else contract_component(platform)


def _literal_platforms(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise input_error(
            f"actual value: {actual_value(value)}; " + ("promotion_performance platforms must be a literal array"), "platforms"
        )
    try:
        return normalize_promotion_platforms(value)
    except InputValidationError as exc:
        raise input_error(str(exc), "platforms") from None


def _literal_metrics(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise input_error(
            f"actual value: {actual_value(value)}; " + ("promotion_performance metrics must be a literal array"), "metrics"
        )
    try:
        return normalize_promotion_metrics(value)
    except InputValidationError as exc:
        raise input_error(str(exc), "metrics") from None


def _validate_app(
    request: Mapping[str, Any], dynamic: set[str], workspace: Any
) -> None:
    if "/app" in dynamic:
        return
    try:
        normalize_promotion_app(workspace.resolve_app(request.get("app")))
    except (KeyError, TypeError, ValueError):
        raise input_error(
            f"actual value: {actual_value(request.get('app'))}; " + ("promotion_performance app must select a configured workspace App"),
            "app",
        ) from None


def _validate_dates(request: Mapping[str, Any], dynamic: set[str]) -> None:
    date_dynamic = dynamic & {"/start", "/end"}
    start = "2026-01-01" if "/start" in dynamic else request.get("start")
    end = "2026-01-02" if "/end" in dynamic else request.get("end")
    try:
        if not date_dynamic:
            normalize_promotion_window(start, end)
            return
        normalize_promotion_window(start, start)
        normalize_promotion_window(end, end)
    except InputValidationError as exc:
        raise input_error(str(exc), "start/end") from None


__all__ = [
    "PROMOTION_PERFORMANCE_FIELDS",
    "PROMOTION_PERFORMANCE_NAME",
    "PROMOTION_PERFORMANCE_OUTPUT_FIELDS",
    "execute_promotion_performance_plan",
    "is_promotion_performance_result",
    "project_promotion_performance_result",
    "sanitize_product_result",
    "validate_promotion_performance_plan",
]
