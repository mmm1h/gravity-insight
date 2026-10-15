"""Registered fixed-field profiles and safe totals for Monetization Detail."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from ._order_read import finite_json_scalar

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


def safe_monetization_total(
    value: Any, fields: tuple[str, ...] = SAFE_ROW_FIELDS
) -> list[dict[str, Any]] | None:
    if value is None:
        return []
    rows = [value] if isinstance(value, Mapping) else value
    if not isinstance(rows, list):
        return None
    result: list[dict[str, Any]] = []
    for row in rows:
        selected = _safe_total_row(row, fields)
        if selected is None:
            return None
        result.append(selected)
    return result


def _safe_total_row(
    value: Any, fields: tuple[str, ...]
) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    selected: dict[str, Any] = {}
    for field in fields:
        if field not in value:
            continue
        item = value[field]
        nested = _nested_fields(field)
        if nested is None:
            if not finite_json_scalar(item):
                return None
            selected[field] = copy.deepcopy(item)
            continue
        projected = _safe_nested_total(item, nested)
        if projected is None:
            return None
        selected[field] = projected
    return selected if selected or not value else None


def _nested_fields(field: str) -> tuple[str, ...] | None:
    return {
        "re_attribute_info": SAFE_RE_ATTRIBUTE_FIELDS,
        "device_info": DEVICE_INFO_FIELDS,
    }.get(field)


def _safe_nested_total(
    value: Any, fields: tuple[str, ...]
) -> dict[str, Any] | None:
    if not isinstance(value, Mapping) or any(
        key in value and not finite_json_scalar(value[key]) for key in fields
    ):
        return None
    return {
        key: copy.deepcopy(value[key]) for key in fields if key in value
    }

__all__ = [
    "DEVICE_INFO_FIELDS",
    "SAFE_RE_ATTRIBUTE_FIELDS",
    "SAFE_ROW_FIELDS",
    "safe_monetization_total",
]
