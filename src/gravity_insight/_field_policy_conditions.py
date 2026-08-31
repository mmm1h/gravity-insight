"""Common Analysis DSL targets, conditions, grouping, and property controls."""

from __future__ import annotations

import re
from typing import Any, Mapping

from .actionable_error_values import actual_value, allowed_values
from ._field_policy_shared import (
    ANALYSIS_CONDITION_OPERATORS,
    ANALYSIS_EVENT_TYPES,
    ANALYSIS_PROPERTY_GROUP_OPERATORS,
    ANALYSIS_TARGET_METHODS,
    ANALYSIS_TIME_GROUPS,
    ANALYSIS_USER_REATTRIBUTE_FIELDS,
    ANALYSIS_USER_TYPES,
    AnalysisReferences,
    analysis_scalar,
    reject_sensitive_analysis_field,
    require_exact_mapping,
    validate_optional_label,
    validate_scalar_list,
)
from .errors import InputValidationError


_ANALYSIS_DATA_TYPES = frozenset({"STRING", "INT", "FLOAT", "BOOL", "DATE", "DATETIME", "LIST"})
_SEGMENT_TYPES = frozenset({None, "", "LATEST", "DYNAMIC_MATCHING", "FIXED_VERSION"})
_ORDER_DIRECTIONS = frozenset({0, 1, -1, "asc", "desc", "ASC", "DESC"})
_SPEC_SCHEMA_ACTION = "gravity analysis query --kind event --spec-schema"


def validate_analysis_target(
    value: Any,
    field_references: set[str],
    dimension_references: set[tuple[str, str]],
) -> None:
    require_exact_mapping(
        value,
        {"name", "field", "quantile_level", "dim_using_table_name"},
        "analysis target",
    )
    method = value.get("name")
    field = value.get("field")
    if not isinstance(method, str) or not (
        method in ANALYSIS_TARGET_METHODS
        or re.fullmatch(r"Quantile(?:_(?:[1-9]|[1-9][0-9]|100))?", method)
    ):
        raise InputValidationError(
            f"actual value: {actual_value(method)}; allowed methods: "
            f"{allowed_values(ANALYSIS_TARGET_METHODS)} or Quantile_1 through "
            "Quantile_100",
            field="target.name",
        )
    if not isinstance(field, str) or not field or len(field) > 256:
        raise InputValidationError(
            f"actual value: {actual_value(field)}; allowed value: a non-empty "
            "metadata field name of at most 256 characters",
            field="target.field",
            next_action="Run `gravity metadata properties \"\"` and retry with a listed field.",
        )
    if field == "$device_id" and method == "Count":
        raise InputValidationError(
            "actual value: field=$device_id, aggregation=Count; this built-in "
            "string identifier does not accept Count; request was not sent",
            field="target.name",
            next_action=(
                "Use `$device_id` with `DistinctCount` to count distinct devices, "
                "or use `PresetAllCount` for both field and aggregation to count "
                "event occurrences; do not retry the unchanged request."
            ),
        )
    reject_sensitive_analysis_field(field)
    field_references.add(field)
    _validate_target_quantile(value.get("quantile_level"))
    _add_dimension_reference(value.get("dim_using_table_name"), field, dimension_references)


def _validate_target_quantile(value: Any) -> None:
    if value is not None and (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not 0 < float(value) <= 100
    ):
        raise InputValidationError(f"actual value: {actual_value(value)}; allowed range: a number greater than 0 through 100", field="target.quantile_level")


def _add_dimension_reference(
    table: Any,
    field: str,
    references: set[tuple[str, str]],
) -> None:
    if table in {None, ""}:
        return
    if not isinstance(table, str) or len(table) > 256:
        raise InputValidationError(
            f"actual value: {actual_value(table)}; allowed value: a metadata dimension "
            "table name of at most 256 characters",
            field="target.dim_using_table_name",
            next_action="Run `gravity metadata properties \"\"` and retry with the field's listed dimension table.",
        )
    references.add((field, table))


