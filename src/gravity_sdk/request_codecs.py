"""Small, deterministic codecs for read routes with private wire filters."""

from __future__ import annotations

import json
from typing import Any, Mapping

from .errors import PolicyViolation


def analysis_segment_request_parts(
    values: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Encode the public app_id into Gravity's canonical segment filter."""

    app_id = values.get("app_id")
    if not isinstance(app_id, str) or not app_id or len(app_id) > 64:
        raise PolicyViolation("analysis segment app_id is invalid")
    filter_value: str | int = int(app_id) if app_id.isdecimal() else app_id
    return {
        "page": values.get("page", 1),
        "page_size": values.get("page_size", 100),
        "to_response_origin_query": False,
        "filters": _json_filters("app_id", 1, filter_value),
    }, {}


def analysis_account_user_request_parts(
    values: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    query: dict[str, Any] = {
        "page": values.get("page", 1),
        "page_size": values.get("page_size", 100),
    }
    filters = values.get("filters", ())
    if isinstance(filters, (list, tuple)) and filters:
        query["filters"] = json.dumps(
            list(filters), ensure_ascii=False, separators=(",", ":")
        )
    return query, {}


def app_onelink_request_parts(
    values: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Hide OneLink's raw filter grammar behind a promoted-object ID."""

    promoted_object_id = values.get("turbo_promoted_object_id")
    if (
        not isinstance(promoted_object_id, str)
        or not promoted_object_id
        or len(promoted_object_id) > 128
    ):
        raise PolicyViolation("OneLink promoted-object ID is invalid")
    return {
        "page": values.get("page", 1),
        "page_size": values.get("page_size", 10),
        "filters": _json_filters(
            "turbo_promoted_object_id", 6, promoted_object_id
        ),
    }, {}


def _json_filters(field: str, operator: str | int, value: Any) -> str:
    return json.dumps(
        [{"field": field, "operator": operator, "values": [value]}],
        ensure_ascii=False,
        separators=(",", ":"),
    )


__all__ = [
    "analysis_account_user_request_parts",
    "analysis_segment_request_parts",
    "app_onelink_request_parts",
]
