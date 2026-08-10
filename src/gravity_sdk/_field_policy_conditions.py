"""Common Analysis DSL targets, conditions, grouping, and property controls."""

from __future__ import annotations

import re
from typing import Any, Mapping

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
            "analysis target method is not registered; request was not sent"
        )
    if not isinstance(field, str) or not field or len(field) > 256:
        raise InputValidationError(
            "analysis target field is invalid; request was not sent"
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
        raise InputValidationError(
            "analysis quantile_level is invalid; request was not sent"
        )


def _add_dimension_reference(
    table: Any,
    field: str,
    references: set[tuple[str, str]],
) -> None:
    if table in {None, ""}:
        return
    if not isinstance(table, str) or len(table) > 256:
        raise InputValidationError(
            "analysis dimension table is invalid; request was not sent"
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
            "property target method is not registered; request was not sent"
        )
    if not isinstance(field, str) or not field or len(field) > 256:
        raise InputValidationError(
            "property target field is invalid; request was not sent"
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
    if target.get("data_type") not in {
        None,
        "STRING",
        "INT",
        "FLOAT",
        "BOOL",
        "DATE",
        "DATETIME",
        "LIST",
    }:
        raise InputValidationError(
            "property target data_type is not registered; request was not sent"
        )
    if target.get("type") not in ({None, ""} | ANALYSIS_USER_TYPES):
        raise InputValidationError(
            "property target type is not registered; request was not sent"
        )
    table = target.get("dim_using_table_name")
    if table not in {None, ""}:
        if not isinstance(table, str) or len(table) > 256:
            raise InputValidationError(
                "property dimension table is invalid; request was not sent"
            )
        references.user_dimension_tables.add((field, table))


def validate_analysis_conditions(
    value: Any,
    references: AnalysisReferences,
    label: str,
) -> None:
    if not isinstance(value, (list, tuple)) or len(value) > 100:
        raise InputValidationError(f"{label} is invalid; request was not sent")
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
            "analysis condition operator is not registered; request was not sent"
        )
    field = item.get("field")
    if not isinstance(field, str) or not field or len(field) > 256:
        raise InputValidationError(
            "analysis condition field is invalid; request was not sent"
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
    if segment_type not in {None, "", "LATEST", "DYNAMIC_MATCHING", "FIXED_VERSION"}:
        raise InputValidationError(
            "analysis segment_type is not registered; request was not sent"
        )
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
        raise InputValidationError(
            "analysis condition type is not registered; request was not sent"
        )
    return is_segment


def _add_segment_reference(
    field: str,
    field_type: Any,
    segment_type: Any,
    version_id: Any,
    references: AnalysisReferences,
) -> None:
    if field_type not in (ANALYSIS_USER_TYPES | frozenset({"user_segment"})):
        raise InputValidationError(
            "analysis segment condition must use a user field type; request was not sent"
        )
    effective_type = str(segment_type or "LATEST")
    if effective_type == "FIXED_VERSION":
        if not isinstance(version_id, (str, int)) or isinstance(version_id, bool):
            raise InputValidationError(
                "analysis fixed segment version is invalid; request was not sent"
            )
    elif version_id is not None and version_id != "":
        raise InputValidationError(
            "analysis segment version requires FIXED_VERSION; request was not sent"
        )
    references.segment_fields.add((field, effective_type, str(version_id or "")))


def _validate_list_controls(item: Mapping[str, Any]) -> None:
    by_list_index = item.get("by_list_index")
    if by_list_index is not None and not isinstance(by_list_index, bool):
        raise InputValidationError(
            "analysis by_list_index is invalid; request was not sent"
        )
    list_index = item.get("list_index_val")
    if list_index is not None and (
        not isinstance(list_index, int)
        or isinstance(list_index, bool)
        or list_index == 0
        or not -10_000 <= list_index <= 10_000
    ):
        raise InputValidationError(
            "analysis list_index_val is invalid; request was not sent"
        )


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
            "analysis dimension table is invalid; request was not sent"
        )
    field_type = item.get("type")
    if field_type in ANALYSIS_EVENT_TYPES:
        references.event_dimension_tables.add((field, table))
    elif field_type in ANALYSIS_USER_TYPES:
        references.user_dimension_tables.add((field, table))


def validate_analysis_group_by(value: Any, references: AnalysisReferences) -> None:
    if not isinstance(value, (list, tuple)) or len(value) > 20:
        raise InputValidationError(
            "analysis group_by_list is invalid; request was not sent"
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
            "analysis group field is invalid; request was not sent"
        )
    reject_sensitive_analysis_field(field)
    if item.get("type") in ANALYSIS_EVENT_TYPES and field == "create_time":
        _validate_time_group(item, field, references)
        return
    if item.get("group_by") != field or item.get("granularity") is not None:
        raise InputValidationError(
            "analysis property group must use its metadata field; request was not sent"
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
        raise InputValidationError(
            "analysis time group is not registered; request was not sent"
        )
    granularity = item.get("granularity")
    if granularity is not None and (group_by != "minute" or granularity not in {1, 5, 10}):
        raise InputValidationError(
            "analysis group granularity is invalid; request was not sent"
        )
    if (
        item.get("operator") not in {None, ""}
        or item.get("values") not in (None, (), [])
        or item.get("segment_type") not in {None, ""}
        or item.get("version_id") not in {None, ""}
        or item.get("dim_using_table_name") not in {None, ""}
    ):
        raise InputValidationError(
            "analysis time group contains unsupported controls; request was not sent"
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
        raise InputValidationError(
            "analysis group type is not registered; request was not sent"
        )


def _add_group_segment(
    item: Mapping[str, Any], field: str, references: AnalysisReferences
) -> None:
    segment_type = item.get("segment_type")
    version_id = item.get("version_id")
    if segment_type not in {None, "", "LATEST", "DYNAMIC_MATCHING", "FIXED_VERSION"}:
        raise InputValidationError(
            "analysis segment group mode is not registered; request was not sent"
        )
    if segment_type == "FIXED_VERSION":
        if not isinstance(version_id, (str, int)) or isinstance(version_id, bool):
            raise InputValidationError(
                "analysis segment group version is invalid; request was not sent"
            )
    elif version_id not in {None, ""}:
        raise InputValidationError(
            "analysis segment group version requires FIXED_VERSION; request was not sent"
        )
    references.segment_fields.add(
        (field, str(segment_type or "LATEST"), str(version_id or ""))
    )
    if item.get("operator") not in {None, ""} or item.get("values") not in (None, (), []):
        raise InputValidationError(
            "analysis segment group does not accept property controls; request was not sent"
        )


def _validate_group_property_controls(item: Mapping[str, Any]) -> None:
    operator = item.get("operator")
    values = item.get("values")
    if operator not in {None, ""}:
        if operator not in ANALYSIS_PROPERTY_GROUP_OPERATORS:
            raise InputValidationError(
                "analysis property group operator is not registered; request was not sent"
            )
        validate_scalar_list(values or (), "analysis group values")
    elif values not in (None, (), []):
        raise InputValidationError(
            "analysis group values require an operator; request was not sent"
        )


def _validate_group_segment_controls(item: Mapping[str, Any]) -> None:
    if item.get("type") != "user_segment" and (
        item.get("segment_type") not in {None, "", "LATEST"}
        or item.get("version_id") not in {None, ""}
    ):
        raise InputValidationError(
            "analysis segment controls require a segment group; request was not sent"
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
            "analysis dimension table is invalid; request was not sent"
        )
    if field_type in ANALYSIS_EVENT_TYPES:
        references.event_dimension_tables.add((field, table))
    else:
        references.user_dimension_tables.add((field, table))


def validate_analysis_user_reattribute_filtering(value: Any, label: str) -> None:
    if not isinstance(value, Mapping) or len(value) > len(ANALYSIS_USER_REATTRIBUTE_FIELDS):
        raise InputValidationError(f"{label} is invalid; request was not sent")
    if set(value) - ANALYSIS_USER_REATTRIBUTE_FIELDS:
        raise InputValidationError(
            f"{label} contains unregistered fields; request was not sent"
        )
    for item in value.values():
        if isinstance(item, (list, tuple)):
            validate_scalar_list(item, label)
        elif not analysis_scalar(item):
            raise InputValidationError(
                f"{label} values must be scalar; request was not sent"
            )


def validate_analysis_filter_map(value: Any, references: set[str], label: str) -> None:
    if not isinstance(value, Mapping) or len(value) > 100:
        raise InputValidationError(f"{label} is invalid; request was not sent")
    for key, item in value.items():
        if not isinstance(key, str) or not key or len(key) > 256:
            raise InputValidationError(f"{label} is invalid; request was not sent")
        reject_sensitive_analysis_field(key)
        references.add(key)
        if isinstance(item, (list, tuple)):
            validate_scalar_list(item, label)
        elif not analysis_scalar(item):
            raise InputValidationError(
                f"{label} values must be scalar; request was not sent"
            )


def validate_property_order(value: Any, references: AnalysisReferences) -> None:
    if not isinstance(value, (list, tuple)) or len(value) > 20:
        raise InputValidationError(
            "property order_by_list is invalid; request was not sent"
        )
    for item in value:
        require_exact_mapping(item, {"field", "sort", "data_type"}, "property order item")
        field = item.get("field")
        if not isinstance(field, str) or not field:
            raise InputValidationError(
                "property order field is invalid; request was not sent"
            )
        reject_sensitive_analysis_field(field)
        references.user_fields.add(field)
        if item.get("sort") not in {0, 1, -1, "asc", "desc", "ASC", "DESC"}:
            raise InputValidationError(
                "property order direction is invalid; request was not sent"
            )
        if item.get("data_type") not in {
            None,
            "STRING",
            "INT",
            "FLOAT",
            "BOOL",
            "DATE",
            "DATETIME",
            "LIST",
        }:
            raise InputValidationError(
                "property order data_type is invalid; request was not sent"
            )