def validate_property_query_item(
    value: Any, references: AnalysisReferences
) -> None:
    require_exact_mapping(
        value, {"target", "conditions", "custom_name"}, "property query item"
    )
    target = value.get("target")
    require_exact_mapping(
        target,
        {"name", "field", "cname", "data_type", "dim_using_table_name", "type"},
        "property query target",
    )
    method = target.get("name")
    field = target.get("field")
    if method not in ANALYSIS_TARGET_METHODS:
        raise InputValidationError(
            f"actual value: {actual_value(method)}; allowed methods: "
            f"{allowed_values(ANALYSIS_TARGET_METHODS)}",
            field="query_list[].target.name",
        )
    if not isinstance(field, str) or not field or len(field) > 256:
        raise InputValidationError(
            f"actual value: {actual_value(field)}; allowed value: a non-empty "
            "metadata property name of at most 256 characters",
            field="query_list[].target.field",
            next_action="Run `gravity metadata properties \"\"` and retry with a listed field.",
        )
    reject_sensitive_analysis_field(field)
    references.user_fields.add(field)
    _validate_property_target_metadata(target, field, references)
    validate_analysis_conditions(
        value.get("conditions", ()), references, "property query item conditions"
    )
    validate_optional_label(value.get("custom_name"), "custom_name")


def _validate_property_target_metadata(
    target: Mapping[str, Any], field: str, references: AnalysisReferences
) -> None:
    validate_optional_label(target.get("cname"), "property target cname")
    data_type = target.get("data_type")
    if data_type not in ({None} | _ANALYSIS_DATA_TYPES):
        raise InputValidationError(f"actual value: {actual_value(data_type)}; allowed values: null, {allowed_values(_ANALYSIS_DATA_TYPES)}", field="query_list[].target.data_type")
    field_type = target.get("type")
    if field_type not in ({None, ""} | ANALYSIS_USER_TYPES):
        raise InputValidationError(f"actual value: {actual_value(field_type)}; allowed values: null, \"\", {allowed_values(ANALYSIS_USER_TYPES)}", field="query_list[].target.type")
    table = target.get("dim_using_table_name")
    if table not in {None, ""}:
        if not isinstance(table, str) or len(table) > 256:
            raise InputValidationError(
                f"actual value: {actual_value(table)}; allowed value: a metadata "
                "dimension table name of at most 256 characters",
                field="query_list[].target.dim_using_table_name",
                next_action="Run `gravity metadata properties \"\"` and retry with the field's listed dimension table.",
            )
        references.user_dimension_tables.add((field, table))


def validate_analysis_conditions(
    value: Any,
    references: AnalysisReferences,
    label: str,
) -> None:
    if not isinstance(value, (list, tuple)) or len(value) > 100:
        raise InputValidationError(
            f"actual value: {actual_value(type(value).__name__) if not isinstance(value, (list, tuple)) else len(value)}; "
            f"{label} must be an array with at most 100 items; condition values are "
            "not echoed because errors may enter logs",
            field=label,
        )
    for item in value:
        _validate_analysis_condition(item, references, label)


def _validate_analysis_condition(
    item: Any, references: AnalysisReferences, label: str
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
        label,
    )
    if item.get("operator") not in ANALYSIS_CONDITION_OPERATORS:
        raise InputValidationError(
            f"actual value: {actual_value(item.get('operator'))}; allowed operators: "
            f"{allowed_values(ANALYSIS_CONDITION_OPERATORS, discovery_action=_SPEC_SCHEMA_ACTION)}",
            field="conditions[].operator",
        )
    field = item.get("field")
    if not isinstance(field, str) or not field or len(field) > 256:
        raise InputValidationError(
            f"actual value: {actual_value(field)}; allowed value: a non-empty metadata "
            "field name of at most 256 characters",
            field="conditions[].field",
            next_action="Run `gravity metadata properties \"\"` or `gravity metadata events \"\"` and retry with a listed field.",
        )
    is_segment = _add_condition_reference(item, field, references)
    validate_scalar_list(item.get("value", ()), "analysis condition value")
    _validate_list_controls(item)
    _add_condition_dimension(item, field, is_segment, references)


