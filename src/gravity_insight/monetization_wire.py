"""Private upstream request encoding for Monetization Detail."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from .wire import isolated_wire


MONETIZATION_BASE_FIELDS = (
    "CreateTime",
    "AdEventTime",
    "AdPlatform",
    "AdvertiserID",
    "AdAid",
    "TurboPromotedObjectID",
    "event$ad_type",
    "event$adn_type",
    "event$ad_unit_id",
    "event$ad_through",
    "event$ad_source_id",
    "event$ad_placement_id",
    "event$ecpm",
    "samount",
    "re_attribute_info",
)


def monetization_detail_request_parts(
    values: Mapping[str, Any],
    *,
    conditions: Sequence[Any],
    query_id: str,
    identifier: Callable[[Any, str], str | int],
) -> tuple[dict[str, Any], dict[str, Any]]:
    fields = values.get("fields") or MONETIZATION_BASE_FIELDS
    body = {
        "query_id": query_id,
        "app_id": identifier(values.get("app_id"), "app_id"),
        "page": values.get("page", 1),
        "page_size": values.get("page_size", 20),
        "order_by_list": values.get("order_by_list", []),
        "global_conditions": list(conditions),
        "cond_logic": values.get("cond_logic", "AND"),
        "local_conditions": values.get("local_conditions", []),
        "local_cond_logic": values.get("local_cond_logic", "AND"),
        "field_map": list(fields),
    }
    segment_id = values.get("segment_id")
    if segment_id not in (None, ""):
        body["segment_id"] = identifier(segment_id, "segment_id")
        body["tmp_segment_id"] = identifier(
            values.get("tmp_segment_id", segment_id), "tmp_segment_id"
        )
    return isolated_wire({}, body)


__all__ = ["MONETIZATION_BASE_FIELDS", "monetization_detail_request_parts"]
