"""Fail-closed nested validation for registered mutation inputs."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import Any

from ._field_policy_analysis import validate_analysis_shape
from ._field_policy_segment import validate_analysis_segment_rule_shape
from .actionable_error_values import actual_value
from .errors import InputValidationError
from .segment_mutation_contracts import (
    FROM_ANALYSIS_CREATE,
    FROM_RULE_CREATE,
    FROM_RULE_UPDATE,
    MANUAL_UPDATE,
    SAVE,
)
from .kanban_wire_validation import validate_kanban_wire
from .kanban_mutation_contracts import KANBAN_MUTATION_OPERATIONS
from .custom_metric_contracts import CUSTOM_METRIC_MUTATIONS
from .custom_metric_wire import validate_custom_metric_wire
from .metadata_template_contracts import TEMPLATE_MUTATIONS
from .metadata_template_wire import validate_metadata_template_wire


def validate_mutation_inputs(
    operation_id: str, values: Mapping[str, Any]
) -> None:
    """Validate nested request fields that the flat manifest schema cannot express."""

    if operation_id in KANBAN_MUTATION_OPERATIONS:
        validate_kanban_wire(operation_id, values)
        return
    if operation_id in CUSTOM_METRIC_MUTATIONS:
        validate_custom_metric_wire(operation_id, values)
        return
    if operation_id in TEMPLATE_MUTATIONS:
        validate_metadata_template_wire(operation_id, values)
        return

    if operation_id == FROM_ANALYSIS_CREATE:
        _from_analysis(values)
    elif operation_id == FROM_RULE_CREATE:
        validate_analysis_segment_rule_shape(values)
    elif operation_id == FROM_RULE_UPDATE:
        rule = {
            key: value
            for key, value in values.items()
            if key not in {"segment_id", "to_update_latest_result"}
        }
        validate_analysis_segment_rule_shape(rule)
        _identifier(values.get("segment_id"), "segment_id")
    elif operation_id == SAVE:
        _save(values)
    else:
        _simple_identifiers(operation_id, values)


def _from_analysis(values: Mapping[str, Any]) -> None:
    analysis_fields = {
        "query_id",
        "app_id",
        "query_item_list",
        "stat_time_window",
        "group_by_list",
        "global_conditions",
        "global_cond_logic",
        "date_list",
        "to_calc_each_day",
    }
    analysis = {key: values[key] for key in analysis_fields}
    validate_analysis_shape("funnel", analysis)
    if values.get("group_by_list") != []:
        raise InputValidationError(
            f"actual value: {actual_value(values.get('group_by_list'))}; allowed value: an empty group_by_list for from_analysis v1",
            field="group_by_list",
            next_action="Remove group_by from the funnel spec, dry-run again, then explicitly execute the create.",
        )
    dates = values.get("date_list")
    first = dates[0] if isinstance(dates, list) and dates else None
    if not isinstance(first, Mapping):
        raise InputValidationError(
            f"actual value: {actual_value(first)}; allowed value: one funnel date range object",
            field="date_list",
        )
    expected = {
        "fixed_date": [
            _compact_date(first.get("start_date")),
            _compact_date(first.get("end_date")),
        ]
    }
    if values.get("date_list_v2") != expected:
        raise InputValidationError(
            f"actual value: {actual_value(values.get('date_list_v2'))}; allowed value: {actual_value(expected)} derived from date_list",
            field="date_list_v2",
            next_action="Regenerate the request through `gravity analysis segment create-from-analysis --dry-run`; do not hand-edit the wire body.",
        )
    conf = values.get("segment_conf")
    required = {"segment_subject", "segment_name", "remark", "step", "is_loss"}
    if not isinstance(conf, Mapping) or set(conf) != required:
        raise InputValidationError(
            f"actual value: {actual_value(sorted(conf) if isinstance(conf, Mapping) else conf)}; allowed fields: {actual_value(sorted(required))}",
            field="segment_conf",
        )
    if conf.get("segment_subject") != "analysis_funnel":
        raise InputValidationError(
            f"actual value: {actual_value(conf.get('segment_subject'))}; allowed value: analysis_funnel",
            field="segment_conf.segment_subject",
        )
    _name(conf.get("segment_name"), "segment_conf.segment_name")
    _remark(conf.get("remark"), "segment_conf.remark")
    step = conf.get("step")
    if type(step) is not int or not 0 <= step < len(analysis["query_item_list"]):
        raise InputValidationError(
            f"actual value: {actual_value(step)}; allowed range: 0 through {len(analysis['query_item_list']) - 1}",
            field="segment_conf.step",
        )
    if type(conf.get("is_loss")) is not bool:
        raise InputValidationError(
            f"actual value: {actual_value(conf.get('is_loss'))}; allowed values: true or false",
            field="segment_conf.is_loss",
        )


def _save(values: Mapping[str, Any]) -> None:
    _identifier(values.get("segment_id"), "segment_id")
    _name(values.get("segment_name"), "segment_name")
    _remark(values.get("segment_remark"), "segment_remark")
    if values.get("action") not in {"UPDATE_NAME", "DEL"}:
        raise InputValidationError(
            f"actual value: {actual_value(values.get('action'))}; allowed values: UPDATE_NAME or DEL",
            field="action",
        )


def _simple_identifiers(
    operation_id: str, values: Mapping[str, Any]
) -> None:
    for field in ("segment_id", "version_id", "from_tmp_segment_id", "app_id"):
        if field in values:
            _identifier(values[field], field)
    for field in ("segment_name",):
        if field in values:
            _name(values[field], field)
    for field in ("segment_remark",):
        if field in values:
            _remark(values[field], field)
    if operation_id == MANUAL_UPDATE and set(values) != {
        "segment_id"
    }:
        raise InputValidationError(
            f"actual value: {actual_value(sorted(values))}; allowed fields: segment_id only",
            field="input",
        )


def _compact_date(value: Any) -> int:
    try:
        return int(date.fromisoformat(str(value)).strftime("%Y%m%d"))
    except (TypeError, ValueError):
        raise InputValidationError(
            f"actual value: {actual_value(value)}; allowed format: YYYY-MM-DD",
            field="date_list",
        ) from None


def _identifier(value: Any, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value.isascii()
        or not value.isdecimal()
        or int(value) < 1
        or len(value) > 64
    ):
        raise InputValidationError(
            f"actual value: {actual_value(value)}; allowed value: a positive decimal identifier of at most 64 characters",
            field=field,
        )
    return value


def _name(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 20:
        raise InputValidationError(
            f"actual value: {actual_value(value)}; allowed range: a non-empty segment name of at most 20 characters",
            field=field,
            next_action="Shorten the segment name to at most 20 characters, dry-run again, then explicitly execute the write.",
        )
    return value


def _remark(value: Any, field: str) -> str:
    if not isinstance(value, str) or len(value) > 2_000:
        raise InputValidationError(
            f"actual value: {actual_value(value)}; allowed value: a string of at most 2000 characters",
            field=field,
        )
    return value


__all__ = ["validate_mutation_inputs"]