def _add_condition_reference(
    item: Mapping[str, Any], field: str, references: AnalysisReferences
) -> bool:
    field_type = item.get("type")
    segment_type = item.get("segment_type")
    version_id = item.get("version_id")
    if segment_type not in _SEGMENT_TYPES:
        raise InputValidationError(f"actual value: {actual_value(segment_type)}; allowed values: {allowed_values(_SEGMENT_TYPES)}", field="conditions[].segment_type")
    is_segment = field_type == "user_segment" or segment_type not in {None, ""}
    if is_segment:
        _add_segment_reference(field, field_type, segment_type, version_id, references)
    elif field_type in ANALYSIS_EVENT_TYPES:
        reject_sensitive_analysis_field(field)
        references.event_fields.add(field)
    elif field_type in ANALYSIS_USER_TYPES:
        reject_sensitive_analysis_field(field)
        references.user_fields.add(field)
    else:
        raise InputValidationError(f"actual value: {actual_value(field_type)}; allowed values: {allowed_values(ANALYSIS_EVENT_TYPES | ANALYSIS_USER_TYPES | frozenset({'user_segment'}))}", field="conditions[].type")
    return is_segment


def _add_segment_reference(
    field: str,
    field_type: Any,
    segment_type: Any,
    version_id: Any,
    references: AnalysisReferences,
) -> None:
    if field_type not in (ANALYSIS_USER_TYPES | frozenset({"user_segment"})):
        raise InputValidationError(f"actual value: {actual_value(field_type)}; allowed user field types: {allowed_values(ANALYSIS_USER_TYPES | frozenset({'user_segment'}))}", field="conditions[].type")
    effective_type = str(segment_type or "LATEST")
    if effective_type == "FIXED_VERSION":
        if not isinstance(version_id, (str, int)) or isinstance(version_id, bool):
            raise InputValidationError(f"actual value: {actual_value(version_id)}; allowed value: a string or integer version id when segment_type is FIXED_VERSION", field="conditions[].version_id")
    elif version_id is not None and version_id != "":
        raise InputValidationError(f"actual value: {actual_value(version_id)}; allowed value: null or \"\" unless segment_type is FIXED_VERSION", field="conditions[].version_id")
    references.segment_fields.add((field, effective_type, str(version_id or "")))


def _validate_list_controls(item: Mapping[str, Any]) -> None:
    by_list_index = item.get("by_list_index")
    if by_list_index is not None and not isinstance(by_list_index, bool):
        raise InputValidationError(f"actual value: {actual_value(by_list_index)}; allowed values: null, true, false", field="conditions[].by_list_index")
    list_index = item.get("list_index_val")
    if list_index is not None and (
        not isinstance(list_index, int)
        or isinstance(list_index, bool)
        or list_index == 0
        or not -10_000 <= list_index <= 10_000
    ):
        raise InputValidationError(f"actual value: {actual_value(list_index)}; allowed range: a non-zero integer from -10000 through 10000", field="conditions[].list_index_val")


def _add_condition_dimension(
    item: Mapping[str, Any],
    field: str,
    is_segment: bool,
    references: AnalysisReferences,
) -> None:
    table = item.get("dim_using_table_name")
    if table in {None, ""}:
        return
    if is_segment or not isinstance(table, str) or len(table) > 256:
        raise InputValidationError(
            f"actual value: {actual_value(table)}; allowed value: a metadata dimension "
            "table name of at most 256 characters on an event or user condition",
            field="conditions[].dim_using_table_name",
            next_action="Run `gravity metadata properties \"\"` and retry with the field's listed dimension table.",
        )
    field_type = item.get("type")
    if field_type in ANALYSIS_EVENT_TYPES:
        references.event_dimension_tables.add((field, table))
    elif field_type in ANALYSIS_USER_TYPES:
        references.user_dimension_tables.add((field, table))


