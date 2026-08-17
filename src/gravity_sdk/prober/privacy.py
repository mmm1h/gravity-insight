"""Value-free response sketches and fail-closed contract projection policy."""

from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

from .nested_projection import (
    build_container_contract,
    merge_allowed_fields,
    merge_omitted_fields,
)
from .privacy_reviews import (
    REVIEWED_SAFE_FIELDS,
    ROUTE_REVIEWED_CONTRACT_FIELDS,
)
from .schema_sketch import json_type, response_schema_sketch, safe_schema_key


CREDENTIAL_TOKENS = frozenset(
    {
        "access_token", "authorization", "cookie", "password", "private_key",
        "refresh_token", "secret", "session_token", "token",
    }
)
_CREDENTIAL_COMPACT = frozenset(item.replace("_", "") for item in CREDENTIAL_TOKENS)

AUTHORIZED_DATA_FIELDS = frozenset(
    {
        "account_name", "advertiser_name", "after_value", "auth_ids", "avatar",
        "before_value", "company", "company_name", "email", "idfa", "idfv",
        "imei", "is_superuser", "mobile", "oaid", "openid", "phone",
        "public_key", "real_name", "unionid", "username", "address",
        "birthdate", "birthday", "gender", "home_address", "ip", "ip_address",
        "precise_location", "url",
    }
)

