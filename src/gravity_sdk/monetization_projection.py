"""Registered fixed-field profiles for Monetization Detail."""

SAFE_ROW_FIELDS = (
    "CreateTime", "AdEventTime", "AdPlatform", "AdvertiserID", "AdAid",
    "TurboPromotedObjectID", "event$ad_type", "event$adn_type",
    "event$ad_unit_id", "event$ad_through", "event$ad_source_id",
    "event$ad_placement_id", "event$ecpm", "samount", "re_attribute_info",
    "user_id", "event_user_id", "device_id", "ClientID", "TraceID",
    "device_info", "user$ad_count", "user$ad_avg_ecpm", "user$ad_ltv",
    "Name", "WXOpenID",
)

SAFE_RE_ATTRIBUTE_FIELDS = (
    "ReAttributeAdAid", "ReAttributeAdCid", "ReAttributeAdGid",
    "ReAttributeAdPlatform", "ReAttributeAdvertiserID", "ReAttributeCSite",
    "ReAttributeChannel", "ReAttributeCreateTime",
    "ReAttributeTurboPromotedObjectID", "ReAttributeRetargetingCount",
    "ReAttributeAdClickTime",
)

DEVICE_INFO_FIELDS = (
    "Android_Version", "Api_Version", "Rom_version", "Aspect_Ratio",
    "Phone_Brand", "Phone_Model", "OS", "Idfa", "Idfv", "Caid1", "Caid2",
    "Oaid", "Imei", "AndroidId",
)

__all__ = ["DEVICE_INFO_FIELDS", "SAFE_RE_ATTRIBUTE_FIELDS", "SAFE_ROW_FIELDS"]