def validate_analysis_group_by(value: Any, references: AnalysisReferences) -> None:
    if not isinstance(value, (list, tuple)) or len(value) > 20:
        raise InputValidationError(
            f"actual value: {actual_value(type(value).__name__) if not isinstance(value, (list, tuple)) else len(value)}; "
            "analysis group_by_list must be an array with at most 20 items; group "
            "values are not echoed because errors may enter logs",
            field="group_by_list",
        )
    for item in value:
        _validate_analysis_group(item, references)


def _validate_analysis_group(item: Any, references: AnalysisReferences) -> None:
    require_exact_mapping(
        item,
        {
            "type",
            "field",
            "group_by",
            "granularity",
            "operator",
            "values",
            "segment_type",
            "version_id",
            "dim_using_table_name",
        },
        "analysis group",
    )
    field = item.get("field")
    if not isinstance(field, str) or not field or len(field) > 256:
        raise InputValidationError(
            f"actual value: {actual_value(field)}; allowed value: a non-empty metadata "
            "field name of at most 256 characters",
            field="group_by_list[].field",
            next_action="Run `gravity metadata properties \"\"` or `gravity metadata events \"\"` and retry with a listed field.",
        )
    reject_sensitive_analysis_field(field)
    if item.get("type") in ANALYSIS_EVENT_TYPES and field == "create_time":
        _validate_time_group(item, field, references)
        return
    if item.get("group_by") != field or item.get("granularity") is not None:
        raise InputValidationError(
            f"actual value: {actual_value({'group_by': item.get('group_by'), 'granularity': item.get('granularity')})}; "
            f"allowed values: group_by={actual_value(field)} and granularity=null for a property group",
            field="group_by_list[]",
        )
    _add_group_reference(item, field, references)
    _validate_group_property_controls(item)
    _validate_group_segment_controls(item)
    _add_group_dimension(item, field, references)


def _validate_time_group(
    item: Mapping[str, Any], field: str, references: AnalysisReferences
) -> None:
    references.event_fields.add(field)
    group_by = item.get("group_by")
    if group_by not in ANALYSIS_TIME_GROUPS:
        raise InputValidationError(f"actual value: {actual_value(group_by)}; allowed values: {allowed_values(ANALYSIS_TIME_GROUPS)}", field="group_by_list[].group_by")
    granularity = item.get("granularity")
    if granularity is not None and (group_by != "minute" or granularity not in {1, 5, 10}):
        raise InputValidationError(f"actual value: {actual_value(granularity)}; allowed values: null, 1, 5, 10 when group_by is minute", field="group_by_list[].granularity")
    if (
        item.get("operator") not in {None, ""}
        or item.get("values") not in (None, (), [])
        or item.get("segment_type") not in {None, ""}
        or item.get("version_id") not in {None, ""}
        or item.get("dim_using_table_name") not in {None, ""}
    ):
        populated = sorted(
            key
            for key in ("operator", "values", "segment_type", "version_id", "dim_using_table_name")
            if item.get(key) not in (None, "", (), [])
        )
        raise InputValidationError(
            f"actual value: {actual_value(populated)}; allowed controls: group_by and "
            "minute granularity only for a create_time group",
            field="group_by_list[]",
        )


