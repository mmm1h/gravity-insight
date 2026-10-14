"""Bounded four-platform material performance product.

The product deliberately composes one existing stable operation.  It owns the
platform fan-out, shared budgets, ordering, and public result envelope; the
registered operation continues to own request encoding and response privacy.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
import re
from typing import Any

from .composite_batch import validate_composite_bounds
from .errors import InputValidationError
from .material_performance_result import (
    MATERIAL_REPORT_OPERATION,
    MATERIAL_ROW_FIELDS,
    material_component_item_count,
    material_performance_item_count,
)
from .actionable_error_values import actual_value
from .process_limits import MAX_CONCURRENCY
from .material_metrics import (
    DEFAULT_GRAVITY_METRICS,
    DEFAULT_MEDIA_METRICS,
    REPORT_PLATFORMS,
    validate_report_metrics,
)


SCHEMA_VERSION = "gravity-insight.material-performance.v1"
DEFAULT_PLATFORMS = ("bytedance", "tencent", "kuaishou", "bilibili")
DEFAULT_CONCURRENCY = 6
MAX_APPS = 100
_ISO_DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
DATE_GRAINS = ("day", "week", "month", "total")
DATA_DIMENSIONS = ("material", "album_id", "designer_id", "creative_user_id")
RELATED_DIMENSIONS = frozenset(
    {"album_id", "designer_id", "creative_user_id", "stat_time"}
)
STATISTICS = frozenset(
    {
        "create_time", "make_time", "album_id", "folder_id", "designer_id",
        "creative_user_id", "designer_image_id",
    }
)
_TIME_LINES = {
    "tencent": frozenset({"REPORTING_TIME", "REQUEST_TIME", "ACTIVE_TIME"}),
    "bytedance": frozenset({"bytedance_std"}),
}


@dataclass(frozen=True)
class MaterialQueryProfile:
    platform: str
    metrics: tuple[str, ...]
    gravity_metrics: tuple[str, ...]
    date_dims: str
    data_dims: tuple[str, ...]
    relate_dims: tuple[str, ...]
    stat_list: tuple[str, ...]
    order_by: tuple[tuple[str, int], ...]
    decimal_point: int | None
    time_line: str | None

    def receipt(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "platform": self.platform,
            "metrics_list": list(self.metrics),
            "gravity_metrics_list": list(self.gravity_metrics),
            "date_dims": self.date_dims,
            "data_dims": list(self.data_dims),
            "relate_dims": list(self.relate_dims),
            "stat_list": list(self.stat_list),
            "order_by": [
                {"field": field, "sort": sort} for field, sort in self.order_by
            ],
        }
        if self.decimal_point is not None:
            result["decimal_point"] = self.decimal_point
        if self.time_line is not None:
            result["time_line"] = self.time_line
        return result


def material_performance(
    client: Any,
    app_ids: Sequence[str | int],
    start: str,
    end: str,
    *,
    platforms: Sequence[str] = DEFAULT_PLATFORMS,
    metrics: Mapping[str, Sequence[str]] | None = None,
    gravity_metrics: Sequence[str] = DEFAULT_GRAVITY_METRICS,
    date_grain: str = "total",
    data_dimension: str = "material",
    relate_dimensions: Sequence[str] = (),
    statistics: Sequence[str] = (),
    order_by: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
    decimal_point: int | None = None,
    time_lines: Mapping[str, str] | None = None,
    max_workers: int = DEFAULT_CONCURRENCY,
    max_pages: int = 1_000,
    max_items: int = 100_000,
) -> dict[str, Any]:
    """Read selected platform material rows under one shared item budget.

    Each platform is one outer batch item and always uses ``read_all``.  The
    public client fixes the pagination worker inside each batch item to one, so
    ``max_workers`` controls platform fan-out only.
    """

    from .material_performance_execution import execute_material_performance

    return execute_material_performance(
        client,
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


def validate_material_performance_request(
    app_ids: Sequence[str | int],
    start: str,
    end: str,
    *,
    platforms: Sequence[str] = DEFAULT_PLATFORMS,
    metrics: Mapping[str, Sequence[str]] | None = None,
    gravity_metrics: Sequence[str] = DEFAULT_GRAVITY_METRICS,
    date_grain: str = "total",
    data_dimension: str = "material",
    relate_dimensions: Sequence[str] = (),
    statistics: Sequence[str] = (),
    order_by: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
    decimal_point: int | None = None,
    time_lines: Mapping[str, str] | None = None,
    max_workers: int = DEFAULT_CONCURRENCY,
    max_pages: int = 1_000,
    max_items: int = 100_000,
) -> tuple[
    tuple[str, ...],
    tuple[str, str],
    tuple[str, ...],
    tuple[MaterialQueryProfile, ...],
    int,
    int,
    int,
]:
    """Validate every local request rule without constructing a client."""

    apps = normalize_material_apps(app_ids)
    window = normalize_material_window(start, end)
    selected_platforms = normalize_material_platforms(platforms)
    profiles = normalize_material_profiles(
        selected_platforms,
        metrics=metrics,
        gravity_metrics=gravity_metrics,
        date_grain=date_grain,
        data_dimension=data_dimension,
        relate_dimensions=relate_dimensions,
        statistics=statistics,
        order_by=order_by,
        decimal_point=decimal_point,
        time_lines=time_lines,
    )
    workers = normalize_material_workers(max_workers)
    pages, items = validate_composite_bounds(
        max_pages,
        max_items,
        minimum_items=len(selected_platforms),
    )
    return apps, window, selected_platforms, profiles, workers, pages, items


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
        if not isinstance(value, str) or value not in REPORT_PLATFORMS:
            raise InputValidationError(
                f"actual value: {actual_value(value)}; material performance platform is "
                "outside the supported set",
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


def normalize_material_profiles(
    platforms: tuple[str, ...],
    *,
    metrics: Mapping[str, Sequence[str]] | None,
    gravity_metrics: Sequence[str],
    date_grain: str,
    data_dimension: str,
    relate_dimensions: Sequence[str],
    statistics: Sequence[str],
    order_by: Mapping[str, Sequence[Mapping[str, Any]]] | None,
    decimal_point: int | None,
    time_lines: Mapping[str, str] | None,
) -> tuple[MaterialQueryProfile, ...]:
    if metrics is not None and not isinstance(metrics, Mapping):
        raise InputValidationError(
            f"actual value: {actual_value(metrics)}; material metrics must be a platform map",
            field="metrics",
        )
    metric_map = dict(metrics or {})
    order_map = _platform_map(order_by, "order_by")
    time_map = _platform_map(time_lines, "time_lines")
    extras = (set(metric_map) | set(order_map) | set(time_map)) - set(platforms)
    if extras:
        raise InputValidationError(
            f"actual value: {actual_value(sorted(extras))}; material query options must "
            "target selected platforms",
            field="platforms",
        )
    if date_grain not in DATE_GRAINS:
        raise InputValidationError(
            f"actual value: {actual_value(date_grain)}; allowed date_grain values: "
            f"{actual_value(list(DATE_GRAINS))}",
            field="date_grain",
            next_action="Choose a documented material date grain and retry.",
        )
    if data_dimension not in DATA_DIMENSIONS:
        raise InputValidationError(
            f"actual value: {actual_value(data_dimension)}; allowed data_dimension values: "
            f"{actual_value(list(DATA_DIMENSIONS))}",
            field="data_dimension",
            next_action="Choose one documented material primary dimension and retry.",
        )
    related = _unique_allowlist(relate_dimensions, RELATED_DIMENSIONS, "relate_dimensions", 10)
    stats = _unique_allowlist(statistics, STATISTICS, "statistics", 500)
    gravity = _metric_sequence(gravity_metrics, "gravity_metrics", minimum=0)
    if decimal_point is not None and (
        type(decimal_point) is not int or decimal_point not in {2, 3, 4}
    ):
        raise InputValidationError(
            f"actual value: {actual_value(decimal_point)}; decimal_point must be 2, 3, or 4",
            field="decimal_point",
        )
    return tuple(
        _material_profile(
            platform,
            metric_map,
            gravity,
            date_grain,
            data_dimension,
            related,
            stats,
            order_map,
            decimal_point,
            time_map,
        )
        for platform in platforms
    )


def _material_profile(
    platform: str,
    metric_map: Mapping[str, Any],
    gravity: tuple[str, ...],
    date_grain: str,
    data_dimension: str,
    related: tuple[str, ...],
    stats: tuple[str, ...],
    order_map: Mapping[str, Any],
    decimal_point: int | None,
    time_map: Mapping[str, Any],
) -> MaterialQueryProfile:
    metrics = _metric_sequence(
        metric_map.get(platform, DEFAULT_MEDIA_METRICS.get(platform, ())),
        f"metrics.{platform}",
        minimum=1,
    )
    validate_report_metrics(platform, metrics, gravity)
    order = _order_rules(
        order_map.get(platform, ()), set(metrics) | set(gravity), date_grain, platform
    )
    time_line = time_map.get(platform)
    if time_line is not None and time_line not in _TIME_LINES.get(platform, ()):
        raise InputValidationError(
            f"actual value: {actual_value(time_line)}; material time line does not "
            f"match platform {platform}",
            field=f"time_lines.{platform}",
            next_action="Use the documented time line for the selected platform or omit it.",
        )
    return MaterialQueryProfile(
        platform,
        metrics,
        gravity,
        date_grain,
        (data_dimension,),
        related,
        stats,
        order,
        decimal_point,
        time_line,
    )


def _platform_map(value: Any, field: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping) or any(
        not isinstance(key, str) or key not in REPORT_PLATFORMS for key in value
    ):
        raise InputValidationError(
            f"actual value: {actual_value(value)}; {field} must be a supported platform map",
            field=field,
        )
    return dict(value)


def _metric_sequence(value: Any, field: str, *, minimum: int) -> tuple[str, ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise InputValidationError(
            f"actual value: {actual_value(value)}; {field} must be an array",
            field=field,
        )
    selected = tuple(value)
    if (
        not minimum <= len(selected) <= 500
        or any(not isinstance(item, str) or not item for item in selected)
        or len(set(selected)) != len(selected)
    ):
        raise InputValidationError(
            f"actual value: {actual_value(selected)}; {field} must contain {minimum} "
            "through 500 unique metric names",
            field=field,
        )
    return selected


def _unique_allowlist(
    value: Any, allowed: frozenset[str], field: str, maximum: int
) -> tuple[str, ...]:
    selected = _metric_sequence(value, field, minimum=0)
    if len(selected) > maximum or not set(selected) <= allowed:
        raise InputValidationError(
            f"actual value: {actual_value(selected)}; allowed {field} values: "
            f"{actual_value(sorted(allowed))}",
            field=field,
            next_action=f"Choose only documented {field} values and retry.",
        )
    return selected


def _order_rules(
    value: Any,
    metric_fields: set[str],
    date_grain: str,
    platform: str,
) -> tuple[tuple[str, int], ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise InputValidationError(
            f"actual value: {actual_value(value)}; order_by.{platform} must be an array",
            field=f"order_by.{platform}",
        )
    allowed = set(metric_fields)
    if date_grain != "total":
        allowed.add("stat_time")
    result: list[tuple[str, int]] = []
    for item in value:
        if (
            not isinstance(item, Mapping)
            or set(item) != {"field", "sort"}
            or item.get("field") not in allowed
            or type(item.get("sort")) is not int
            or item.get("sort") not in {0, 1}
        ):
            raise InputValidationError(
                f"actual value: {actual_value(item)}; order_by.{platform} must use "
                "selected metrics or non-total stat_time",
                field=f"order_by.{platform}",
            )
        pair = (str(item["field"]), int(item["sort"]))
        if pair[0] in {field for field, _ in result}:
            raise InputValidationError(
                f"actual value: {actual_value(pair[0])}; order_by.{platform} fields must be unique",
                field=f"order_by.{platform}",
            )
        result.append(pair)
    return tuple(result)


def normalize_material_workers(value: Any) -> int:
    if type(value) is not int or not 1 <= value <= MAX_CONCURRENCY:
        raise InputValidationError(
            f"actual value: {actual_value(value)}; " + (f"material performance max_workers must be between 1 and {MAX_CONCURRENCY}"),
            field="max_workers",
        )
    return value


def _platform_request(
    profile: MaterialQueryProfile,
    apps: tuple[str, ...],
    window: tuple[str, str],
) -> dict[str, Any]:
    return {
        "operation_id": MATERIAL_REPORT_OPERATION,
        "request_id": profile.platform,
        "inputs": {
            "app_list": list(apps),
            "date_list": list(window),
            **profile.receipt(),
            "page": 1,
            "page_size": 10,
        },
        "read_all": True,
    }


__all__ = [
    "DEFAULT_PLATFORMS",
    "MATERIAL_REPORT_OPERATION",
    "MATERIAL_ROW_FIELDS",
    "MaterialQueryProfile",
    "DATA_DIMENSIONS",
    "DATE_GRAINS",
    "RELATED_DIMENSIONS",
    "STATISTICS",
    "SCHEMA_VERSION",
    "material_component_item_count",
    "material_performance",
    "material_performance_item_count",
    "normalize_material_apps",
    "normalize_material_platforms",
    "normalize_material_profiles",
    "normalize_material_window",
    "normalize_material_workers",
    "validate_material_performance_request",
]
