"""Legacy Promotion snapshot surface bound to Promotion Performance v1."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .actionable_error_values import actual_value
from .errors import InputValidationError
from .workspace import load_workspace
from .workspace_app import resolve_workspace_app


_BOUND_INPUT_FIELDS = frozenset(
    {"app_id", "date_list", "filters", "page", "page_size", "query_fields"}
)


def promotion_snapshot_compat(
    client: Any,
    platforms: Sequence[str],
    *,
    resource: str = "primary",
    common_inputs: Mapping[str, Any] | None = None,
    inputs_by_platform: Mapping[str, Mapping[str, Any]] | None = None,
    read_all: bool = False,
    max_workers: int = 6,
) -> dict[str, Any]:
    """Execute the old signature through the governed Promotion product."""

    request = _bound_request(
        platforms,
        resource=resource,
        common_inputs=common_inputs,
        inputs_by_platform=inputs_by_platform,
        read_all=read_all,
        max_workers=max_workers,
    )
    from .promotion_performance import promotion_performance

    app_id, window, selected, metrics, workers, pages, items = request
    return promotion_performance(
        client,
        app_id,
        window[0],
        window[1],
        platforms=selected,
        metrics=metrics,
        max_workers=workers,
        max_pages=pages,
        max_items=items,
    )


def _bound_request(
    platforms: Sequence[str],
    *,
    resource: str,
    common_inputs: Mapping[str, Any] | None,
    inputs_by_platform: Mapping[str, Mapping[str, Any]] | None,
    read_all: bool,
    max_workers: int,
) -> tuple[str, tuple[str, str], tuple[str, ...], tuple[str, ...], int, int, int]:
    from .promotion_performance_request import (
        normalize_promotion_platforms,
        validate_promotion_performance_request,
    )

    if resource != "primary":
        raise InputValidationError(
            f"actual value: {actual_value(resource)}; legacy promotion snapshots "
            "now require the governed primary resource",
            field="resource",
            next_action=(
                "Use resource='primary' with the governed Promotion request, then retry."
            ),
        )
    if not isinstance(read_all, bool):
        _reject("read_all", read_all, "promotion snapshot read_all must be a boolean")
    if common_inputs is not None and not isinstance(common_inputs, Mapping):
        _reject(
            "common_inputs",
            common_inputs,
            "promotion snapshot common_inputs must be an object",
        )
    if inputs_by_platform is not None and not isinstance(inputs_by_platform, Mapping):
        _reject(
            "inputs_by_platform",
            inputs_by_platform,
            "promotion snapshot inputs_by_platform must be an object",
        )

    shared = dict(common_inputs or {})
    platform_inputs = dict(inputs_by_platform or {})
    bindings: list[
        tuple[str, tuple[str, str], tuple[str, ...], tuple[str, ...], int, int, int]
    ] = []
    selected = normalize_promotion_platforms(platforms)
    extra = sorted(set(platform_inputs) - set(selected))
    if extra:
        _reject(
            "inputs_by_platform",
            extra,
            "promotion snapshot inputs must name a selected supported platform",
        )
    for platform in selected:
        raw = _platform_request_inputs(shared, platform_inputs, platform)
        app_ref, start, end, metrics = _extract_binding(raw)
        preflight = validate_promotion_performance_request(
            app_ref,
            start,
            end,
            platforms=selected,
            metrics=metrics,
            max_workers=max_workers,
        )
        bindings.append(preflight)
    if any(binding != bindings[0] for binding in bindings[1:]):
        _reject(
            "inputs_by_platform",
            sorted(platform_inputs),
            "every platform must bind the same App, date window, and metrics",
        )
    app_id = resolve_workspace_app(load_workspace(), bindings[0][0])
    return validate_promotion_performance_request(
        app_id,
        bindings[0][1][0],
        bindings[0][1][1],
        platforms=bindings[0][2],
        metrics=bindings[0][3],
        max_workers=bindings[0][4],
        max_pages=bindings[0][5],
        max_items=bindings[0][6],
    )


def _platform_request_inputs(
    shared: Mapping[str, Any], platform_inputs: Mapping[str, Any], platform: str
) -> dict[str, Any]:
    specific = platform_inputs.get(platform, {})
    if not isinstance(specific, Mapping):
        _reject(
            f"inputs_by_platform.{platform}",
            specific,
            "promotion snapshot platform inputs must be an object",
        )
    result = dict(shared)
    result.update(specific)
    unknown = sorted(set(result) - _BOUND_INPUT_FIELDS)
    if unknown:
        _reject(
            "common_inputs",
            unknown,
            "promotion snapshot accepts only governed App, date, metric, and page inputs",
        )
    if result.get("page", 1) != 1:
        _reject("page", result.get("page"), "promotion snapshot page must start at 1")
    if result.get("page_size", 10) != 10:
        _reject(
            "page_size", result.get("page_size"), "promotion snapshot page_size must be 10"
        )
    return result


def _extract_binding(value: Mapping[str, Any]) -> tuple[Any, Any, Any, Any]:
    if "app_id" in value and "filters" in value:
        raise InputValidationError(
            f"actual value: {actual_value(value['filters'])}; promotion snapshot "
            "requires one unambiguous App binding",
            field="filters",
            next_action="Keep app_id or one App equality filter, remove the other, and retry.",
        )
    app_id = (
        value["app_id"] if "app_id" in value else _filtered_app(value.get("filters"))
    )
    start, end = _date_pair(value.get("date_list"))
    return app_id, start, end, value.get("query_fields")


def _filtered_app(value: Any) -> Any:
    if value is None:
        return None
    if (
        not isinstance(value, list)
        or len(value) != 1
        or not isinstance(value[0], Mapping)
        or set(value[0]) != {"field", "operator", "values"}
        or value[0].get("field") != "app_id"
        or value[0].get("operator") != 1
        or not isinstance(value[0].get("values"), list)
        or len(value[0]["values"]) != 1
    ):
        _reject(
            "filters",
            value,
            "promotion snapshot filters must contain exactly one App equality binding",
        )
    return value[0]["values"][0]


def _date_pair(value: Any) -> tuple[Any, Any]:
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray, memoryview)
    ) and len(value) == 2:
        return value[0], value[1]
    return value, None


def _reject(field: str, value: Any, reason: str) -> None:
    raise InputValidationError(
        f"actual value: {actual_value(value)}; {reason}",
        field=field,
        next_action=(
            "Use one governed App, one inclusive date pair, supported platforms, "
            "and one shared physical metric list, then retry."
        ),
    )


__all__ = ["promotion_snapshot_compat"]
