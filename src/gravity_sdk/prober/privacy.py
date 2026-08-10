"""Value-free response sketches and fail-closed projection policy."""

from __future__ import annotations

import re
from typing import Any, Mapping, Sequence


SENSITIVE_TOKENS = frozenset(
    {
        "authorization", "cookie", "password", "secret", "token", "uid",
        "user", "userid", "user_id", "device", "device_id", "phone",
        "mobile", "email", "idfa", "idfv", "imei", "oaid", "androidid",
        "android_id", "caid", "openid", "open_id", "unionid", "union_id",
        "order", "order_id", "ip", "ip_address", "client_id", "trace_id",
        "session_id",
        "operator", "operator_id", "operator_name",
        "creator", "creator_id", "creator_name", "dept", "department",
        "designer", "latitude", "longitude", "gps", "url",
    }
)

SENSITIVE_EXACT_FIELDS = frozenset(
    {
        "account_name", "advertiser_name", "after_value", "auth_ids",
        "before_value", "company", "company_name", "private_key",
        "public_key", "real_name", "username", "address", "birthdate",
        "birthday", "gender", "home_address", "precise_location",
    }
)

REVIEWED_SENSITIVE_FIELDS: Mapping[str, str] = {
    "{dynamic_key}": "unbounded_dynamic_object_key_review",
    "app_dict": "unbounded_metadata_container_review",
    "col_name_en_cn_dict": "unbounded_metadata_container_review",
    "condition": "opaque_user_level_condition_review",
    "description": "free_text_field_review",
    "info": "unbounded_metadata_container_review",
    "last_request_api": "request_route_may_contain_identifiers_review",
    "message": "free_text_field_review",
    "name_en_cn_dict": "unbounded_metadata_container_review",
    "remark": "free_text_field_review",
    "state_reason": "free_text_field_review",
    "table_remark": "free_text_field_review",
    "tag": "free_text_audience_label_review",
    "thumbnail": "resource_url_review",
    "title_list": "free_text_material_list_review",
}

# Gravity ``cid`` is the company/tenant identifier, not a natural-person
# identifier. Reassess this decision if the SDK is expanded to a multi-tenant
# context (for example, an agency account that can observe multiple companies).
REVIEWED_NON_SENSITIVE_FIELDS: Mapping[str, str] = {
    "agetype": "targeting_enum_shape_review",
    "cid": "tenant_company_identifier_review",
    "data_topic": "fixed_report_topic_enum_review",
    "delivery_range": "targeting_enum_shape_review",
    "district": "targeting_region_enum_review",
    "file_md5": "non_personal_asset_fingerprint_review",
    "material": "nested_projection_container_review",
    "order": "display_sort_index_review",
    "params_md5": "non_personal_parameter_fingerprint_review",
    "table_cname": "metadata_display_name_review",
    "target": "frontend_select_enum_review",
    "value": "numeric_or_option_value_review",
}

SAFE_TOKENS = frozenset(
    {
        "id", "name", "cname", "label", "title", "status", "type", "code",
        "category", "platform", "count", "cnt", "total", "number", "num",
        "page", "page_size", "total_page", "total_number", "date", "day",
        "week", "month", "year", "time", "created_at", "updated_at",
        "create_time", "modify_time", "start_date", "end_date", "is_enabled",
        "visible", "enabled",
        "idx", "sort", "tip", "is_system", "media", "source",
        "applied_to_all", "booking", "bundle", "channel", "condition_result",
        "converted_time_duration", "cover_num", "create_at", "flag",
        "has_alum", "hide_if_converted", "hour", "is_activity", "is_ai",
        "is_deleted", "is_scene", "is_section", "isdel", "marketing_goal",
        "material_num", "metric_cname", "mode", "os", "plan_num",
        "region_version", "row_num", "state", "title_num", "trigger",
        "update_at", "upload_num", "version",
    }
)

SAFE_SUFFIXES = (
    "_id", "_name", "_count", "_cnt", "_date", "_time", "_status",
    "_type", "_number", "_total",
)

