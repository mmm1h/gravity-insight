"""Request controls and metadata-backed dynamic response field validation."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from .actionable_error_values import actual_value, allowed_values
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
        _validate_filtering(filtering, controls, operation.operation_id)
    data_list = inputs.get("data_list")
    if isinstance(data_list, (list, tuple)):
        _validate_data_list(data_list, controls, operation.operation_id)
    order_by = inputs.get("order_by")
    if isinstance(order_by, (list, tuple)):
        _validate_order_by(order_by, controls, operation.operation_id)


def _validate_promotion_metric_type(inputs: Mapping[str, Any]) -> None:
    metric_type = inputs.get("metric_type")
    if metric_type is not None and inputs.get("media_type") != "tencentV3":
        raise InputValidationError(
            f"actual value: {actual_value({'metric_type': metric_type, 'media_type': inputs.get('media_type')})}; "
            "allowed shape: metric_type is only set when media_type is tencentV3",
            field="metric_type",
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
        _validate_filter_item(item, controls, operators, rule, operation.operation_id)


def _validate_filter_item(
    item: Any,
    controls: set[str],
    operators: set[str | int],
    rule: Any,
    operation_id: str,
) -> None:
    if not isinstance(item, Mapping):
        raise InputValidationError(
            f"actual value: {actual_value(type(item).__name__)}; allowed value: a filter object",
            field="filters[]",
        )
    field_name = str(item.get("field", ""))
    operator = item.get("operator")
    if rule.exact_filter_profile is not None:
        allowed_operators = rule.exact_filter_profile.get(field_name)
        if allowed_operators is None or operator not in allowed_operators:
            if allowed_operators is None:
                observed = field_name
                alternatives = allowed_values(
                    rule.exact_filter_profile,
                    discovery_action=f"gravity insight operations describe {operation_id}",
                )
                error_field = "filters[].field"
            else:
                observed = operator
                alternatives = allowed_values(allowed_operators)
                error_field = "filters[].operator"
            raise InputValidationError(
                f"actual value: {actual_value(observed)}; allowed filter field/operator "
                f"profile values: {alternatives}",
                field=error_field,
            )
        validate_exact_filter_values(rule.exact_filter_values, field_name, item)
        return
    if field_name not in controls:
        raise InputValidationError(
            f"actual value: {actual_value(field_name)}; allowed fields: "
            f"{allowed_values(controls, discovery_action=f'gravity insight operations describe {operation_id}')}",
            field="filters[].field",
        )
    if operator not in operators:
        raise InputValidationError(
            f"actual value: {actual_value(operator)}; allowed operators: "
            f"{allowed_values(operators)}",
            field="filters[].operator",
        )


def validate_exact_filter_values(
    value_kind: str | None, field_name: str, item: Mapping[str, Any]
) -> None:
    if value_kind == "account":
        _validate_account_filter_values(field_name, item)
    elif value_kind in {"template", "dashboard"}:
        _validate_named_filter_values(field_name, item)


def _filter_values(item: Mapping[str, Any], field_name: str) -> Sequence[Any]:
    values = item.get("values", item.get("value", ()))
    if not isinstance(values, (list, tuple)) or not values:
        raise InputValidationError(
            "filter values must be a non-empty array; values are not echoed because "
            "errors may enter logs",
            field=f"filters[{field_name}].values",
        )
    return values


def _validate_account_filter_values(
    field_name: str, item: Mapping[str, Any]
) -> None:
    values = _filter_values(
        item,
        field_name,
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
                "account member identifier filter values must be non-empty strings or "
                "integers of at most 64 characters; values are not echoed because errors may enter logs",
                field=f"filters[{field_name}].values",
            )
        return
    if any(not isinstance(value, str) or len(value) > 256 for value in values):
        raise InputValidationError(
            "account member text filter values must be strings of at most 256 "
            "characters; values are not echoed because errors may enter logs",
            field=f"filters[{field_name}].values",
        )


def _validate_named_filter_values(
    field_name: str, item: Mapping[str, Any]
) -> None:
    values = _filter_values(
        item,
        field_name,
    )
    if field_name == "template_type":
        if any(value not in {"report", "kanban"} for value in values):
            raise InputValidationError(
                f"actual value: {actual_value(values)}; allowed values: \"kanban\", \"report\"",
                field="filters[template_type].values",
            )
    elif field_name == "name":
        if any(not isinstance(value, str) or len(value) > 256 for value in values):
            raise InputValidationError(
                "analysis name filter values must be strings of at most 256 characters; "
                "values are not echoed because errors may enter logs",
                field="filters[name].values",
            )
    elif field_name == "dashboard_id":
        if any(not isinstance(value, str) or not value for value in values):
            raise InputValidationError(
                "dashboard filter identifiers must be non-empty strings; values are "
                "not echoed because errors may enter logs",
                field="filters[dashboard_id].values",
            )
    elif field_name in {"default_to_one", "default_to_all"} and any(
        value != "1" for value in values
    ):
        raise InputValidationError(
            "dashboard default filter values must all equal \"1\"; values are not "
            "echoed because errors may enter logs",
            field=f"filters[{field_name}].values",
        )


def _validate_filtering(
    value: Mapping[str, Any], controls: set[str], operation_id: str
) -> None:
    allowed = controls | {"keyword", "search_keyword", "search_type"}
    unknown = sorted(str(key) for key in value if str(key) not in allowed)
    if unknown:
        raise InputValidationError(
            f"actual value: {actual_value(unknown)}; allowed fields: "
            f"{allowed_values(allowed, discovery_action=f'gravity insight operations describe {operation_id}')}",
            field="filtering",
        )
    if any(
        item is None or isinstance(item, (Mapping, list, tuple))
        for item in value.values()
    ):
        raise InputValidationError(
            "filtering values must be scalar and non-null; values are not echoed because "
            "errors may enter logs",
            field="filtering",
        )


def _validate_data_list(
    value: Sequence[Any], controls: set[str], operation_id: str
) -> None:
    for row in value:
        if not isinstance(row, Mapping):
            raise InputValidationError(
                f"actual value: {actual_value(type(row).__name__)}; allowed value: a controlled object",
                field="data_list[]",
            )
        row_keys = {str(key) for key in row}
        if not row_keys <= controls or any(is_sensitive_control_key(key) for key in row_keys):
            invalid = sorted(
                key
                for key in row_keys
                if key not in controls or is_sensitive_control_key(key)
            )
            raise InputValidationError(
                f"actual value: {actual_value(invalid)}; allowed fields: "
                f"{allowed_values(controls, discovery_action=f'gravity insight operations describe {operation_id}')}",
                field="data_list[]",
            )
        if any(isinstance(item, (Mapping, list, tuple)) for item in row.values()):
            raise InputValidationError(
                "data_list values must be scalars; values are not echoed because errors "
                "may enter logs",
                field="data_list[]",
            )


def _validate_order_by(
    value: Sequence[Any], controls: set[str], operation_id: str
) -> None:
    for item in value:
        field_name = order_field(item)
        if field_name is None or field_name not in controls:
            observed = (
                field_name
                if field_name is not None
                else sorted(str(key) for key in item)
                if isinstance(item, Mapping)
                else type(item).__name__
            )
            raise InputValidationError(
                f"actual value: {actual_value(observed)}; "
                f"allowed fields: {allowed_values(controls, discovery_action=f'gravity insight operations describe {operation_id}')}",
                field="order_by[]",
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
        f"actual value: {actual_value(sorted(requested))}; allowed value: dynamic fields "
        "with a registered metadata validator for this operation",
        field="dynamic_response_fields",
        next_action=f"Run `gravity insight operations describe {operation.operation_id}` and use its registered response fields.",
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
            f"actual value: {actual_value(operation.platform)}; allowed value: a registered platform context",
            field="platform",
            next_action=f"Run `gravity insight operations describe {operation.operation_id}` and select an operation with platform metadata.",
        )
    profile = promotion_metadata_inputs(operation, inputs)
    view = load_view(PROMOTION_METRIC, profile, metadata_loader)
    available = names(view.rows, keys=("name",))
    missing = sorted(unresolved - available)
    if missing:
        discovery_action = (
            f"gravity run {PROMOTION_METRIC} --input {actual_value(profile)}"
        )
        raise InputValidationError(
            f"actual value absent from live platform metadata: {actual_value(missing)}; allowed values: "
            f"{allowed_values(available, discovery_action=discovery_action)}",
            field="query_fields",
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
            "actual value: 0 metadata rows; allowed value: non-empty business metric metadata",
            field="metrics_list",
            next_action=f"Run `gravity run {REPORT_BUSINESS_METRIC} --input '{{}}'` and retry only after metadata is available.",
        )
    allowed = set(operation.response_projection.item_keys) | names(view.rows)
    missing = sorted(requested - allowed)
    if missing:
        discovery_action = f"gravity run {REPORT_BUSINESS_METRIC} --input '{{}}'"
        raise InputValidationError(
            f"actual value: {actual_value(missing)}; allowed values: "
            f"{allowed_values(allowed, discovery_action=discovery_action)}",
            field="metrics_list/dims_list",
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
                f"actual value: {actual_value(list(metrics) + list(custom_metrics))}; "
                "allowed value: metrics with complete exclusion metadata",
                field="metrics_list/custom_metrics_list",
                next_action="Run `gravity multidim metadata` and retry with a metric whose metadata is complete.",
            )
        conflicts = sorted(set(dimensions) & exclusions)
        if conflicts:
            raise InputValidationError(
                f"actual value: {actual_value(conflicts)}; allowed value: dimensions not "
                "excluded by the selected metrics",
                field="data_dims/relate_dims",
                next_action="Run `gravity multidim metadata` and remove the reported excluded dimensions.",
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
            f"actual value: {actual_value({item.operation_id: item.status for item in all_views})}; "
            "allowed metadata statuses: success, empty",
            field="data_dims/relate_dims",
            next_action="Run `gravity multidim metadata` and retry only after metadata is complete.",
        )
    rows = tuple(row for item in all_views for row in item.rows)
    known, complete = all_exclusion_dimensions(rows)
    if not complete or not requested <= known:
        missing = sorted(requested - known)
        raise InputValidationError(
            f"actual value for data_dims/relate_dims absent from complete live metadata: {actual_value(missing)}; allowed values: "
            f"{allowed_values(known, discovery_action='gravity multidim metadata')}",
            field="data_dims/relate_dims",
        )