REVIEWED_MANUAL_FIELDS: Mapping[str, str] = {
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
_OPAQUE_OBJECT_ITEM_FIELDS = frozenset({"creative_components"})

BYTEDANCE_TEXT_TITLE_METRIC_FIELDS = frozenset(
    {
        "history_click_rate",
        "history_cost",
        "last_3_day_click_rate",
        "last_3_day_cost",
    }
)
BYTEDANCE_TEXT_TITLE_OPERATION_RE = re.compile(
    r"^material\.bytedance_[a-z0-9_]*text_title[a-z0-9_]*\.list$"
)
AI_TRUSTEESHIP_OPERATION_RE = re.compile(
    r"^promotion\.ai_trusteeship\.[a-z0-9_]+$"
)
AI_TRUSTEESHIP_SAFE_FIELDS = frozenset(
    {"boost_value", "caliber", "check_fre", "frequency"}
)
FAMILY_SAFE_FIELD_RULES = (
    (BYTEDANCE_TEXT_TITLE_OPERATION_RE, BYTEDANCE_TEXT_TITLE_METRIC_FIELDS),
    (AI_TRUSTEESHIP_OPERATION_RE, AI_TRUSTEESHIP_SAFE_FIELDS),
)

AGGREGATE_REPORT_RESOURCES = frozenset({"hour_comparison", "overview"})

AGGREGATE_REPORT_FIELDS = frozenset(
    {
        "adcost", "appactivepayamountsumreco", "appadfirstdayrevenuereco",
        "appadrevenuereco", "appdaureco", "appfirstdaypayamountstandardreco",
        "approireco", "apprealregistercnt", "apprevenuereco", "base",
        "compare", "hour", "ratio",
    }
)

METADATA_DICTIONARY_RESOURCES = frozenset({"operation_log", "version"})

METADATA_DICTIONARY_MARKERS = (
    ".col_name_en_cn_dict.", ".info.name_cname.", ".name_en_cn_dict.",
)


def _reviewed_safe_fields(operation_id: str | None) -> frozenset[str]:
    normalized = str(operation_id)
    family_fields: set[str] = set()
    for pattern, fields in FAMILY_SAFE_FIELD_RULES:
        if pattern.fullmatch(normalized):
            family_fields.update(fields)
    return REVIEWED_SAFE_FIELDS.get(normalized, frozenset()) | frozenset(family_fields)


def _reviewed_contract_fields(operation_id: str | None) -> frozenset[str]:
    return ROUTE_REVIEWED_CONTRACT_FIELDS.get(str(operation_id), frozenset())


def _is_metadata_dictionary_operation(operation_id: str | None) -> bool:
    parts = str(operation_id).split(".")
    return (
        len(parts) == 3
        and parts[0] == "metadata"
        and parts[1] in METADATA_DICTIONARY_RESOURCES
        and parts[2] == "list"
    )


def _is_aggregate_report_operation(operation_id: str | None) -> bool:
    parts = str(operation_id).split(".")
    return (
        len(parts) == 3
        and parts[0] == "report"
        and parts[1] in AGGREGATE_REPORT_RESOURCES
        and parts[2] == "query"
    )


def classify_field(path: str) -> tuple[str, str]:
    """Classify credentials separately from authorized data and unknown fields."""

    field = path.rsplit(".", 1)[-1].replace("[]", "").casefold()
    tokens = set(re.findall(r"[a-z0-9]+", field))
    compact = field.replace("_", "")
    manual_reason = REVIEWED_MANUAL_FIELDS.get(field)
    if manual_reason is not None:
        return "manual_review", manual_reason
    reviewed_reason = REVIEWED_NON_SENSITIVE_FIELDS.get(field)
    if reviewed_reason is not None:
        return "non_sensitive", reviewed_reason
    if (
        field in CREDENTIAL_TOKENS
        or compact in _CREDENTIAL_COMPACT
        or tokens & CREDENTIAL_TOKENS
        or any(token in field for token in ("password", "cookie", "authorization"))
    ):
        return "sensitive", "credential_name_pattern"
    if field in AUTHORIZED_DATA_FIELDS or any(
        token in tokens
        for token in {
            "creator", "department", "dept", "designer", "device", "operator",
            "user", "userid", "uid",
        }
    ):
        return "non_sensitive", "upstream_authorized_data_field"
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
    if field_name.casefold() in _reviewed_contract_fields(operation_id):
        return "manual_review", "route_specific_contract_field_review"

    reviewed = _reviewed_safe_fields(operation_id)
    if field_name in reviewed:
        return "non_sensitive", "route_specific_field_review"

    normalized = path.casefold()
    field = field_name.casefold()
    if (
        _is_aggregate_report_operation(operation_id)
        and field in AGGREGATE_REPORT_FIELDS
        and normalized.startswith("data.")
    ):
        return "non_sensitive", "aggregate_metric_field_review"
    if (
        _is_metadata_dictionary_operation(operation_id)
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
        scalar_list_leaf = (
            bool(types)
            and path == "$.data.list[]"
            and set(types) <= {"string", "integer", "number", "boolean"}
        )
        if (path.endswith("[]") and not scalar_list_leaf) or set(types) <= {
            "array",
            "object",
            "unknown",
        }:
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


def _container_contract(
    value: Any, path: str, by_path: Mapping[str, Mapping[str, Any]]
) -> tuple[list[str], list[str], dict[str, list[str]], dict[str, list[str]]]:
    return build_container_contract(
        [value], path, lambda candidate: _classified(candidate, by_path)
    )


def _scalar_list_type(value: Any) -> str | None:
    if not isinstance(value, list) or not value:
        return None
    observed = {json_type(item) for item in value}
    if not observed <= {"string", "integer", "number", "boolean"}:
        return None
    if observed <= {"integer", "number"}:
        return "number" if "number" in observed else "integer"
    return next(iter(observed)) if len(observed) == 1 else None


def _list_data_projection(
    value: list[Any], by_path: Mapping[str, Mapping[str, Any]]
) -> dict[str, Any] | None:
    scalar_type = _scalar_list_type(value)
    if scalar_type is not None:
        if _classified("data.list[]", by_path) != "non_sensitive":
            return None
        return {"data_scalar_list_types": {"list": scalar_type}}
    safe, hidden, nested, nested_omitted = _container_contract(
        value, "data.list", by_path
    )
    if not safe:
        return None
    result: dict[str, Any] = {"item_keys": safe}
    if hidden:
        result["known_omitted_item_keys"] = hidden
    opaque = [name for name in safe if name in _OPAQUE_OBJECT_ITEM_FIELDS]
    if opaque:
        result["opaque_json_item_keys"] = opaque
    elif nested:
        result["nested_item_keys"] = nested
        if nested_omitted:
            result["known_omitted_nested_item_keys"] = nested_omitted
    return result


def _container_projection_keys(
    key: str, value: Any, by_path: Mapping[str, Mapping[str, Any]]
) -> tuple[list[str], list[str], dict[str, list[str]], dict[str, list[str]]]:
    return _container_contract(value, f"data.{key}", by_path)


def _list_projection(data: list[Any], by_path: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    safe, hidden, nested, nested_omitted = _container_contract(data, "data", by_path)
    projection: dict[str, Any] = {
        "data_keys": [], "required_data_keys": [], "item_keys": safe,
        "dynamic_item_fields": [], "data_shape": "list",
    }
    if hidden:
        projection["known_omitted_item_keys"] = hidden
    if nested:
        projection["nested_item_keys"] = nested
    if nested_omitted:
        projection["known_omitted_nested_item_keys"] = nested_omitted
    return projection


def _apply_list_data_projection(
    projection: dict[str, Any],
    value: list[Any],
    by_path: Mapping[str, Mapping[str, Any]],
) -> bool:
    result = _list_data_projection(value, by_path)
    if result is None:
        return False
    projection["required_data_keys"].append("list")
    projection.update(result)
    return True


def _page_info_is_safe(
    value: Mapping[str, Any], by_path: Mapping[str, Mapping[str, Any]]
) -> bool:
    child_keys = {safe_schema_key(name) for name in value}
    return bool(child_keys) and all(
        _classified(f"data.page_info.{name}", by_path) == "non_sensitive"
        for name in child_keys
    )


def _merge_nested_projection(
    projection: dict[str, Any],
    nested: Mapping[str, Sequence[str]],
    nested_omitted: Mapping[str, Sequence[str]],
) -> None:
    if nested:
        allowed = projection.setdefault("nested_item_keys", {})
        for name, fields in nested.items():
            merge_allowed_fields(allowed, name, fields)
    if nested_omitted:
        omitted = projection.setdefault("known_omitted_nested_item_keys", {})
        for name, fields in nested_omitted.items():
            merge_omitted_fields(omitted, name, fields)


def _apply_container_projection(
    projection: dict[str, Any],
    key: str,
    value: Any,
    by_path: Mapping[str, Mapping[str, Any]],
) -> bool:
    safe, hidden, nested, nested_omitted = _container_projection_keys(
        key, value, by_path
    )
    if not safe or key == "total" and hidden:
        return False
    projection.setdefault("data_item_keys", {})[key] = safe
    if hidden:
        projection.setdefault("known_omitted_data_item_keys", {})[key] = hidden
    _merge_nested_projection(projection, nested, nested_omitted)
    return True


def _project_mapping_value(
    projection: dict[str, Any],
    key: str,
    value: Any,
    by_path: Mapping[str, Mapping[str, Any]],
) -> bool:
    if key == "list" and isinstance(value, list):
        return _apply_list_data_projection(projection, value, by_path)
    if key == "page_info" and isinstance(value, Mapping):
        return _page_info_is_safe(value, by_path)
    if isinstance(value, (list, Mapping)):
        return _apply_container_projection(projection, key, value, by_path)
    return _classified(f"data.{key}", by_path) == "non_sensitive"


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
        if _project_mapping_value(projection, key, value, by_path):
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

    nested = projection.get("nested_item_keys", {})
    if normalized.startswith("data[]"):
        return first_name in item_keys and _nested_projection_exposes(
            first_name, segments[1:], nested
        )
    if first == "list[]":
        return _list_projection_exposes(
            segments, data_keys=data_keys, item_keys=item_keys, projection=projection
        )
    if len(segments) == 1:
        return first_name in data_keys
    if first_name not in data_keys:
        return False
    allowed = projection.get("data_item_keys", {})
    if not isinstance(allowed, Mapping):
        return False
    item_name = segments[1].removesuffix("[]")
    if item_name not in {str(value) for value in allowed.get(first_name, ())}:
        return False
    return _nested_projection_exposes(item_name, segments[2:], nested)


def _list_projection_exposes(
    segments: Sequence[str],
    *,
    data_keys: set[str],
    item_keys: set[str],
    projection: Mapping[str, Any],
) -> bool:
    if len(segments) == 1:
        scalar_lists = projection.get("data_scalar_list_types", {})
        return (
            "list" in data_keys
            and isinstance(scalar_lists, Mapping)
            and "list" in scalar_lists
        )
    if "list" not in data_keys:
        return False
    item_name = segments[1].removesuffix("[]")
    if item_name not in item_keys:
        return False
    return _nested_projection_exposes(
        item_name, segments[2:], projection.get("nested_item_keys", {})
    )


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