REVIEWED_SAFE_FIELDS: Mapping[str, frozenset[str]] = {
    "material.asset_material_media_review_list.list": frozenset(
        {"suggestion"}
    ),
    "metadata.event_property_template_event_list.list": frozenset(
        {"is_common", "is_preset", "trigger_opportunity"}
    ),
    "metadata.property.list": frozenset(
        {"is_common", "is_preset"}
    ),
    "promotion.bilibili.account.list": frozenset(
        {
            "average_cost_per_thousand",
            "click_rate",
            "cost_per_click",
            "san_lian_launch_total_consume",
            "total_cash_consume",
            "total_consume",
            "total_red_packet_consume",
            "total_special_red_packet_consume",
        }
    ),
    "material.bytedance_asset_text_title.list": frozenset(
        {
            "history_click_rate", "history_cost", "last_3_day_click_rate",
            "last_3_day_cost",
        }
    ),
    "material.bytedance_asset_text_title_package.list": frozenset(
        {
            "history_click_rate", "history_cost", "last_3_day_click_rate",
            "last_3_day_cost",
        }
    ),
    "material.bytedance_std_asset_text_title.list": frozenset(
        {
            "history_click_rate", "history_cost", "last_3_day_click_rate",
            "last_3_day_cost",
        }
    ),
    "material.bytedance_std_asset_text_title_package.list": frozenset(
        {
            "history_click_rate", "history_cost", "last_3_day_click_rate",
            "last_3_day_cost",
        }
    ),
    "promotion.ai_trusteeship.list": frozenset(
        {"boost_value", "caliber", "check_fre", "frequency"}
    ),
    "promotion.bytedance.site.list": frozenset({"siteId", "siteType"}),
    "report.company_amount.query": frozenset(
        {"ad_create_amount_usage", "material_transmit_g_usage"}
    ),
    "report.media_report.list": frozenset({"cost"}),
}

AGGREGATE_REPORT_OPERATIONS = frozenset(
    {"report.hour_comparison.query", "report.overview.query"}
)

AGGREGATE_REPORT_FIELDS = frozenset(
    {
        "adcost", "appactivepayamountsumreco", "appadfirstdayrevenuereco",
        "appadrevenuereco", "appdaureco", "appfirstdaypayamountstandardreco",
        "approireco", "apprealregistercnt", "apprevenuereco", "base",
        "compare", "hour", "ratio",
    }
)

METADATA_DICTIONARY_OPERATIONS = frozenset(
    {"metadata.operation_log.list", "metadata.version.list"}
)

METADATA_DICTIONARY_MARKERS = (
    ".col_name_en_cn_dict.", ".info.name_cname.", ".name_en_cn_dict.",
)


def _json_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, Mapping):
        return "object"
    return "unknown"


def safe_schema_key(value: Any) -> str:
    key = str(value)
    lowered = key.casefold()
    if (
        len(key) > 64
        or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key)
        or "@" in key
        or re.fullmatch(r"[0-9a-f]{16,}", lowered)
        or re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", lowered)
    ):
        return "{dynamic_key}"
    return key


def response_schema_sketch(value: Any) -> dict[str, Any]:
    """Return path/type observations without retaining response values."""

    observed: dict[str, set[str]] = {}

    def visit(item: Any, path: str, depth: int) -> None:
        observed.setdefault(path, set()).add(_json_type(item))
        if depth >= 12:
            return
        if isinstance(item, Mapping):
            for raw_key, child in item.items():
                visit(child, f"{path}.{safe_schema_key(raw_key)}", depth + 1)
        elif isinstance(item, list):
            if not item:
                observed.setdefault(path + "[]", set()).add("unknown")
            for child in item[:200]:
                visit(child, path + "[]", depth + 1)

    visit(value, "$", 0)
    paths = [
        {"path": path, "types": sorted(types), "presence": "observed"}
        for path, types in sorted(observed.items())
    ]
    return {"schema_version": "gravity-insight.raw-schema-sketch.v1", "paths": paths}


