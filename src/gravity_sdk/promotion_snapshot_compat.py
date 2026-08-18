"""Legacy 25-platform promotion snapshot implementation.

This module preserves the original composite result and permissive input
behavior.  It is intentionally separate from the closed Promotion Performance
product so the two contracts cannot grow into one ambiguous API.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .composite_result import combined_status
from .actionable_error_values import actual_value
from .errors import InputValidationError
from .result_source import RAW_OPERATION, result_source


_PRIMARY_RESOURCES = {
    "ubix": "group",
    "taptap": "group",
    "wechat_video": "report",
}


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
    """Preserve the pre-v1 CompositeService contract verbatim."""

    selected = _selection(platforms, resource, inputs_by_platform)
    shared = dict(common_inputs or {})
    platform_inputs = dict(inputs_by_platform or {})
    requests, unavailable, resources = _requests(
        client,
        selected,
        resource=resource,
        shared=shared,
        platform_inputs=platform_inputs,
        read_all=read_all,
    )
    completed = (
        client.batch(requests, max_workers=max_workers) if requests else []
    )
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
        "coverage": _batch_coverage(len(selected), results),
        "results": results,
    }


def _selection(
    platforms: Sequence[str],
    resource: str,
    inputs_by_platform: Mapping[str, Mapping[str, Any]] | None,
) -> list[str]:
    selected = list(dict.fromkeys(_ids(platforms)))
    if not selected:
        raise InputValidationError(
            f"actual value: {actual_value(selected)}; promotion snapshot requires at "
            "least one platform",
            field="platforms",
        )
    if not isinstance(resource, str) or not resource:
        raise InputValidationError(
            f"actual value: {actual_value(resource)}; promotion snapshot resource must "
            "be a non-empty string",
            field="resource",
        )
    extra = sorted(set(dict(inputs_by_platform or {})) - set(selected))
    if extra:
        raise InputValidationError(
            f"actual value: {actual_value(extra)}; promotion inputs must name a "
            "selected platform; remove the extra keys",
            field="inputs_by_platform",
        )
    return selected


def _requests(
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
        operation_id = str(
            sorted(matches, key=lambda item: str(item["operation_id"]))[0][
                "operation_id"
            ]
        )
        inputs = dict(shared)
        inputs.update(platform_inputs.get(platform, {}))
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


def _unavailable(platform: str, resource: str) -> dict[str, Any]:
    return {
        "operation_id": None,
        "platform": platform,
        "resource": resource,
        "ok": False,
        "status": "unavailable",
        "data": None,
        "error": (
            "no stable read operation is registered for this platform/resource"
        ),
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
    if isinstance(values, (str, bytes)) or any(
        not isinstance(item, str) or not item for item in values
    ):
        raise InputValidationError(
            f"actual value: {actual_value(type(values).__name__ if isinstance(values, (str, bytes)) else [type(item).__name__ for item in values])}; "
            "operation/platform identifiers must be non-empty strings",
            field="platforms",
        )
    return list(values)


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


__all__ = ["promotion_snapshot_compat"]
