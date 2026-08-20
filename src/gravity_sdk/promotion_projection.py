"""Registered native row fields for Promotion Performance."""

from types import MappingProxyType
from typing import Any, Sequence

from .domains import PROMOTION_PRIMARY_OPERATIONS
from .errors import ManifestError
from .models import load_operation_manifest
from .paths import MANIFEST_ROOT


COMMON_ROW_FIELDS = frozenset(
    {
        "id", "name", "status", "date", "day", "hour", "week", "month",
        "advertiser_id", "advertiser_name", "campaign_id", "campaign_name",
        "project_id", "project_name", "group_id", "group_name", "ad_group_id",
        "ad_group_name", "ad_unit_id", "ad_unit_name", "creative_id",
        "creative_name", "account_id", "account_name", "app_id", "app_name",
    }
)
PLATFORM_ROW_FIELDS = MappingProxyType(
    {
        "bytedance": frozenset(
            {
                "advertiser_agent_id", "advertiser_agent_name",
                "advertiser_budget_mode", "advertiser_remark",
                "advertiser_system_status", "company", "delay", "operator_id",
                "operator_name", "project_list", "stat_cost",
            }
        ),
        "tencent": frozenset(
            {
                "advertiser_agent_id", "advertiser_agent_name",
                "advertiser_budget_mode", "advertiser_remark",
                "advertiser_system_status", "company", "cost", "delay",
                "operator_id", "operator_name", "project_list",
            }
        ),
    }
)


def promotion_row_fields(platforms: tuple[str, ...]) -> MappingProxyType[str, frozenset[str]]:
    return MappingProxyType(
        {
            platform: COMMON_ROW_FIELDS | PLATFORM_ROW_FIELDS.get(platform, frozenset())
            for platform in platforms
        }
    )


def promotion_opaque_json_fields(
    platforms: tuple[str, ...], operations: Sequence[Any] | None = None
) -> MappingProxyType[str, frozenset[str]]:
    """Derive opaque row boundaries from the compiled promotion manifest."""

    loaded = (
        tuple(load_operation_manifest(MANIFEST_ROOT / "promotion.json"))
        if operations is None
        else tuple(operations)
    )
    by_id = {
        operation.operation_id: operation
        for operation in loaded
        if getattr(operation, "operation_id", None)
    }
    selected: dict[str, frozenset[str]] = {}
    for platform in platforms:
        operation_id = PROMOTION_PRIMARY_OPERATIONS.get(platform)
        operation = by_id.get(operation_id)
        if operation is None:
            raise ManifestError(
                "compiled promotion manifest is missing a primary operation"
            )
        projection = operation.response_projection
        opaque = frozenset(projection.opaque_json_item_keys)
        if opaque - set(projection.item_keys):
            raise ManifestError(
                "compiled promotion opaque JSON fields are not registered item keys"
            )
        selected[platform] = opaque
    return MappingProxyType(selected)


__all__ = [
    "COMMON_ROW_FIELDS",
    "PLATFORM_ROW_FIELDS",
    "promotion_opaque_json_fields",
    "promotion_row_fields",
]
