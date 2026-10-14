"""Small, deterministic codecs for read routes with private wire filters."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .actionable_error_values import actual_value
from .errors import InputValidationError, ManifestError, PolicyViolation


_RUNTIME_BINDINGS_PATH = (
    Path(__file__).resolve().parent / "contracts" / "runtime-operation-bindings.json"
)


def _load_request_builder_names(
    path: Path = _RUNTIME_BINDINGS_PATH,
) -> dict[str, str]:
    try:
        return dict(json.loads(path.read_text(encoding="utf-8"))["request_builders"])
    except (KeyError, OSError, TypeError, UnicodeError, json.JSONDecodeError) as exc:
        raise ManifestError("could not load runtime operation bindings") from exc


REQUEST_BUILDER_NAMES = _load_request_builder_names()


CatalogFilterRule = tuple[frozenset[int], str, int, int]
DATA_TYPES = frozenset(
    {"STRING", "BOOL", "INT", "FLOAT", "DATETIME", "DATE", "LIST", "DICT"}
)
APP_FILTER_RULES: Mapping[str, CatalogFilterRule] = {
    "app_id": (frozenset({1}), "integer", 1, 1),
    "id": (frozenset({1}), "integer", 1, 1),
    "os": (frozenset({6}), "integer", 1, 1_000),
    "industry_id": (frozenset({6}), "integer", 1, 1_000),
    "package_name": (frozenset({1}), "string", 1, 1),
    "name": (frozenset({8}), "string", 1, 1),
    "remark": (frozenset({8}), "string", 1, 1),
    "is_enabled": (frozenset({1}), "boolean", 1, 1),
    "create_time": (frozenset({7}), "string", 2, 2),
}
EVENT_FILTER_RULES: Mapping[str, CatalogFilterRule] = {
    "name": (frozenset({1}), "string", 1, 1),
    "accepted": (frozenset({1}), "boolean", 1, 1),
    "is_preset": (frozenset({1}), "boolean", 1, 1),
    "visible": (frozenset({1}), "boolean", 1, 1),
    "uploaded": (frozenset({1}), "boolean", 1, 1),
    "create_time": (frozenset({7}), "string", 2, 2),
    "modify_time": (frozenset({7}), "string", 2, 2),
    "like_name_cname": (frozenset({9}), "string", 1, 1),
}
PROPERTY_FILTER_RULES: Mapping[str, CatalogFilterRule] = {
    "name": (frozenset({1}), "string", 1, 1),
    "data_type": (frozenset({6}), "data_type", 1, 1_000),
    "prop_type": (frozenset({1}), "integer", 1, 1),
    "is_common": (frozenset({1}), "boolean", 1, 1),
    "is_preset": (frozenset({1}), "boolean", 1, 1),
    "uploaded": (frozenset({1}), "boolean", 1, 1),
    "visible": (frozenset({1}), "boolean", 1, 1),
    "create_time": (frozenset({7}), "string", 2, 2),
    "modify_time": (frozenset({7}), "string", 2, 2),
    "like_name_cname": (frozenset({9}), "string", 1, 1),
}


def catalog_filter_operator_profile(
    rules: Mapping[str, CatalogFilterRule],
) -> Mapping[str, frozenset[int]]:
    return {field: rule[0] for field, rule in rules.items()}


def resolve_request_builder(
    operation_id: str, fallback_namespace: Mapping[str, Any]
) -> Any:
    builder_name = REQUEST_BUILDER_NAMES.get(operation_id)
    if builder_name is None:
        return None
    builder = globals().get(builder_name) or fallback_namespace.get(builder_name)
    if not callable(builder):
        raise ManifestError("runtime operation binding names an unavailable builder")
    return builder


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


def app_catalog_request_parts(
    values: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    return _catalog_request_parts(values, APP_FILTER_RULES)


def analysis_event_catalog_request_parts(
    values: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    return _catalog_request_parts(
        values,
        EVENT_FILTER_RULES,
        default_visible=True,
        controls=("order_by_field", "order_by_op", "need_yesterday_count", "need_favourite"),
    )


def analysis_event_property_catalog_request_parts(
    values: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    return _catalog_request_parts(
        values,
        PROPERTY_FILTER_RULES,
        controls=("order_by_field", "order_by_op", "only_dim_prop"),
    )


def analysis_user_property_catalog_request_parts(
    values: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    return _catalog_request_parts(
        values,
        PROPERTY_FILTER_RULES,
        default_visible=True,
        controls=("order_by_field", "order_by_op", "only_dim_prop"),
    )


def _catalog_request_parts(
    values: Mapping[str, Any],
    rules: Mapping[str, CatalogFilterRule],
    *,
    default_visible: bool = False,
    controls: tuple[str, ...] = (),
) -> tuple[dict[str, Any], dict[str, Any]]:
    filters = _validated_catalog_filters(values.get("filters", ()), rules)
    if default_visible and not any(item["field"] == "visible" for item in filters):
        filters.insert(0, {"field": "visible", "operator": 1, "values": [True]})
    query = {
        name: values[name]
        for name in ("app_id", "page", "page_size")
        if name in values
    }
    query["filters"] = json.dumps(
        filters, ensure_ascii=False, separators=(",", ":")
    )
    for name in controls:
        value = values.get(name)
        if name == "only_dim_prop":
            if value:
                query[name] = 1
        elif name == "need_favourite":
            query[name] = bool(value)
        elif value is not None:
            query[name] = value
    return query, {}


def _validated_catalog_filters(
    raw_filters: Any,
    rules: Mapping[str, CatalogFilterRule],
) -> list[dict[str, Any]]:
    if not isinstance(raw_filters, (list, tuple)):
        raise _catalog_filter_error("filters must be an array", "filters")
    result: list[dict[str, Any]] = []
    for item in raw_filters:
        if not isinstance(item, Mapping) or set(item) != {"field", "operator", "values"}:
            raise _catalog_filter_error(
                "filter items must contain exactly field, operator, and values", "filters"
            )
        field = item.get("field")
        if not isinstance(field, str) or field not in rules:
            raise _catalog_filter_error(
                f"filter field is not allowed: {actual_value(field)}", "filters[].field"
            )
        operator = item.get("operator")
        operators, value_type, minimum, maximum = rules[field]
        if isinstance(operator, bool) or operator not in operators:
            raise _catalog_filter_error(
                f"operator is not allowed for {field}: {actual_value(operator)}",
                "filters[].operator",
            )
        item_values = item.get("values")
        if (
            not isinstance(item_values, (list, tuple))
            or not minimum <= len(item_values) <= maximum
        ):
            raise _catalog_filter_error(
                f"{field} filter requires between {minimum} and {maximum} values",
                "filters[].values",
            )
        normalized_values = list(item_values)
        if not all(_catalog_value_matches(value, value_type) for value in normalized_values):
            raise _catalog_filter_error(
                f"{field} filter values must be {value_type}", "filters[].values"
            )
        result.append(
            {"field": field, "operator": operator, "values": normalized_values}
        )
    return result


def _catalog_value_matches(value: Any, value_type: str) -> bool:
    if value_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if value_type == "boolean":
        return isinstance(value, bool)
    if value_type == "data_type":
        return isinstance(value, str) and value in DATA_TYPES
    return isinstance(value, str) and bool(value) and len(value) <= 256


def _catalog_filter_error(message: str, field: str) -> InputValidationError:
    return InputValidationError(
        message + "; request was not sent",
        field=field,
        next_action="Use the filter field/operator/value grammar from the operation schema.",
    )


def _json_filters(field: str, operator: str | int, value: Any) -> str:
    return json.dumps(
        [{"field": field, "operator": operator, "values": [value]}],
        ensure_ascii=False,
        separators=(",", ":"),
    )


__all__ = [
    "APP_FILTER_RULES",
    "EVENT_FILTER_RULES",
    "PROPERTY_FILTER_RULES",
    "REQUEST_BUILDER_NAMES",
    "analysis_account_user_request_parts",
    "analysis_event_catalog_request_parts",
    "analysis_event_property_catalog_request_parts",
    "analysis_segment_request_parts",
    "analysis_user_property_catalog_request_parts",
    "app_catalog_request_parts",
    "app_onelink_request_parts",
    "catalog_filter_operator_profile",
    "resolve_request_builder",
]
