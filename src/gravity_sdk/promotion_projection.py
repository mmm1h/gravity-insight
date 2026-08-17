"""Registered native row fields for Promotion Performance."""

from types import MappingProxyType


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
                "advertiser_system_status", "company", "project_list", "stat_cost",
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
