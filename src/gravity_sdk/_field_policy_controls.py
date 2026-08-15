"""Request controls and metadata-backed dynamic response field validation."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from ._field_policy_metadata import (
    all_exclusion_dimensions,
    load_view,
    names,
    select_rows,
)
from ._field_policy_operations import (
    PROMOTION_METRIC,
    REPORT_BUSINESS_METRIC,
    REPORT_MULTIDIM_CUSTOM_METRIC,
    REPORT_MULTIDIM_METRIC,
    REPORT_MULTIDIM_SHARED_METRIC,
    operation_rule,
)
from ._field_policy_shared import (
    MetadataLoader,
    MetadataView,
    control_fields,
    dynamic_values,
    is_sensitive_control_key,
    order_field,
    promotion_metadata_inputs,
    reject_unhandled,
)
from .errors import InputValidationError
from .models import OperationSpec


def validate_request_controls(
    operation: OperationSpec,
    inputs: Mapping[str, Any],
    metadata_loader: MetadataLoader,
) -> None:
    controls = control_fields(operation, inputs)
    if operation.operation_id == PROMOTION_METRIC:
        _validate_promotion_metric_type(inputs)
    filters = inputs.get("filters")
    if isinstance(filters, (list, tuple)) and filters:
        _validate_filters(operation, inputs, filters, controls, metadata_loader)
    filtering = inputs.get("filtering")
    if isinstance(filtering, Mapping) and filtering:
        _validate_filtering(filtering, controls)
    data_list = inputs.get("data_list")
    if isinstance(data_list, (list, tuple)):
        _validate_data_list(data_list, controls)
    order_by = inputs.get("order_by")
    if isinstance(order_by, (list, tuple)):
        _validate_order_by(order_by, controls)


def _validate_promotion_metric_type(inputs: Mapping[str, Any]) -> None:
    metric_type = inputs.get("metric_type")
    if metric_type is not None and inputs.get("media_type") != "tencentV3":
        raise InputValidationError(
            "metric_type is only enabled for the verified Tencent metadata profile; "
            "request was not sent"
        )


def _validate_filters(
    operation: OperationSpec,
    inputs: Mapping[str, Any],
    filters: Sequence[Any],
    controls: set[str],
    loader: MetadataLoader,
) -> None:
    rule = operation_rule(operation.operation_id)
    operators: set[str | int]
    if operation.domain == "promotion":
        operators = {1}
        unresolved = {
            str(item.get("field"))
            for item in filters
            if isinstance(item, Mapping) and item.get("field") not in controls
        }
        if unresolved:
            profile = promotion_metadata_inputs(operation, inputs)
            view = load_view(PROMOTION_METRIC, profile, loader)
            controls.update(names(view.rows, keys=("name",)))
    else:
        operators = {
            1,
            "EQUALS",
            "IN",
            "NOT_EQUALS",
            "NOT_IN",
            "CONTAINS",
            "GT",
            "GTE",
            "LT",
            "LTE",
            "RANGE_IN",
            8,
        }
    for item in filters:
        _validate_filter_item(item, controls, operators, rule)


def _validate_filter_item(
    item: Any,
    controls: set[str],
    operators: set[str | int],
    rule: Any,
) -> None:
    if not isinstance(item, Mapping):
        raise InputValidationError("filter contract is invalid; request was not sent")
    field_name = str(item.get("field", ""))
    operator = item.get("operator")
    if rule.exact_filter_profile is not None:
        allowed_operators = rule.exact_filter_profile.get(field_name)
        if allowed_operators is None or operator not in allowed_operators:
            raise InputValidationError(
                "filter field/operator pair is absent from the exact operation "
                "profile; request was not sent"
            )
        validate_exact_filter_values(rule.exact_filter_values, field_name, item)
        return
    if field_name not in controls:
        raise InputValidationError(
            "filter field is absent from the operation field policy; request was not sent"
        )
    if operator not in operators:
        raise InputValidationError(
            "filter operator is absent from the operation codec; request was not sent"
        )


def validate_exact_filter_values(
    value_kind: str | None, field_name: str, item: Mapping[str, Any]
) -> None:
    if value_kind == "account":
        _validate_account_filter_values(field_name, item)
    elif value_kind in {"template", "dashboard"}:
        _validate_named_filter_values(field_name, item)


def _filter_values(item: Mapping[str, Any], message: str) -> Sequence[Any]:
    values = item.get("values", item.get("value", ()))
    if not isinstance(values, (list, tuple)) or not values:
        raise InputValidationError(message)
    return values


def _validate_account_filter_values(
    field_name: str, item: Mapping[str, Any]
) -> None:
    values = _filter_values(
        item,
        "account member filter values must be a non-empty array; request was not sent",
    )
    if field_name in {"dept_id", "role_id"}:
        if any(
            not isinstance(value, (str, int))
            or isinstance(value, bool)
            or not str(value)
            or len(str(value)) > 64
            for value in values
        ):
            raise InputValidationError(
                "account member identifier filter is invalid; request was not sent"
            )
        return
    if any(not isinstance(value, str) or len(value) > 256 for value in values):
        raise InputValidationError(
            "account member text filter is invalid; request was not sent"
        )


def _validate_named_filter_values(
    field_name: str, item: Mapping[str, Any]
) -> None:
    values = _filter_values(
        item,
        "exact analysis filter values must be a non-empty array; request was not sent",
    )
    if field_name == "template_type":
        if any(value not in {"report", "kanban"} for value in values):
            raise InputValidationError(
                "template_type filter value is absent from the frontend contract; request was not sent"
            )
    elif field_name == "name":
        if any(not isinstance(value, str) or len(value) > 256 for value in values):
            raise InputValidationError(
                "analysis name filter value is invalid; request was not sent"
            )
    elif field_name == "dashboard_id":
        if any(not isinstance(value, str) or not value for value in values):
            raise InputValidationError(
                "dashboard filter identifier is invalid; request was not sent"
            )
    elif field_name in {"default_to_one", "default_to_all"} and any(
        value != "1" for value in values
    ):
        raise InputValidationError(
            "dashboard default filter value is invalid; request was not sent"
        )


def _validate_filtering(value: Mapping[str, Any], controls: set[str]) -> None:
    allowed = controls | {"keyword", "search_keyword", "search_type"}
    if any(str(key) not in allowed for key in value):
        raise InputValidationError(
            "filtering contains fields absent from the operation policy; request was not sent"
        )
    if any(
        item is None or isinstance(item, (Mapping, list, tuple))
        for item in value.values()
    ):
        raise InputValidationError(
            "filtering values must be scalar; request was not sent"
        )


def _validate_data_list(value: Sequence[Any], controls: set[str]) -> None:
    for row in value:
        if not isinstance(row, Mapping):
            raise InputValidationError(
                "data_list rows must be controlled objects; request was not sent"
            )
        row_keys = {str(key) for key in row}
        if not row_keys <= controls or any(is_sensitive_control_key(key) for key in row_keys):
            raise InputValidationError(
                "data_list contains fields absent from the operation policy; "
                "request was not sent"
            )
        if any(isinstance(item, (Mapping, list, tuple)) for item in row.values()):
            raise InputValidationError(
                "data_list values must be scalar; request was not sent"
            )


def _validate_order_by(value: Sequence[Any], controls: set[str]) -> None:
    for item in value:
        field_name = order_field(item)
        if field_name is None or field_name not in controls:
            raise InputValidationError(
                "order_by contains a field absent from the operation policy; request was not sent"
            )


def validate_dynamic_response_fields(
    operation: OperationSpec,
    inputs: Mapping[str, Any],
    metadata_loader: MetadataLoader,
) -> None:
    values = {
        name: dynamic_values(operation, name, inputs.get(name))
        for name in operation.response_projection.dynamic_item_fields
    }
    requested = {
        name: items
        for name, items in values.items()
        if items and not operation.fields[name].enum and not operation.fields[name].item_enum
    }
    if not requested:
        return
    if operation.domain == "promotion" and "query_fields" in requested:
        reject_unhandled(requested, {"query_fields"})
        validate_promotion(operation, requested["query_fields"], inputs, metadata_loader)
        return
    request_kind = operation_rule(operation.operation_id).request_kind
    if request_kind == "business_query":
        reject_unhandled(requested, {"metrics_list", "dims_list"})
        validate_business(operation, requested, metadata_loader)
        return
    if request_kind == "multidim_query":
        reject_unhandled(
            requested,
            {"data_dims", "relate_dims", "metrics_list", "custom_metrics_list"},
        )
        validate_multidim(operation, requested, metadata_loader)
        return
    raise InputValidationError(
        "dynamic response fields have no registered metadata validator; request was not sent"
    )


def validate_promotion(
    operation: OperationSpec,
    requested: Sequence[str],
    inputs: Mapping[str, Any],
    metadata_loader: MetadataLoader,
) -> None:
    unresolved = set(requested) - set(operation.response_projection.item_keys)
    if not unresolved:
        return
    if not operation.platform:
        raise InputValidationError(
            "promotion field metadata has no platform context; request was not sent"
        )
    view = load_view(
        PROMOTION_METRIC,
        promotion_metadata_inputs(operation, inputs),
        metadata_loader,
    )
    if not unresolved <= names(view.rows, keys=("name",)):
        raise InputValidationError(
            "query_fields contains values absent from live platform metadata; request was not sent"
        )


def validate_business(
    operation: OperationSpec,
    requested_by_field: Mapping[str, Sequence[str]],
    metadata_loader: MetadataLoader,
) -> None:
    requested = {item for items in requested_by_field.values() for item in items}
    if not requested:
        return
    view = load_view(REPORT_BUSINESS_METRIC, {}, metadata_loader)
    if not view.rows:
        raise InputValidationError(
            "business metric metadata is empty; request was not sent"
        )
    allowed = set(operation.response_projection.item_keys) | names(view.rows)
    if not requested <= allowed:
        raise InputValidationError(
            "business metrics/dimensions are absent from live metadata; request was not sent"
        )


def validate_multidim(
    operation: OperationSpec,
    requested_by_field: Mapping[str, Sequence[str]],
    metadata_loader: MetadataLoader,
) -> None:
    metrics = tuple(requested_by_field.get("metrics_list", ()))
    custom_metrics = tuple(requested_by_field.get("custom_metrics_list", ()))
    dimensions = tuple(requested_by_field.get("data_dims", ())) + tuple(
        requested_by_field.get("relate_dims", ())
    )
    nonstatic_dimensions = set(dimensions) - set(operation.response_projection.item_keys)
    views = _load_multidim_views(
        bool(metrics or dimensions),
        bool(custom_metrics or nonstatic_dimensions),
        metadata_loader,
    )
    selected_rows = _selected_metric_rows(metrics, custom_metrics, views)
    if nonstatic_dimensions:
        _validate_nonstatic_dimensions(nonstatic_dimensions, views)
    if dimensions and selected_rows:
        exclusions, complete = all_exclusion_dimensions(selected_rows)
        if not complete:
            raise InputValidationError(
                "selected metric exclusion metadata is incomplete; request was not sent"
            )
        if set(dimensions) & exclusions:
            raise InputValidationError(
                "selected dimensions conflict with live metric exclusions; request was not sent"
            )


def _load_multidim_views(
    need_standard: bool,
    need_custom: bool,
    loader: MetadataLoader,
) -> dict[str, MetadataView]:
    result: dict[str, MetadataView] = {}
    if need_standard:
        result[REPORT_MULTIDIM_METRIC] = load_view(REPORT_MULTIDIM_METRIC, {}, loader)
    if need_custom:
        result[REPORT_MULTIDIM_CUSTOM_METRIC] = load_view(
            REPORT_MULTIDIM_CUSTOM_METRIC, {}, loader
        )
        result[REPORT_MULTIDIM_SHARED_METRIC] = load_view(
            REPORT_MULTIDIM_SHARED_METRIC, {}, loader
        )
    return result


def _selected_metric_rows(
    metrics: Sequence[str],
    custom_metrics: Sequence[str],
    views: Mapping[str, MetadataView],
) -> tuple[Mapping[str, Any], ...]:
    standard_rows = views[REPORT_MULTIDIM_METRIC].rows if metrics else ()
    selected = select_rows(standard_rows, metrics, "metrics_list")
    if custom_metrics:
        custom_rows = (
            views[REPORT_MULTIDIM_CUSTOM_METRIC].rows
            + views[REPORT_MULTIDIM_SHARED_METRIC].rows
        )
        selected += select_rows(custom_rows, custom_metrics, "custom_metrics_list")
    return selected


def _validate_nonstatic_dimensions(
    requested: set[str], views: Mapping[str, MetadataView]
) -> None:
    all_views = (
        views[REPORT_MULTIDIM_METRIC],
        views[REPORT_MULTIDIM_CUSTOM_METRIC],
        views[REPORT_MULTIDIM_SHARED_METRIC],
    )
    if any(item.status not in {"success", "empty"} for item in all_views):
        raise InputValidationError(
            "dimension metadata is incomplete; request was not sent"
        )
    rows = tuple(row for item in all_views for row in item.rows)
    known, complete = all_exclusion_dimensions(rows)
    if not complete or not requested <= known:
        raise InputValidationError(
            "data_dims/relate_dims are absent from complete live metadata; request was not sent"
        )