def _add_group_reference(
    item: Mapping[str, Any], field: str, references: AnalysisReferences
) -> None:
    field_type = item.get("type")
    if field_type in ANALYSIS_EVENT_TYPES:
        references.event_fields.add(field)
    elif field_type in ANALYSIS_USER_TYPES:
        references.user_fields.add(field)
    elif field_type == "user_segment":
        _add_group_segment(item, field, references)
    else:
        raise InputValidationError(f"actual value: {actual_value(field_type)}; allowed values: {allowed_values(ANALYSIS_EVENT_TYPES | ANALYSIS_USER_TYPES | frozenset({'user_segment'}))}", field="group_by_list[].type")


def _add_group_segment(
    item: Mapping[str, Any], field: str, references: AnalysisReferences
) -> None:
    segment_type = item.get("segment_type")
    version_id = item.get("version_id")
    if segment_type not in _SEGMENT_TYPES:
        raise InputValidationError(f"actual value: {actual_value(segment_type)}; allowed values: {allowed_values(_SEGMENT_TYPES)}", field="group_by_list[].segment_type")
    if segment_type == "FIXED_VERSION":
        if not isinstance(version_id, (str, int)) or isinstance(version_id, bool):
            raise InputValidationError(f"actual value: {actual_value(version_id)}; allowed value: a string or integer version id when segment_type is FIXED_VERSION", field="group_by_list[].version_id")
    elif version_id not in {None, ""}:
        raise InputValidationError(f"actual value: {actual_value(version_id)}; allowed value: null or \"\" unless segment_type is FIXED_VERSION", field="group_by_list[].version_id")
    references.segment_fields.add(
        (field, str(segment_type or "LATEST"), str(version_id or ""))
    )
    if item.get("operator") not in {None, ""} or item.get("values") not in (None, (), []):
        raise InputValidationError(
            f"actual value: {actual_value({'operator': item.get('operator'), 'value_count': len(item.get('values') or ())})}; "
            "allowed values: operator=null and an empty values array for a segment group",
            field="group_by_list[]",
        )


def _validate_group_property_controls(item: Mapping[str, Any]) -> None:
    operator = item.get("operator")
    values = item.get("values")
    if operator not in {None, ""}:
        if operator not in ANALYSIS_PROPERTY_GROUP_OPERATORS:
            raise InputValidationError(f"actual value: {actual_value(operator)}; allowed values: {allowed_values(ANALYSIS_PROPERTY_GROUP_OPERATORS)}", field="group_by_list[].operator")
        validate_scalar_list(values or (), "analysis group values")
    elif values not in (None, (), []):
        raise InputValidationError(
            f"actual value: {actual_value({'operator': operator, 'value_count': len(values) if isinstance(values, (list, tuple)) else 1})}; "
            "allowed shape: set an operator when values are present",
            field="group_by_list[].operator",
        )


def _validate_group_segment_controls(item: Mapping[str, Any]) -> None:
    if item.get("type") != "user_segment" and (
        item.get("segment_type") not in {None, "", "LATEST"}
        or item.get("version_id") not in {None, ""}
    ):
        raise InputValidationError(
            f"actual value: {actual_value({'type': item.get('type'), 'segment_type': item.get('segment_type'), 'version_id': item.get('version_id')})}; "
            "allowed shape: segment_type and version_id require type=user_segment",
            field="group_by_list[]",
        )


def _add_group_dimension(
    item: Mapping[str, Any], field: str, references: AnalysisReferences
) -> None:
    table = item.get("dim_using_table_name")
    if table in {None, ""}:
        return
    field_type = item.get("type")
    if field_type == "user_segment" or not isinstance(table, str) or len(table) > 256:
        raise InputValidationError(
            f"actual value: {actual_value(table)}; allowed value: a metadata dimension "
            "table name of at most 256 characters on an event or user group",
            field="group_by_list[].dim_using_table_name",
            next_action="Run `gravity metadata properties \"\"` and retry with the field's listed dimension table.",
        )
    if field_type in ANALYSIS_EVENT_TYPES:
        references.event_dimension_tables.add((field, table))
    else:
        references.user_dimension_tables.add((field, table))


