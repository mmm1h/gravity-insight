"""Formal operation bindings retained behind the legacy Promotion snapshot."""

from __future__ import annotations

from collections.abc import Mapping
from functools import lru_cache
from types import MappingProxyType
from typing import Any

from .domains import PROMOTION_PLATFORMS
from .models import OperationSpec, load_operation_manifest
from .paths import MANIFEST_ROOT
from .promotion_performance_result import PromotionComponentBinding


_FORMAL_RESOURCE_PLATFORMS = {
    "project": ("bytedance",),
    "ad_group": ("honor",),
    "campaign": ("honor",),
    "ad_unit": ("kuaishou",),
}
PROMOTION_SNAPSHOT_RESOURCE_OPERATIONS = MappingProxyType(
    {
        resource: MappingProxyType(
            {
                platform: PROMOTION_PLATFORMS[platform][resource]
                for platform in platforms
            }
        )
        for resource, platforms in _FORMAL_RESOURCE_PLATFORMS.items()
    }
)

_BOUND_INPUTS = frozenset(
    {
        "date_list",
        "filtering",
        "filters",
        "order_by",
        "page",
        "page_size",
        "query_fields",
    }
)
_RESULT_DATA_KEYS = ("list", "page_info", "total", "update_at")


@lru_cache(maxsize=None)
def promotion_component_binding(
    platform: str, resource: str, operation_id: str
) -> PromotionComponentBinding:
    """Bind one explicitly approved snapshot operation to its compiled contract."""

    operation = _operation(operation_id)
    if (
        operation.platform,
        operation.resource,
        operation.stability,
        operation.executable,
    ) != (platform, resource, "stable", True):
        raise RuntimeError("formal Promotion snapshot operation identity changed")
    _validate_request_shape(operation)
    _validate_result_shape(operation)
    projection = operation.response_projection
    return PromotionComponentBinding(
        platform=platform,
        resource=resource,
        operation_id=operation_id,
        row_fields=frozenset(projection.item_keys),
        opaque_json_fields=frozenset(projection.opaque_json_item_keys),
    )


def promotion_performance_snapshot(
    client: Any,
    request: tuple[
        str,
        tuple[str, str],
        tuple[str, ...],
        tuple[str, ...],
        int,
        int,
        int,
    ],
    *,
    resource: str,
) -> dict[str, Any]:
    """Execute a preflighted snapshot through Promotion Performance internals."""

    if resource == "primary":
        return _primary_performance(client, request)
    from .promotion_performance import _validated_performance

    bindings = _resource_bindings(resource, request[2])
    return _validated_performance(client, request, bindings=bindings)


def _resource_bindings(
    resource: str, platforms: tuple[str, ...]
) -> Mapping[str, PromotionComponentBinding]:
    operations = PROMOTION_SNAPSHOT_RESOURCE_OPERATIONS.get(resource)
    if operations is None or any(platform not in operations for platform in platforms):
        raise RuntimeError("Promotion snapshot formal resource binding is not registered")
    return {
        platform: promotion_component_binding(
            platform, resource, operations[platform]
        )
        for platform in platforms
    }


def _primary_performance(
    client: Any,
    request: tuple[
        str,
        tuple[str, str],
        tuple[str, ...],
        tuple[str, ...],
        int,
        int,
        int,
    ],
) -> dict[str, Any]:
    from .promotion_performance import promotion_performance

    app_id, window, platforms, metrics, workers, pages, items = request
    return promotion_performance(
        client,
        app_id,
        window[0],
        window[1],
        platforms=platforms,
        metrics=metrics,
        max_workers=workers,
        max_pages=pages,
        max_items=items,
    )


def _operation(operation_id: str) -> OperationSpec:
    operations = {
        operation.operation_id: operation
        for operation in load_operation_manifest(MANIFEST_ROOT / "promotion.json")
    }
    selected = operations.get(operation_id)
    if selected is None:
        raise RuntimeError("formal Promotion snapshot operation is missing")
    return selected


def _validate_request_shape(operation: OperationSpec) -> None:
    input_names = frozenset(field.name for field in operation.input_fields)
    required = frozenset(
        field.name for field in operation.input_fields if field.required
    )
    if input_names != _BOUND_INPUTS or required != frozenset({"date_list"}):
        raise RuntimeError("formal Promotion snapshot request contract changed")
    if frozenset(operation.request.body_fields) != _BOUND_INPUTS:
        raise RuntimeError("formal Promotion snapshot request placement changed")


def _validate_result_shape(operation: OperationSpec) -> None:
    projection = operation.response_projection
    pagination = operation.pagination
    if (
        projection.data_shape != "object"
        or projection.data_keys != _RESULT_DATA_KEYS
        or projection.required_data_keys != ("list",)
        or projection.dynamic_item_fields != ("query_fields",)
    ):
        raise RuntimeError("formal Promotion snapshot result contract changed")
    if (
        pagination.kind != "page_info"
        or pagination.list_path != "data.list"
        or pagination.default_page_size != 10
        or pagination.max_page_size != 10
    ):
        raise RuntimeError("formal Promotion snapshot pagination contract changed")
    if operation.privacy_policy.classification != "internal_business":
        raise RuntimeError("formal Promotion snapshot privacy classification changed")


__all__ = [
    "PROMOTION_SNAPSHOT_RESOURCE_OPERATIONS",
    "promotion_component_binding",
    "promotion_performance_snapshot",
]