def classify_field(path: str) -> tuple[str, str]:
    """Classify a field name conservatively; manual review stays hidden."""

    field = path.rsplit(".", 1)[-1].replace("[]", "").casefold()
    tokens = set(re.findall(r"[a-z0-9]+", field))
    compact = field.replace("_", "")
    sensitive_reason = REVIEWED_SENSITIVE_FIELDS.get(field)
    if sensitive_reason is not None:
        return "sensitive", sensitive_reason
    reviewed_reason = REVIEWED_NON_SENSITIVE_FIELDS.get(field)
    if reviewed_reason is not None:
        return "non_sensitive", reviewed_reason
    if (
        field in SENSITIVE_EXACT_FIELDS
        or field in SENSITIVE_TOKENS
        or compact in SENSITIVE_TOKENS
        or tokens & SENSITIVE_TOKENS
        or any(token in field for token in ("password", "cookie", "authorization"))
    ):
        return "sensitive", "sensitive_name_pattern"
    if field in SAFE_TOKENS or field.endswith(SAFE_SUFFIXES):
        return "non_sensitive", "business_metadata_name_pattern"
    return "manual_review", "no_confident_name_pattern"


def classify_candidate_field(
    path: str, *, operation_id: str | None = None
) -> tuple[str, str]:
    """Classify one observed field with narrowly scoped semantic context."""

    field_name = path.rsplit(".", 1)[-1].replace("[]", "")
    classification, reason = classify_field(path)
    if classification != "manual_review":
        return classification, reason

    reviewed = REVIEWED_SAFE_FIELDS.get(str(operation_id), frozenset())
    if field_name in reviewed:
        return "non_sensitive", "route_specific_field_review"

    normalized = path.casefold()
    field = field_name.casefold()
    if (
        operation_id in AGGREGATE_REPORT_OPERATIONS
        and field in AGGREGATE_REPORT_FIELDS
        and normalized.startswith("data.")
    ):
        return "non_sensitive", "aggregate_metric_field_review"
    if (
        operation_id in METADATA_DICTIONARY_OPERATIONS
        and any(marker in normalized for marker in METADATA_DICTIONARY_MARKERS)
        and field != "{dynamic_key}"
    ):
        return "non_sensitive", "metadata_dictionary_field_review"
    return classification, reason


