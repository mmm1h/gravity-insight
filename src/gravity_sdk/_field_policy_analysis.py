"""Top-level orchestration for Analysis query and segment validation."""

from __future__ import annotations

from typing import Any, Mapping

from .analysis_execution_support import (
    reject_unsupported_property_groups,
    validate_segment_event_support_inputs,
)
from ._field_policy_conditions import (
    validate_analysis_conditions,
    validate_analysis_filter_map,
    validate_analysis_group_by,
    validate_analysis_user_reattribute_filtering,
    validate_property_order,
    validate_property_query_item,
)
from ._field_policy_event import (
    validate_analysis_aggregate_config,
    validate_analysis_custom_items,
    validate_analysis_event_items,
    validate_analysis_extra_data,
    validate_analysis_scatter_items,
    validate_analysis_split_event,
    validate_analysis_window,
    validate_event_query_labels,
)
from ._field_policy_metadata import validate_analysis_reference_membership
from ._field_policy_retention import validate_retention_before_after
from ._field_policy_segment import validate_analysis_segment_rule_shape
from ._field_policy_shared import (
    ANALYSIS_QUERY_ID_RE,
    AnalysisReferences,
    MetadataLoader,
    new_analysis_references,
    parse_analysis_datetime,
    require_exact_mapping,
)
from .errors import InputValidationError


def validate_analysis_query(
    query_kind: str,
    inputs: Mapping[str, Any],
    metadata_loader: MetadataLoader,
) -> None:
    references = validate_analysis_shape(query_kind, inputs)
    app_id = inputs.get("app_id")
    if not isinstance(app_id, str) or not app_id or len(app_id) > 64:
        raise InputValidationError(
            "analysis app_id must be a bounded identifier; request was not sent"
        )
    validate_analysis_reference_membership(app_id, references, metadata_loader)


def validate_analysis_segment_rule(
    inputs: Mapping[str, Any],
    metadata_loader: MetadataLoader,
) -> None:
    references = validate_analysis_segment_rule_shape(inputs)
    validate_segment_event_support_inputs(inputs)
    app_id = inputs.get("app_id")
    if not isinstance(app_id, str) or not app_id.isdecimal() or len(app_id) > 64:
        raise InputValidationError(
            "analysis segment-rule app_id must be a decimal identifier; "
            "request was not sent"
        )
    validate_analysis_reference_membership(app_id, references, metadata_loader)


def validate_analysis_shape(
    query_kind: str, inputs: Mapping[str, Any]
) -> AnalysisReferences:
    query_id = inputs.get("query_id")
    if not isinstance(query_id, str) or not ANALYSIS_QUERY_ID_RE.fullmatch(query_id):
        raise InputValidationError(
            "analysis query_id must be an opaque identifier; request was not sent"
        )
    references = new_analysis_references()
    validate_analysis_group_by(inputs.get("group_by_list", ()), references)
    if query_kind == "property":
        reject_unsupported_property_groups(inputs.get("group_by_list", ()))
        _validate_property_query(inputs, references)
        return references
    validate_analysis_date_list(inputs.get("date_list"), query_kind)
    _validate_query_items(query_kind, inputs.get("query_item_list"), references)
    validate_analysis_conditions(
        inputs.get("global_conditions", ()), references, "global_conditions"
    )
    if query_kind == "funnel":
        _reject_funnel_user_property_conditions(inputs.get("global_conditions", ()))
    _validate_query_kind_controls(query_kind, inputs, references)
    return references


def _reject_funnel_user_property_conditions(value: Any) -> None:
    if any(
        item.get("type") == "user_property"
        and item.get("segment_type") in {None, ""}
        for item in value
    ):
        raise InputValidationError(
            "analysis funnel global_conditions must use type 'user' for user "
            "properties; request was not sent",
            field="global_conditions",
            next_action=(
                "Change each funnel user-property condition type to `user`, then "
                "retry the same request."
            ),
        )


