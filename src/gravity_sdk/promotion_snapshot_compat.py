"""Route legacy Promotion snapshots by the guarantees their inputs support.

The formal primary-platform scope delegates to Promotion Performance v1. The
remaining inventory-backed surface stays readable through an explicitly
lower-assurance compatibility envelope.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .actionable_error_values import actual_value
from .composite_result import combined_status
from .errors import InputValidationError
from .result_source import RAW_OPERATION, result_source
from .workspace import load_workspace
from .workspace_app import resolve_workspace_app


_BOUND_INPUT_FIELDS = frozenset(
    {"app_id", "date_list", "filters", "page", "page_size", "query_fields"}
)
_PRIMARY_RESOURCES = {
    "ubix": "group",
    "taptap": "group",
    "wechat_video": "report",
}
_COMPATIBILITY_PRIMARY_PLATFORMS = frozenset(
    {"bing", "xiaohongshu", "taptap", "wechat_video"}
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
    """Use formal governance when possible and preserve inventory reach otherwise."""

    shared, platform_inputs, workers = _common_request_values(
        common_inputs,
        inputs_by_platform,
        read_all=read_all,
        max_workers=max_workers,
    )
    requested = _ids(platforms)
    _validate_resource(resource)
    if _uses_formal_path(requested, resource):
        request = _bound_request(
            requested,
            resource=resource,
            common_inputs=shared,
            inputs_by_platform=platform_inputs,
            read_all=read_all,
            max_workers=workers,
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
    return _compatibility_snapshot(
        client,
        requested,
        resource=resource,
        shared=shared,
        platform_inputs=platform_inputs,
        read_all=read_all,
        max_workers=workers,
    )


def _common_request_values(
    common_inputs: Mapping[str, Any] | None,
    inputs_by_platform: Mapping[str, Mapping[str, Any]] | None,
    *,
    read_all: bool,
    max_workers: int,
) -> tuple[dict[str, Any], dict[str, Mapping[str, Any]], int]:
    from .promotion_performance_request import normalize_promotion_workers

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
    return (
        dict(common_inputs or {}),
        dict(inputs_by_platform or {}),
        normalize_promotion_workers(max_workers),
    )


def _uses_formal_path(platforms: Sequence[str], resource: str) -> bool:
    from .promotion_performance_request import normalize_promotion_platforms
    from .promotion_performance_result import SUPPORTED_PLATFORMS

    if resource != "primary":
        return False
    if all(platform in SUPPORTED_PLATFORMS for platform in platforms):
        return True
    unsupported = [
        platform
        for platform in platforms
        if platform not in SUPPORTED_PLATFORMS
        and platform not in _COMPATIBILITY_PRIMARY_PLATFORMS
    ]
    if unsupported:
        normalize_promotion_platforms(unsupported)
    return False


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


def _compatibility_snapshot(
    client: Any,
    platforms: Sequence[str],
    *,
    resource: str,
    shared: dict[str, Any],
    platform_inputs: dict[str, Mapping[str, Any]],
    read_all: bool,
    max_workers: int,
) -> dict[str, Any]:
    selected = _compatibility_selection(platforms, platform_inputs)
    requests, unavailable, resources = _compatibility_requests(
        client,
        selected,
        resource=resource,
        shared=shared,
        platform_inputs=platform_inputs,
        read_all=read_all,
    )
    completed = client.batch(requests, max_workers=max_workers) if requests else []
    results = _ordered_results(
        selected,
        completed=completed,
        unavailable=unavailable,
        resources=resources,
    )
    return {
        "schema_version": "gravity-insight.composite.promotion.v1",
        "result_source": result_source(RAW_OPERATION),
        "status": _batch_status(results),
        "resource": resource,
        "compatibility": {
            "mode": "inventory",
            "formal_binding_validation": "not_performed",
        },
        "coverage": _batch_coverage(len(selected), results),
        "results": results,
    }


def _compatibility_selection(
    platforms: Sequence[str],
    inputs_by_platform: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    selected = list(dict.fromkeys(platforms))
    if not selected:
        _reject("platforms", selected, "promotion snapshot requires at least one platform")
    extra = sorted(set(inputs_by_platform) - set(selected))
    if extra:
        _reject(
            "inputs_by_platform",
            extra,
            "promotion inputs must name a selected platform",
        )
    return selected


def _compatibility_requests(
    client: Any,
    selected: list[str],
    *,
    resource: str,
    shared: dict[str, Any],
    platform_inputs: dict[str, Mapping[str, Any]],
    read_all: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, str]]:
    requests: list[dict[str, Any]] = []
    unavailable: list[dict[str, Any]] = []
    resources: dict[str, str] = {}
    for platform in selected:
        selected_resource = (
            _PRIMARY_RESOURCES.get(platform, "advertiser")
            if resource == "primary"
            else resource
        )
        resources[platform] = selected_resource
        matches = _matches(client, platform, selected_resource)
        if not matches:
            unavailable.append(_unavailable(platform, selected_resource))
            continue
        operation_id = _unique_operation_id(
            matches,
            platform=platform,
            resource=selected_resource,
        )
        inputs = dict(shared)
        specific = platform_inputs.get(platform, {})
        if not isinstance(specific, Mapping):
            _reject(
                f"inputs_by_platform.{platform}",
                specific,
                "promotion snapshot platform inputs must be an object",
            )
        inputs.update(specific)
        requests.append(
            {
                "request_id": platform,
                "operation_id": operation_id,
                "inputs": inputs,
                "read_all": read_all,
            }
        )
    return requests, unavailable, resources


def _matches(client: Any, platform: str, resource: str) -> list[Mapping[str, Any]]:
    return [
        item
        for item in client.operations(
            domain="promotion", platform=platform, stability="stable"
        )
        if item.get("resource") == resource
        and item.get("action") in {"list", "query"}
    ]


def _unique_operation_id(
    matches: Sequence[Mapping[str, Any]], *, platform: str, resource: str
) -> str:
    candidates = sorted(str(item.get("operation_id")) for item in matches)
    if len(candidates) != 1:
        _reject(
            "resource",
            candidates,
            f"promotion snapshot inventory matched multiple stable reads for "
            f"{platform}/{resource}",
            next_action=(
                "Choose one listed operation_id with `gravity promotion query`, or "
                "request a platform/resource pair with exactly one stable read operation."
            ),
        )
    return candidates[0]


def _unavailable(platform: str, resource: str) -> dict[str, Any]:
    return {
        "operation_id": None,
        "platform": platform,
        "resource": resource,
        "ok": False,
        "status": "unavailable",
        "data": None,
        "error": "no stable read operation is registered for this platform/resource",
    }


def _ordered_results(
    selected: list[str],
    *,
    completed: Sequence[Mapping[str, Any]],
    unavailable: Sequence[Mapping[str, Any]],
    resources: Mapping[str, str],
) -> list[dict[str, Any]]:
    by_platform = {
        str(item.get("request_id")): {
            **item,
            "platform": str(item.get("request_id")),
            "resource": resources.get(str(item.get("request_id"))),
        }
        for item in completed
    }
    unavailable_by_platform = {
        str(item["platform"]): dict(item) for item in unavailable
    }
    return [
        by_platform.get(platform)
        or unavailable_by_platform.get(platform)
        or _missing(platform, resources[platform])
        for platform in selected
    ]


def _missing(platform: str, resource: str) -> dict[str, Any]:
    return {
        "operation_id": None,
        "platform": platform,
        "resource": resource,
        "ok": False,
        "status": "error",
        "data": None,
        "error": "the batch did not return a result for this platform",
    }


def _ids(values: Sequence[str]) -> list[str]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        _reject(
            "platforms",
            values,
            "promotion snapshot platforms must be an array of non-empty strings",
        )
    if any(not isinstance(item, str) or not item for item in values):
        _reject(
            "platforms",
            [type(item).__name__ for item in values],
            "promotion snapshot platforms must be an array of non-empty strings",
        )
    return list(values)


def _validate_resource(value: Any) -> None:
    if not isinstance(value, str) or not value:
        _reject(
            "resource",
            value,
            "promotion snapshot resource must be a non-empty string",
        )


def _batch_status(results: Sequence[Mapping[str, Any]]) -> str:
    if not results:
        return "empty"
    statuses = [str(item.get("status", "error")) for item in results]
    successes = sum(bool(item.get("ok")) for item in results)
    if successes == len(results):
        return combined_status(statuses)
    return "partial" if successes else "unavailable"


def _batch_coverage(
    requested: int, results: Sequence[Mapping[str, Any]]
) -> dict[str, int]:
    successful = sum(bool(item.get("ok")) for item in results)
    unavailable = sum(
        str(item.get("status")) == "unavailable" for item in results
    )
    return {
        "requested": requested,
        "completed": len(results),
        "successful": successful,
        "failed": len(results) - successful,
        "unavailable": unavailable,
    }


def _reject(
    field: str,
    value: Any,
    reason: str,
    *,
    next_action: str | None = None,
) -> None:
    raise InputValidationError(
        f"actual value: {actual_value(value)}; {reason}",
        field=field,
        next_action=next_action
        or (
            "Use one governed App/date/metric request, or provide exact raw inputs "
            "for one inventory-backed compatibility platform/resource, then retry."
        ),
    )


__all__ = ["promotion_snapshot_compat"]
