"""Shared types and predicates for Gravity Insight field validation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Mapping, Sequence

from .errors import InputValidationError
from .models import OperationSpec


MetadataLoader = Callable[[str, Mapping[str, Any]], Mapping[str, Any]]

ANALYSIS_QUERY_ID_RE = re.compile(r"^\d{13}[A-Za-z0-9]{19}$")
ANALYSIS_CONTROL_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
ANALYSIS_FORMULA_RE = re.compile(r"^[xX0-9+*/().\s-]{1,256}$")
ANALYSIS_TARGET_METHODS = frozenset(
    {
        "PresetAllCount",
        "PresetUserCount",
        "Count",
        "DistinctCount",
        "SumCount",
        "MaxCount",
        "MinCount",
        "ValueAvg",
        "UserAvg",
        "ListDistinctCount",
        "ListSetDistinctCount",
        "ListElementDistinctCount",
    }
)
ANALYSIS_CONDITION_OPERATORS = frozenset(
    {
        "EQUALS",
        "NOT_EQUALS",
        "IN",
        "NOT_IN",
        "CONTAINS",
        "NOT_CONTAINS",
        "GT",
        "GTE",
        "LT",
        "LTE",
        "GREATER",
        "GREATER_EQUALS",
        "LESS",
        "LESS_EQUALS",
        "PATTERN",
        "NOT_PATTERN",
        "RANGE_IN",
        "WITHOUT_VAL",
        "WITH_VAL",
        "RELATIVE_DAY",
        "RELATIVE_HOUR",
        "RELATIVE_MINUTE",
        "RELATIVE_WEEK",
        "RELATIVE_MONTH",
        "INDEX_POSITION",
    }
)
ANALYSIS_EVENT_TYPES = frozenset({"event", "default_event", "default"})
ANALYSIS_USER_TYPES = frozenset(
    {"user", "user_property", "default_user", "user_re_attribute"}
)
ANALYSIS_TIME_GROUPS = frozenset(
    {"minute", "hour", "day", "week", "month", "total"}
)
ANALYSIS_PROPERTY_GROUP_OPERATORS = frozenset(
    {
        "minute",
        "hour",
        "day",
        "week",
        "month",
        "quarter",
        "year",
        "default",
        "dispersed",
        "custom",
        "LIST_ELEMENT",
        "LIST",
        "LIST_SET",
    }
)
ANALYSIS_FIXED_EVENT_FIELDS = frozenset(
    {
        "PresetAllCount",
        "PresetUserCount",
        "$EventCreateTime",
        "create_time",
        "$PresetAdPlatform",
    }
)
ANALYSIS_FIXED_USER_FIELDS = frozenset(
    {"PresetUserCount", "create_time", "create_date_list", "ad_platform_list"}
)
ANALYSIS_USER_REATTRIBUTE_FIELDS = frozenset(
    {
        "turbo_promoted_object_id",
        "create_time",
        "channel",
        "click_company",
        "gid",
        "advertiser_id",
        "aid",
        "cid",
        "csite",
    }
)


@dataclass(frozen=True)
class MetadataView:
    operation_id: str
    status: str
    rows: tuple[Mapping[str, Any], ...]


@dataclass
class AnalysisReferences:
    events: set[str]
    event_fields: set[str]
    user_fields: set[str]
    user_target_fields: set[str]
    segment_fields: set[tuple[str, str, str]]
    event_dimension_tables: set[tuple[str, str]]
    user_dimension_tables: set[tuple[str, str]]


def new_analysis_references() -> AnalysisReferences:
    return AnalysisReferences(set(), set(), set(), set(), set(), set(), set())


def require_exact_mapping(value: Any, allowed: set[str], label: str) -> None:
    if not isinstance(value, Mapping) or set(value) - allowed:
        raise InputValidationError(
            f"{label} contains unregistered keys; request was not sent"
        )


def validate_optional_label(value: Any, label: str) -> None:
    if value is not None and (
        not isinstance(value, str) or len(value) > 256 or "\x00" in value
    ):
        raise InputValidationError(f"{label} is invalid; request was not sent")


def analysis_scalar(value: Any) -> bool:
    return value is None or isinstance(value, (str, int, float, bool)) and not (
        isinstance(value, str) and len(value) > 4_096
    )


def validate_scalar_list(value: Any, label: str) -> None:
    if (
        not isinstance(value, (list, tuple))
        or len(value) > 200
        or any(not analysis_scalar(item) for item in value)
    ):
        raise InputValidationError(f"{label} must be a scalar list; request was not sent")


def parse_iso_calendar_date(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise InputValidationError(f"analysis {label} is invalid; request was not sent")
    try:
        return datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise InputValidationError(
            f"analysis {label} is invalid; request was not sent"
        ) from exc


def parse_analysis_datetime(value: Any) -> datetime:
    if not isinstance(value, str) or not value or len(value) > 32:
        raise InputValidationError(
            "analysis date value is invalid; request was not sent"
        )
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise InputValidationError(
            "analysis date value is invalid; request was not sent"
        ) from exc


def dynamic_values(
    operation: OperationSpec, field_name: str, value: Any
) -> tuple[str, ...]:
    field = operation.fields.get(field_name)
    if field is None:
        raise InputValidationError("dynamic field contract references an unknown input")
    if field.enum:
        if isinstance(value, str):
            return (value,) if value else ()
        if isinstance(value, (list, tuple)) and all(isinstance(item, str) for item in value):
            return tuple(value)
        raise InputValidationError("enumerated dynamic field has an invalid value")
    if value in (None, "", [], ()):
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, (list, tuple)) and all(
        isinstance(item, str) and bool(item) for item in value
    ):
        return tuple(value)
    raise InputValidationError(
        f"{field_name} must contain only non-empty string field names"
    )


def control_fields(operation: OperationSpec, inputs: Mapping[str, Any]) -> set[str]:
    allowed = set(operation.response_projection.item_keys)
    if operation.domain == "promotion":
        allowed.update({"put_status", "grant_type", "account_type"})
    for input_name in operation.response_projection.dynamic_item_fields:
        value = inputs.get(input_name)
        if isinstance(value, str) and value:
            allowed.add(value)
        elif isinstance(value, (list, tuple)):
            allowed.update(item for item in value if isinstance(item, str) and item)
    return allowed


def promotion_metadata_inputs(
    operation: OperationSpec, inputs: Mapping[str, Any]
) -> dict[str, Any]:
    if not operation.platform:
        raise InputValidationError(
            "promotion field metadata has no platform context; request was not sent"
        )
    metadata_inputs: dict[str, Any] = {
        "media_type": {
            "apple": "asa",
            "tencent": "tencentV3",
        }.get(operation.platform, operation.platform)
    }
    if operation.platform == "tencent":
        time_line = inputs.get("time_line", "behavior")
        if time_line not in {"behavior", "active"}:
            raise InputValidationError(
                "Tencent request timeline has no verified metric metadata profile; request was not sent"
            )
        metadata_inputs["metric_type"] = time_line
    return metadata_inputs


def order_field(value: Any) -> str | None:
    if isinstance(value, str) and value:
        normalized = value.strip()
        if not normalized:
            return None
        if normalized[0] in "+-":
            return normalized[1:] or None
        parts = normalized.split()
        if len(parts) == 1:
            return parts[0]
        if len(parts) == 2 and parts[1].casefold() in {"asc", "desc"}:
            return parts[0]
        return None
    if not isinstance(value, Mapping):
        return None
    if set(value) - {"field", "name", "order", "direction", "sort"}:
        return None
    field_name = value.get("field", value.get("name"))
    direction = value.get("order", value.get("direction", value.get("sort")))
    if not isinstance(field_name, str) or not field_name:
        return None
    if direction is not None and direction not in {
        "asc",
        "ASC",
        "desc",
        "DESC",
        1,
        -1,
    }:
        return None
    return field_name


def is_sensitive_control_key(value: str) -> bool:
    normalized = value.casefold()
    if normalized in {
        "authorization",
        "cookie",
        "email",
        "email_address",
        "password",
        "phone",
        "mobile",
        "token",
        "user_name",
    }:
        return True
    return normalized.endswith(
        ("_token", "_password", "_email", "_phone", "_mobile", "_url")
    ) or normalized.startswith(
        ("operator_", "creator_", "user_", "department_", "dept_", "designer_")
    )


_DIRECT_PERSONAL_RESPONSE_FIELDS = frozenset(
    {
        "avatar",
        "email",
        "emailaddress",
        "phone",
        "phonenumber",
        "mobile",
        "mobilephone",
        "idcard",
        "identitycard",
        "realname",
        "username",
        "operatorname",
        "creatorname",
        "openid",
        "wxopenid",
        "wechatopenid",
        "unionid",
        "idfa",
        "idfv",
        "imei",
        "oaid",
        "androidid",
        "caid",
        "caid1",
        "caid2",
        "ip",
        "ipaddress",
        "birthdate",
        "birthday",
        "homeaddress",
        "preciselocation",
    }
)


def is_direct_personal_response_field(value: str) -> bool:
    normalized = value.casefold().strip().lstrip("$").replace("-", "_")
    compact = re.sub(r"[^a-z0-9]", "", normalized)
    return compact in _DIRECT_PERSONAL_RESPONSE_FIELDS or normalized.endswith(
        ("_email", "_phone", "_mobile", "_avatar")
    )


def is_sensitive_analysis_field(value: str) -> bool:
    normalized = value.casefold().strip().lstrip("$").replace("-", "_")
    compact = re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", normalized)
    if compact in {
        "authorization",
        "cookie",
        "password",
        "secret",
        "sessioncookie",
        "sessiontoken",
        "token",
        "访问令牌",
        "刷新令牌",
        "密码",
        "会话令牌",
    }:
        return True
    return normalized.endswith(
        (
            "_authorization",
            "_cookie",
            "_password",
            "_secret",
            "_session_token",
            "_token",
        )
    )


def reject_sensitive_analysis_field(value: str) -> None:
    if is_sensitive_analysis_field(value):
        raise InputValidationError(
            "analysis credential/session fields are blocked; request was not sent"
        )


def reject_sensitive_metadata_fields(
    rows: Sequence[Mapping[str, Any]], requested: set[str]
) -> None:
    by_name: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        name = row.get("name")
        if isinstance(name, str):
            by_name.setdefault(name, []).append(row)
    for field_name in requested:
        for row in by_name.get(field_name, ()):
            for key in ("name", "cname", "remark"):
                value = row.get(key)
                if isinstance(value, str) and is_sensitive_analysis_field(value):
                    raise InputValidationError(
                        "analysis metadata marks a field as user-identifying; "
                        "business request was not sent"
                    )


def require_dimension_tables(
    rows: Sequence[Mapping[str, Any]],
    requested: set[tuple[str, str]],
    label: str,
) -> None:
    if not requested:
        return
    available = {
        (str(row.get("name")), str(row.get("dim_using_table_name")))
        for row in rows
        if isinstance(row.get("name"), str)
        and row.get("name")
        and isinstance(row.get("dim_using_table_name"), str)
        and row.get("dim_using_table_name")
    }
    if not requested <= available:
        raise InputValidationError(
            f"analysis {label} dimension table is absent from live metadata; "
            "request was not sent"
        )


def reject_unhandled(
    requested_by_field: Mapping[str, Sequence[str]], allowed_fields: set[str]
) -> None:
    if set(requested_by_field) - allowed_fields:
        raise InputValidationError(
            "dynamic response fields have no registered metadata validator; request was not sent"
        )