def _validate_property_query(
    inputs: Mapping[str, Any], references: AnalysisReferences
) -> None:
    validate_property_query_item(inputs.get("query_item"), references)
    validate_analysis_filter_map(
        inputs.get("user_filtering", {}), references.user_fields, "user_filtering"
    )
    validate_analysis_user_reattribute_filtering(
        inputs.get("user_re_attribute_filtering", {}),
        "user_re_attribute_filtering",
    )
    validate_analysis_conditions(
        inputs.get("property_condition", ()), references, "property_condition"
    )
    validate_property_order(inputs.get("order_by_list", ()), references)


def _validate_query_items(
    query_kind: str, value: Any, references: AnalysisReferences
) -> None:
    minimum = 2 if query_kind in {"funnel", "retention"} else 1
    maximum = 2 if query_kind == "retention" else 50
    if query_kind == "scatter":
        validate_analysis_scatter_items(
            value, references, minimum=minimum, maximum=maximum
        )
    else:
        validate_analysis_event_items(
            value, references, minimum=minimum, maximum=maximum
        )


def _validate_query_kind_controls(
    query_kind: str,
    inputs: Mapping[str, Any],
    references: AnalysisReferences,
) -> None:
    if query_kind == "event":
        _validate_event_controls(inputs, references)
    elif query_kind == "funnel":
        validate_analysis_window(inputs.get("stat_time_window"))
    elif query_kind == "retention":
        _validate_retention_controls(inputs, references)
    elif query_kind == "scatter":
        validate_analysis_extra_data(inputs.get("extra_data", {}))


def _validate_event_controls(
    inputs: Mapping[str, Any], references: AnalysisReferences
) -> None:
    validate_event_query_labels(inputs.get("query_item_list"))
    validate_analysis_custom_items(inputs.get("custom_query_item_list", ()), references)
    validate_analysis_split_event(inputs.get("split_event", {}), references)
    validate_analysis_aggregate_config(inputs.get("aggregate_config", {}))
    validate_analysis_extra_data(inputs.get("extra_data", {}))


def _validate_retention_controls(
    inputs: Mapping[str, Any], references: AnalysisReferences
) -> None:
    validate_retention_before_after(
        inputs.get("query_item_before_after", {}), references
    )
    validate_analysis_filter_map(
        inputs.get("user_filtering", {}), references.user_fields, "user_filtering"
    )
    validate_analysis_user_reattribute_filtering(
        inputs.get("user_re_attribute_filtering", {}),
        "user_re_attribute_filtering",
    )
    validate_analysis_conditions(
        inputs.get("property_condition", ()), references, "property_condition"
    )
    offset = inputs.get("offset")
    if not isinstance(offset, int) or isinstance(offset, bool) or not 1 <= offset <= 365:
        raise InputValidationError(
            "analysis retention offset is outside the controlled range; request was not sent"
        )
    week_first_day = inputs.get("week_first_day")
    if (
        not isinstance(week_first_day, int)
        or isinstance(week_first_day, bool)
        or not 1 <= week_first_day <= 7
    ):
        raise InputValidationError(
            "analysis week_first_day is outside the controlled range; request was not sent"
        )


def validate_analysis_date_list(value: Any, query_kind: str) -> None:
    maximum = 2 if query_kind == "event" else 1
    if not isinstance(value, (list, tuple)) or not 1 <= len(value) <= maximum:
        raise InputValidationError(
            "analysis date_list is invalid; request was not sent"
        )
    for item in value:
        require_exact_mapping(item, {"start_date", "end_date"}, "analysis date range")
        start = parse_analysis_datetime(item.get("start_date"))
        end = parse_analysis_datetime(item.get("end_date"))
        if start.tzinfo != end.tzinfo or start > end or (end - start).days > 90:
            raise InputValidationError(
                "analysis date range exceeds the controlled 90-day span; request was not sent"
            )
