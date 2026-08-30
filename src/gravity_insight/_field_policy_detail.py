"""Detail-query validators for the Analysis DSL."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .actionable_error_values import actual_value, allowed_values, live_metadata_miss
from ._field_policy_metadata import (
    load_event_property_rows,
    load_view,
    names,
    wire_dimension_tables,
    wire_property_names,
)
from ._field_policy_operations import (
    ANALYSIS_EVENT,
    ANALYSIS_EVENT_PROPERTY,
    ANALYSIS_MONETIZATION_DETAIL,
    ANALYSIS_ORDER_DETAIL,
    ANALYSIS_SEGMENT,
    ANALYSIS_SEGMENT_HISTORY,
    ANALYSIS_SEGMENT_USER_DETAIL,
    ANALYSIS_USER_EVENT,
    ANALYSIS_USER_PROPERTY,
)
from ._field_policy_shared import (
    ANALYSIS_CONDITION_OPERATORS,
    ANALYSIS_EVENT_TYPES,
    ANALYSIS_USER_TYPES,
    MetadataLoader,
    MetadataView,
    parse_iso_calendar_date,
    require_exact_mapping,
    validate_optional_label,
    validate_scalar_list,
)
from ._field_policy_segment_members import validate_segment_member_fields
from ._order_read import STATIC_ORDER_FIELD_PROFILES
from .monetization_detail import SAFE_ROW_FIELDS, validate_monetization_operation_request
from .errors import InputValidationError
from .models import OperationSpec


_STATIC_DETAIL_FIELD_PROFILES = {
    ANALYSIS_MONETIZATION_DETAIL: (frozenset(SAFE_ROW_FIELDS),),
    ANALYSIS_ORDER_DETAIL: STATIC_ORDER_FIELD_PROFILES,
}
_DETAIL_TYPES = ANALYSIS_EVENT_TYPES | ANALYSIS_USER_TYPES | frozenset({"order", "cash", "default_order", "user_segment"})
_SEGMENT_TYPES = frozenset({None, "", "LATEST", "DYNAMIC_MATCHING", "FIXED_VERSION"})
_ORDER_DIRECTIONS = frozenset({0, 1, -1, "asc", "ASC", "desc", "DESC"})
_SPEC_SCHEMA_ACTION = "gravity analysis query --kind event --spec-schema"


@dataclass(frozen=True)
class _DetailMetadata:
    user_properties: MetadataView
    event_properties: MetadataView
    segment_ids: set[str]
    allowed_fields: set[str]
    dimension_tables: Mapping[str, str]


def validate_analysis_detail(
    operation: OperationSpec,
    inputs: Mapping[str, Any],
    metadata_loader: MetadataLoader,
) -> None:
    app_id = _validate_app_id(inputs.get("app_id"))
    if operation.operation_id == ANALYSIS_USER_EVENT:
        _validate_user_event_contract(inputs)
    if operation.operation_id == ANALYSIS_MONETIZATION_DETAIL:
        validate_monetization_operation_request(operation, inputs)
    if operation.operation_id == ANALYSIS_SEGMENT_USER_DETAIL:
        validate_segment_member_fields(operation, inputs, app_id, metadata_loader)
        return
    if _static_detail_product_request(operation, inputs):
        parse_iso_calendar_date(inputs.get("date"), "date")
        _validate_selected_fields(
            inputs.get("fields", ()), set(operation.response_projection.item_keys)
        )
        _validate_detail_logic(inputs)
        return
    metadata = _load_detail_metadata(operation, app_id, metadata_loader)
    selected_fields = set(metadata.allowed_fields)
    if operation.operation_id == ANALYSIS_USER_EVENT:
        selected_fields.update(
            str(row.get("cname"))
            for row in (*metadata.user_properties.rows, *metadata.event_properties.rows)
            if isinstance(row.get("cname"), str) and row.get("cname")
        )
    _validate_selected_fields(inputs.get("fields", ()), selected_fields)
    _validate_detail_condition_sets(inputs, metadata, metadata_loader, app_id)
    _validate_detail_logic(inputs)
    if "order_by_list" in inputs:
        validate_detail_order(inputs.get("order_by_list"), metadata.allowed_fields)
    if operation.operation_id == ANALYSIS_USER_EVENT:
        _validate_user_event_items(
            inputs, app_id, metadata, metadata_loader
        )


def _static_detail_product_request(
    operation: OperationSpec, inputs: Mapping[str, Any]
) -> bool:
    """Skip metadata only for an exact governed product field profile."""

    fields = inputs.get("fields")
    profiles = _STATIC_DETAIL_FIELD_PROFILES.get(operation.operation_id, ())
    return bool(
        isinstance(fields, (list, tuple))
        and all(isinstance(field, str) for field in fields)
        and len(fields) == len(set(fields))
        and frozenset(fields) in profiles
        and inputs.get("date") not in (None, "")
        and type(inputs.get("page", 1)) is int
        and inputs.get("page", 1) >= 1
        and inputs.get("page_size", 20) == 100
        and all(
            inputs.get(name) in (None, (), [])
            for name in (
                "global_conditions",
                "local_conditions",
                "order_conditions",
                "order_by_list",
            )
        )
        and inputs.get("user_cond_logic", "AND") == "AND"
        and inputs.get("order_cond_logic", "AND") == "AND"
    )


def _validate_app_id(value: Any) -> str:
    if not isinstance(value, str) or not value or len(value) > 64:
        raise InputValidationError(
            f"actual value: {actual_value(value)}; allowed value: a non-empty app_id "
            "string of at most 64 characters",
            field="app_id",
        )
    return value


def _validate_user_event_contract(inputs: Mapping[str, Any]) -> None:
    has_date = inputs.get("date") not in (None, "")
    has_date_list = inputs.get("date_list") not in (None, (), [])
    if has_date == has_date_list:
        raise InputValidationError(
            f"actual value: {actual_value({'date_present': has_date, 'date_list_present': has_date_list})}; "
            "allowed shape: provide exactly one of date or date_list",
            field="date/date_list",
        )
    page = inputs.get("page", 1)
    page_size = inputs.get("page_size", 20)
    if (
        not isinstance(page, int)
        or isinstance(page, bool)
        or page < 1
        or not isinstance(page_size, int)
        or isinstance(page_size, bool)
        or not 1 <= page_size <= 200
    ):
        raise InputValidationError(
            f"actual value: {actual_value({'page': page, 'page_size': page_size})}; "
            "allowed range: page is an integer >= 1 and page_size is 1 through 200",
            field="page/page_size",
        )


def _load_detail_metadata(
    operation: OperationSpec,
    app_id: str,
    loader: MetadataLoader,
) -> _DetailMetadata:
    metadata_inputs = {"app_id": app_id, "page": 1, "page_size": 2_000}
    user_properties = load_view(ANALYSIS_USER_PROPERTY, metadata_inputs, loader)
    event_properties = load_view(ANALYSIS_EVENT_PROPERTY, metadata_inputs, loader)
    segments = load_view(
        ANALYSIS_SEGMENT,
        {"app_id": app_id, "page": 1, "page_size": 100},
        loader,
    )
    segment_ids = names(segments.rows, keys=("segment_id", "id"))
    user_fields = wire_property_names(user_properties.rows, "user")
    event_fields = wire_property_names(event_properties.rows, "event")
    dimension_tables = {
        **wire_dimension_tables(user_properties.rows, "user"),
        **wire_dimension_tables(event_properties.rows, "event"),
    }
    allowed_fields = (
        set(operation.response_projection.item_keys)
        | user_fields
        | event_fields
        | segment_ids
        | {
            "ClientID",
            "TraceID",
            "Name",
            "CreateTime",
            "ModifyTime",
            "LatestLoginDay",
            "WXOpenID",
            "user_id",
            "event_user_id",
            "device_id",
            "create_time",
            "create_date_list",
            "client_id_list",
            "ad_platform_list",
            "channel_list",
            "version_list",
            "turbo_promoted_object_id_list",
        }
    )
    return _DetailMetadata(
        user_properties,
        event_properties,
        segment_ids,
        allowed_fields,
        dimension_tables,
    )


def _validate_selected_fields(value: Any, selected_fields: set[str]) -> None:
    if value in (None, (), []):
        return
    if not isinstance(value, (list, tuple)) or any(
        not isinstance(item, str) or item not in selected_fields for item in value
    ):
        requested = value if isinstance(value, (list, tuple)) else [value]
        missing = [item for item in requested if not isinstance(item, str) or item not in selected_fields]
        raise InputValidationError(
            live_metadata_miss(actual_value(missing), noun="fields"),
            field="fields",
            next_action="Run `gravity metadata properties \"\"` and retry with listed fields.",
        )


def _validate_detail_condition_sets(
    inputs: Mapping[str, Any],
    metadata: _DetailMetadata,
    loader: MetadataLoader,
    app_id: str,
) -> None:
    for name in (
        "global_conditions",
        "order_conditions",
        "local_conditions",
        "postback_conditions",
    ):
        if name in inputs:
            validate_detail_conditions(
                inputs.get(name),
                metadata.allowed_fields,
                name,
                segment_ids=metadata.segment_ids,
                dimension_tables=metadata.dimension_tables,
                metadata_loader=loader,
                app_id=app_id,
            )


def _validate_detail_logic(inputs: Mapping[str, Any]) -> None:
    for name in ("user_cond_logic", "order_cond_logic", "postback_cond_logic"):
        if name in inputs and inputs.get(name) not in {"AND", "OR"}:
            raise InputValidationError(f"actual value: {actual_value(inputs.get(name))}; allowed values: \"AND\", \"OR\"", field=name)


def _validate_user_event_items(
    inputs: Mapping[str, Any],
    app_id: str,
    metadata: _DetailMetadata,
    loader: MetadataLoader,
) -> None:
    events = load_view(
        ANALYSIS_EVENT,
        {"app_id": app_id, "page": 1, "page_size": 2_000},
        loader,
    )
    allowed_events = names(events.rows, keys=("name",))
    event_list = inputs.get("event_list", ())
    if not isinstance(event_list, (list, tuple)) or any(
        not isinstance(item, str) or item not in allowed_events for item in event_list
    ):
        requested = event_list if isinstance(event_list, (list, tuple)) else [event_list]
        missing = [item for item in requested if not isinstance(item, str) or item not in allowed_events]
        raise InputValidationError(
            live_metadata_miss(actual_value(missing), noun="events"),
            field="event_list",
            next_action="Run `gravity metadata events \"\"` and retry with listed events.",
        )
    validate_detail_query_items(
        inputs.get("query_item_list", ()),
        allowed_events,
        metadata.allowed_fields,
        metadata.segment_ids,
        metadata.dimension_tables,
        app_id,
        loader,
    )


def validate_detail_conditions(
    value: Any,
    allowed_fields: set[str],
    label: str,
    *,
    segment_ids: set[str],
    dimension_tables: Mapping[str, str],
    metadata_loader: MetadataLoader,
    app_id: str,
) -> None:
    if not isinstance(value, (list, tuple)) or len(value) > 100:
        raise InputValidationError(
            f"actual value: {len(value) if isinstance(value, (list, tuple)) else actual_value(type(value).__name__)}; "
            "allowed value: an array with at most 100 conditions",
            field=label,
        )
    for item in value:
        _validate_detail_condition(
            item,
            allowed_fields,
            label,
            segment_ids,
            dimension_tables,
            metadata_loader,
            app_id,
        )


def _validate_detail_condition(
    item: Any,
    allowed_fields: set[str],
    label: str,
    segment_ids: set[str],
    dimension_tables: Mapping[str, str],
    loader: MetadataLoader,
    app_id: str,
) -> None:
    require_exact_mapping(
        item,
        {
            "operator",
            "field",
            "type",
            "value",
            "by_list_index",
            "list_index_val",
            "segment_type",
            "version_id",
            "dim_using_table_name",
        },
        f"analysis {label}",
    )
    operator = item.get("operator")
    if not isinstance(operator, str) or operator not in ANALYSIS_CONDITION_OPERATORS:
        raise InputValidationError(f"actual value: {actual_value(operator)}; allowed operators: {allowed_values(ANALYSIS_CONDITION_OPERATORS, discovery_action=_SPEC_SCHEMA_ACTION)}", field=f"{label}[].operator")
    field = item.get("field")
    if not isinstance(field, str) or field not in allowed_fields:
        raise InputValidationError(
            live_metadata_miss(actual_value(field), noun="fields"),
            field=f"{label}[].field",
            next_action="Run `gravity metadata properties \"\"` and retry with a listed field.",
        )
    field_type = item.get("type")
    if not isinstance(field_type, str) or field_type not in _DETAIL_TYPES:
        raise InputValidationError(f"actual value: {actual_value(field_type)}; allowed values: {allowed_values(_DETAIL_TYPES)}", field=f"{label}[].type")
    validate_scalar_list(item.get("value", ()), f"analysis {label} value")
    _validate_detail_list_controls(item, label)
    _validate_detail_segment(item, field, field_type, label, segment_ids, loader, app_id)
    _validate_detail_dimension(item, field, label, dimension_tables)


def _validate_detail_list_controls(item: Mapping[str, Any], label: str) -> None:
    by_list_index = item.get("by_list_index")
    if by_list_index is not None and not isinstance(by_list_index, bool):
        raise InputValidationError(f"actual value: {actual_value(by_list_index)}; allowed values: null, true, false", field=f"{label}[].by_list_index")
    list_index = item.get("list_index_val")
    if list_index is not None and (
        not isinstance(list_index, int)
        or isinstance(list_index, bool)
        or list_index == 0
        or not -10_000 <= list_index <= 10_000
    ):
        raise InputValidationError(f"actual value: {actual_value(list_index)}; allowed range: a non-zero integer from -10000 through 10000", field=f"{label}[].list_index_val")


def _validate_detail_segment(
    item: Mapping[str, Any],
    field: str,
    field_type: str,
    label: str,
    segment_ids: set[str],
    loader: MetadataLoader,
    app_id: str,
) -> None:
    segment_type = item.get("segment_type")
    version_id = item.get("version_id")
    if not isinstance(segment_type, (str, type(None))) or segment_type not in _SEGMENT_TYPES:
        raise InputValidationError(f"actual value: {actual_value(segment_type)}; allowed values: {allowed_values(_SEGMENT_TYPES)}", field=f"{label}[].segment_type")
    if (field_type == "user_segment" or segment_type not in {None, ""}) and field not in segment_ids:
        segment_discovery = f"gravity analysis metadata --app-id {app_id}"
        raise InputValidationError(
            live_metadata_miss(actual_value(field), noun="segment ids"),
            field=f"{label}[].field",
            next_action=f"Run `{segment_discovery}` and retry with a listed segment id.",
        )
    if segment_type == "FIXED_VERSION":
        _validate_detail_segment_version(field, version_id, label, loader)
    elif version_id is not None and version_id != "":
        raise InputValidationError(f"actual value: {actual_value(version_id)}; allowed value: null or \"\" unless segment_type is FIXED_VERSION", field=f"{label}[].version_id")


def _validate_detail_segment_version(
    field: str, version_id: Any, label: str, loader: MetadataLoader
) -> None:
    if not isinstance(version_id, (str, int)) or isinstance(version_id, bool):
        raise InputValidationError(f"actual value: {actual_value(version_id)}; allowed value: a string or integer version id", field=f"{label}[].version_id")
    history = load_view(
        ANALYSIS_SEGMENT_HISTORY,
        {"segment_id": str(field), "page": 1, "page_size": 100},
        loader,
    )
    available = names(history.rows, keys=("version_id", "id"))
    if str(version_id) not in available:
        version_discovery = f"gravity run {ANALYSIS_SEGMENT_HISTORY} --input {actual_value({'segment_id': field, 'page': 1, 'page_size': 100})}"
        raise InputValidationError(
            live_metadata_miss(actual_value(version_id), noun="versions"),
            field=f"{label}[].version_id",
            next_action=f"Run `{version_discovery}` and retry with a listed version id.",
        )


def _validate_detail_dimension(
    item: Mapping[str, Any],
    field: str,
    label: str,
    dimension_tables: Mapping[str, str],
) -> None:
    table = item.get("dim_using_table_name")
    if table not in {None, ""} and (
        not isinstance(table, str)
        or len(table) > 256
        or dimension_tables.get(field) != table
    ):
        raise InputValidationError(
            live_metadata_miss(actual_value(table), noun="dimension tables"),
            field=f"{label}[].dim_using_table_name",
            next_action="Run `gravity metadata properties \"\"` and use the field's listed dimension table.",
        )


def validate_detail_order(value: Any, allowed_fields: set[str]) -> None:
    if not isinstance(value, (list, tuple)) or len(value) > 20:
        raise InputValidationError(
            f"actual value: {len(value) if isinstance(value, (list, tuple)) else actual_value(type(value).__name__)}; allowed value: an array with at most "
            "20 order items",
            field="order_by_list",
        )
    for item in value:
        require_exact_mapping(item, {"field", "sort", "data_type"}, "analysis order item")
        if item.get("field") not in allowed_fields:
            raise InputValidationError(
                live_metadata_miss(actual_value(item.get("field")), noun="fields"),
                field="order_by_list[].field",
                next_action="Run `gravity metadata properties \"\"` and retry with a listed field.",
            )
        _validate_detail_order_controls(item)


def _validate_detail_order_controls(item: Mapping[str, Any]) -> None:
    sort = item.get("sort")
    if not isinstance(sort, (str, int)) or isinstance(sort, bool) or sort not in _ORDER_DIRECTIONS:
        raise InputValidationError(f"actual value: {actual_value(sort)}; allowed values: {allowed_values(_ORDER_DIRECTIONS)}", field="order_by_list[].sort")
    data_type = item.get("data_type")
    if data_type is not None and (
        not isinstance(data_type, str) or not data_type or len(data_type) > 64
    ):
        raise InputValidationError(f"actual value: {actual_value(data_type)}; allowed value: null or a non-empty data type string of at most 64 characters", field="order_by_list[].data_type")


def validate_detail_query_items(
    value: Any,
    allowed_events: set[str],
    allowed_fields: set[str],
    segment_ids: set[str],
    dimension_tables: Mapping[str, str],
    app_id: str,
    metadata_loader: MetadataLoader,
) -> None:
    if not isinstance(value, (list, tuple)) or len(value) > 100:
        raise InputValidationError(
            f"actual value: {len(value) if isinstance(value, (list, tuple)) else actual_value(type(value).__name__)}; "
            "allowed value: an array with at most 100 query items",
            field="query_item_list",
        )
    for item in value:
        _validate_detail_query_item(
            item,
            allowed_events,
            allowed_fields,
            segment_ids,
            dimension_tables,
            app_id,
            metadata_loader,
        )


def _validate_detail_query_item(
    item: Any,
    allowed_events: set[str],
    allowed_fields: set[str],
    segment_ids: set[str],
    dimension_tables: Mapping[str, str],
    app_id: str,
    loader: MetadataLoader,
) -> None:
    require_exact_mapping(
        item,
        {"event_name", "event_label", "conditions", "cond_logic"},
        "analysis detail query item",
    )
    event_name = item.get("event_name")
    if event_name not in allowed_events:
        raise InputValidationError(
            live_metadata_miss(actual_value(event_name), noun="events"),
            field="query_item_list[].event_name",
            next_action="Run `gravity metadata events \"\"` and retry with a listed event.",
        )
    validate_optional_label(item.get("event_label"), "event_label")
    cond_logic = item.get("cond_logic", "AND")
    if cond_logic not in {"AND", "OR"}:
        raise InputValidationError(f"actual value: {actual_value(cond_logic)}; allowed values: \"AND\", \"OR\"", field="query_item_list[].cond_logic")
    event_rows = load_event_property_rows((str(event_name),), app_id, loader)
    validate_detail_conditions(
        item.get("conditions", ()),
        allowed_fields | wire_property_names(event_rows, "event"),
        "query item conditions",
        segment_ids=segment_ids,
        dimension_tables={
            **dimension_tables,
            **wire_dimension_tables(event_rows, "event"),
        },
        metadata_loader=loader,
        app_id=app_id,
    )