def validate_analysis_user_reattribute_filtering(value: Any, label: str) -> None:
    if not isinstance(value, Mapping) or len(value) > len(ANALYSIS_USER_REATTRIBUTE_FIELDS):
        raise InputValidationError(
            f"actual value: {actual_value(type(value).__name__) if not isinstance(value, Mapping) else len(value)}; "
            f"{label} must be an object with at most "
            f"{len(ANALYSIS_USER_REATTRIBUTE_FIELDS)} fields; filter values are not "
            "echoed because errors may enter logs",
            field=label,
        )
    if set(value) - ANALYSIS_USER_REATTRIBUTE_FIELDS:
        unknown = sorted(set(value) - ANALYSIS_USER_REATTRIBUTE_FIELDS)
        raise InputValidationError(
            f"actual value: {actual_value(unknown)}; allowed fields: "
            f"{allowed_values(ANALYSIS_USER_REATTRIBUTE_FIELDS)}",
            field=label,
        )
    for item in value.values():
        if isinstance(item, (list, tuple)):
            validate_scalar_list(item, label)
        elif not analysis_scalar(item):
            raise InputValidationError(
                f"actual value: {actual_value(type(item).__name__)}; {label} values "
                "must be scalar or scalar arrays; filter values are not echoed because "
                "errors may enter logs",
                field=label,
            )


def validate_analysis_filter_map(value: Any, references: set[str], label: str) -> None:
    if not isinstance(value, Mapping) or len(value) > 100:
        raise InputValidationError(
            f"actual value: {actual_value(type(value).__name__) if not isinstance(value, Mapping) else len(value)}; "
            f"{label} must be an object with at most 100 fields; filter values are not "
            "echoed because errors may enter logs",
            field=label,
        )
    for key, item in value.items():
        if not isinstance(key, str) or not key or len(key) > 256:
            raise InputValidationError(
                f"actual value: {actual_value(key)}; allowed value: a non-empty "
                "metadata field name of at most 256 characters",
                field=label,
                next_action="Run `gravity metadata properties \"\"` and retry with a listed field.",
            )
        reject_sensitive_analysis_field(key)
        references.add(key)
        if isinstance(item, (list, tuple)):
            validate_scalar_list(item, label)
        elif not analysis_scalar(item):
            raise InputValidationError(
                f"actual value: {actual_value(type(item).__name__)}; {label} values "
                "must be scalar or scalar arrays; filter values are not echoed because "
                "errors may enter logs",
                field=label,
            )


def validate_property_order(value: Any, references: AnalysisReferences) -> None:
    if not isinstance(value, (list, tuple)) or len(value) > 20:
        raise InputValidationError(
            f"actual value: {len(value) if isinstance(value, (list, tuple)) else actual_value(type(value).__name__)}; allowed value: an array with at "
            "most 20 property order items",
            field="order_by_list",
        )
    for item in value:
        require_exact_mapping(item, {"field", "sort", "data_type"}, "property order item")
        field = item.get("field")
        if not isinstance(field, str) or not field:
            raise InputValidationError(
                f"actual value: {actual_value(field)}; allowed value: a non-empty "
                "metadata property name",
                field="order_by_list[].field",
                next_action="Run `gravity metadata properties \"\"` and retry with a listed field.",
            )
        reject_sensitive_analysis_field(field)
        references.user_fields.add(field)
        direction = item.get("sort")
        if direction not in _ORDER_DIRECTIONS:
            raise InputValidationError(f"actual value: {actual_value(direction)}; allowed values: {allowed_values(_ORDER_DIRECTIONS)}", field="order_by_list[].sort")
        data_type = item.get("data_type")
        if data_type not in ({None} | _ANALYSIS_DATA_TYPES):
            raise InputValidationError(f"actual value: {actual_value(data_type)}; allowed values: null, {allowed_values(_ANALYSIS_DATA_TYPES)}", field="order_by_list[].data_type")