def candidate_fields(
    sketch: Mapping[str, Any], *, operation_id: str | None = None
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for item in sketch.get("paths", []):
        if not isinstance(item, Mapping):
            continue
        path = str(item.get("path", ""))
        types = sorted(str(value) for value in item.get("types", []))
        if not path.startswith("$.data.") and not path.startswith("$.data[]"):
            continue
        if path.endswith("[]") or set(types) <= {"array", "object", "unknown"}:
            continue
        normalized = path.removeprefix("$.")
        field_name = normalized.rsplit(".", 1)[-1].replace("[]", "")
        classification, reason = classify_candidate_field(
            normalized, operation_id=operation_id
        )
        candidates.append(
            {
                "path": normalized,
                "types": types,
                "presence": "observed",
                "privacy_classification": classification,
                "classification_reason": reason,
                "expose": classification == "non_sensitive",
            }
        )
    return candidates


def _classified(path: str, candidates: Mapping[str, Mapping[str, Any]]) -> str:
    item = candidates.get(path)
    if item is not None:
        return str(item.get("privacy_classification", "manual_review"))
    return classify_field(path)[0]


def _mapping_keys(rows: Sequence[Any]) -> set[str]:
    keys: set[str] = set()
    for row in rows:
        if isinstance(row, Mapping):
            keys.update(safe_schema_key(key) for key in row)
    return keys


def _list_projection(data: list[Any], by_path: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    keys = _mapping_keys(data)
    safe = sorted(
        key for key in keys if _classified(f"data[].{key}", by_path) == "non_sensitive"
    )
    projection: dict[str, Any] = {
        "data_keys": [], "required_data_keys": [], "item_keys": safe,
        "dynamic_item_fields": [], "data_shape": "list",
    }
    hidden = sorted(keys - set(safe))
    if hidden:
        projection["known_omitted_item_keys"] = hidden
    return projection


def _mapping_projection(
    data: Mapping[str, Any], by_path: Mapping[str, Mapping[str, Any]]
) -> dict[str, Any]:
    projection: dict[str, Any] = {
        "data_keys": [], "required_data_keys": [], "item_keys": [],
        "dynamic_item_fields": [],
    }
    exposed: list[str] = []
    omitted: list[str] = []
    for raw_key, value in data.items():
        key = safe_schema_key(raw_key)
        if key == "list" and isinstance(value, list):
            keys = _mapping_keys(value)
            safe = sorted(
                name for name in keys
                if _classified(f"data.list[].{name}", by_path) == "non_sensitive"
            )
            if safe:
                exposed.append(key)
                projection["required_data_keys"].append(key)
                projection["item_keys"] = safe
                hidden = sorted(keys - set(safe))
                if hidden:
                    projection["known_omitted_item_keys"] = hidden
            else:
                omitted.append(key)
        elif key == "page_info" and isinstance(value, Mapping):
            child_keys = {safe_schema_key(name) for name in value}
            if child_keys and all(
                _classified(f"data.page_info.{name}", by_path) == "non_sensitive"
                for name in child_keys
            ):
                exposed.append(key)
            else:
                omitted.append(key)
        elif isinstance(value, list):
            keys = _mapping_keys(value)
            safe = sorted(
                name for name in keys
                if _classified(f"data.{key}[].{name}", by_path) == "non_sensitive"
            )
            hidden = sorted(keys - set(safe))
            if safe and not (key == "total" and hidden):
                exposed.append(key)
                projection.setdefault("data_item_keys", {})[key] = safe
                if hidden:
                    projection.setdefault("known_omitted_data_item_keys", {})[key] = hidden
            else:
                omitted.append(key)
        elif not isinstance(value, (Mapping, list)) and _classified(
            f"data.{key}", by_path
        ) == "non_sensitive":
            exposed.append(key)
        else:
            omitted.append(key)
    projection["data_keys"] = sorted(set(exposed))
    projection["required_data_keys"] = sorted(set(projection["required_data_keys"]))
    if omitted:
        projection["known_omitted_data_keys"] = sorted(set(omitted))
    return projection


def build_projection(
    payload: Mapping[str, Any], fields: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    """Build a fail-closed projection from already classified candidates."""

    by_path = {str(item.get("path", "")): item for item in fields}
    data = payload.get("data")
    if isinstance(data, list):
        return _list_projection(data, by_path)
    if isinstance(data, Mapping):
        return _mapping_projection(data, by_path)
    return {
        "data_keys": [], "required_data_keys": [], "item_keys": [],
        "dynamic_item_fields": [],
    }


def projection_exposes_path(path: str, projection: Mapping[str, Any]) -> bool:
    """Return whether a candidate leaf is present in a projection allowlist."""

    normalized = path.removeprefix("$.")
    if not normalized.startswith("data"):
        return False
    remainder = normalized.removeprefix("data")
    if remainder.startswith("[]"):
        remainder = remainder[2:]
    remainder = remainder.removeprefix(".")
    if not remainder:
        return False

    segments = remainder.split(".")
    first = segments[0]
    first_name = first.removesuffix("[]")
    data_keys = {str(value) for value in projection.get("data_keys", ())}
    item_keys = {str(value) for value in projection.get("item_keys", ())}

    if normalized.startswith("data[]"):
        return len(segments) == 1 and first_name in item_keys
    if first == "list[]":
        if "list" not in data_keys or len(segments) < 2:
            return False
        item_name = segments[1].removesuffix("[]")
        if item_name not in item_keys:
            return False
        return _nested_projection_exposes(
            item_name, segments[2:], projection.get("nested_item_keys", {})
        )
    if len(segments) == 1:
        return first_name in data_keys
    if first.endswith("[]"):
        if first_name not in data_keys:
            return False
        allowed = projection.get("data_item_keys", {})
        if not isinstance(allowed, Mapping):
            return False
        item_name = segments[1].removesuffix("[]")
        return item_name in {str(value) for value in allowed.get(first_name, ())}
    return False


def _nested_projection_exposes(
    parent: str, remaining: Sequence[str], nested: Any
) -> bool:
    if not remaining:
        return True
    if not isinstance(nested, Mapping):
        return False
    child = remaining[0].removesuffix("[]")
    if child not in {str(value) for value in nested.get(parent, ())}:
        return False
    return _nested_projection_exposes(child, remaining[1:], nested)
