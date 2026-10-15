"""Compile compact Analysis specs into existing governed operation inputs.

The compiler removes frontend wire-shape knowledge from callers.  It does not
invent events, metrics, filters, or calculation semantics: those remain
explicit in the spec and are validated by the existing Analysis field policy.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ._field_policy_analysis import validate_analysis_shape
from .actionable_error_values import actual_value, allowed_values
from .analysis_spec_preview import prepare_query_spec_preview
from .analysis_execution_support import reject_unsupported_property_groups
from .analysis_spec_input import compile_dated_query, compile_metric
from .analysis_spec_schema import (
    ANALYSIS_SPEC_KINDS,
    ANALYSIS_TIME_GROUPS_BY_KIND,
    RETENTION_ADDITIVE_FOLLOWUP_GAP_CODE,
    RETENTION_ADDITIVE_FOLLOWUP_JOURNEY,
    RETENTION_ADDITIVE_FOLLOWUP_NEXT_ACTION,
    RETENTION_ADDITIVE_FOLLOWUP_REASON,
    analysis_query_spec_schema,
)
from .analysis_spec_controls import (
    validate_time_grain,
)
from .analysis_spec_validation import (
    compile_condition_values,
    bounded_string as _bounded_string,
    choice as _choice,
    list_items as _list,
    logic as _logic,
    mapping as _mapping,
    reject_keys as _reject_keys,
)
from .domains import ANALYSIS_QUERY_OPERATIONS, new_analysis_query_id
from .errors import InputValidationError, UnsupportedOperationError
from .workspace import Workspace, load_workspace


COMPILED_SCHEMA_VERSION = "gravity-insight.analysis-query-compiled.v1"
_COMMON_FIELDS = frozenset(
    {
        "app",
        "query_id",
        "group_by",
    }
)
_KIND_FIELDS = {
    "event": frozenset(
        {
            "start",
            "end",
            "date_ranges",
            "steps",
            "formulas",
            "time_grain",
            "global_filters",
            "global_logic",
            "user_filters",
            "calculate_y",
            "calculate_layer_y",
            "return_hierarchy_list",
            "page_size",
            "aggregate",
        }
    ),
    "funnel": frozenset(
        {
            "start",
            "end",
            "steps",
            "time_grain",
            "global_filters",
            "global_logic",
            "window",
            "calculate_each_day",
        }
    ),
    "retention": frozenset(
        {
            "start",
            "end",
            "steps",
            "time_grain",
            "offset",
            "period_calc_method",
            "custom_before_method",
            "total_calc_type",
            "week_first_day",
            "user_filters",
            "user_reattribute_filters",
            "user_logic",
            "property_conditions",
            "query_item_before_after",
        }
    ),
    "property": frozenset(
        {
            "property",
            "conditions",
            "order_by",
            "user_filters",
            "user_reattribute_filters",
            "user_logic",
            "property_conditions",
        }
    ),
    "scatter": frozenset({"start", "end", "steps", "time_grain", "zone"}),
}
_GROUP_SOURCES = {
    "event": "event",
    "user": "user",
    "segment": "user_segment",
}


@dataclass(frozen=True)
class CompiledAnalysisQuery:
    """One compact spec resolved to a stable operation and its exact input."""

    kind: str
    operation_id: str
    inputs: dict[str, Any]

    def plan_node(self, *, node_id: str | None = None) -> dict[str, Any]:
        selected_id = node_id or (
            f"analysis_{self.kind}_{self.inputs['query_id'][-8:].casefold()}"
        )
        item_budget = max(200, int(self.inputs.get("page_size", 0) or 0))
        return {
            "id": selected_id,
            "kind": "run",
            "request": {"selector": self.operation_id, "inputs": self.inputs},
            "limits": {"max_pages": 1, "max_items": item_budget},
        }


def compile_query_spec(
    kind: str,
    spec: Mapping[str, Any],
    *,
    workspace: Workspace | str | None = None,
    app: str | int | None = None,
    start: str | None = None,
    end: str | None = None,
) -> CompiledAnalysisQuery:
    """Compile a compact Analysis spec without constructing a network client."""

    selected_kind = _normalize_kind(kind)
    _validate_date_overrides(selected_kind, start, end)
    values = _mapping(spec, "spec")
    _reject_unknown_fields(selected_kind, values)
    if selected_kind != "property":
        validate_time_grain(
            selected_kind,
            values.get("time_grain"),
            ANALYSIS_TIME_GROUPS_BY_KIND[selected_kind],
        )
    selected_workspace = _workspace(workspace)
    app_id = _resolve_app(selected_workspace, app if app is not None else values.get("app"))
    query_id = _bounded_string(values.get("query_id") or new_analysis_query_id(), "query_id")
    inputs: dict[str, Any] = {"query_id": query_id, "app_id": str(app_id)}
    if selected_kind == "property":
        reject_unsupported_property_groups(values.get("group_by", ()), field_root="group_by")
    inputs["group_by_list"] = _group_by(values)
    if selected_kind == "property":
        _compile_property(values, inputs)
    else:
        compile_dated_query(
            selected_kind,
            values,
            inputs,
            start=start,
            end=end,
        )
    _copy_shared_controls(values, inputs)
    compiled = CompiledAnalysisQuery(
        kind=selected_kind,
        operation_id=ANALYSIS_QUERY_OPERATIONS[selected_kind],
        inputs=compile_condition_values(inputs),
    )
    validate_analysis_shape(compiled.kind, compiled.inputs)
    return compiled


def prepare_query_spec(
    client: Any,
    kind: str,
    spec: Mapping[str, Any],
    **options: Any,
) -> dict[str, Any]:
    """Compile, validate, and return a caller-safe offline preview."""

    return prepare_query_spec_preview(
        client,
        kind,
        spec,
        validate_query_spec=validate_query_spec,
        schema_version=COMPILED_SCHEMA_VERSION,
        gap_error_type=UnsupportedOperationError,
        gap_code=RETENTION_ADDITIVE_FOLLOWUP_GAP_CODE,
        gap_journey=RETENTION_ADDITIVE_FOLLOWUP_JOURNEY,
        gap_reason=RETENTION_ADDITIVE_FOLLOWUP_REASON,
        gap_next_action=RETENTION_ADDITIVE_FOLLOWUP_NEXT_ACTION,
        gap_operation_id=ANALYSIS_QUERY_OPERATIONS["retention"],
        **options,
    )


def validate_query_spec(
    client: Any,
    kind: str,
    spec: Mapping[str, Any],
    **options: Any,
) -> tuple[CompiledAnalysisQuery, Mapping[str, Any]]:
    """Return exact executable input after the existing offline validator passes."""

    compiled = compile_query_spec(kind, spec, **options)
    validation = client.validate(compiled.operation_id, compiled.inputs)
    if not validation.get("ok"):
        error = validation.get("error") if isinstance(validation, Mapping) else None
        details = error if isinstance(error, Mapping) else {}
        raise InputValidationError(
            f"actual value: {actual_value(spec)}; " + (str(details.get("message") or "compiled Analysis query is invalid")),
            field=str(details.get("field") or "spec"),
            next_action=str(
                details.get("next_action")
                or "Correct the Analysis spec and retry the same command."
            ),
        )
    return compiled, validation


def _compile_property(spec: Mapping[str, Any], inputs: dict[str, Any]) -> None:
    target = compile_metric(spec.get("property"), "property", require_data_type=True)
    label = str(target.pop("label", ""))
    conditions = _list(spec.get("conditions", []), "conditions", 100)
    inputs["query_item"] = {
        "target": target,
        "conditions": conditions,
        "custom_name": label,
    }
    inputs["order_by_list"] = _property_order(spec.get("order_by", []))


def _property_order(value: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for index, raw in enumerate(_list(value, "order_by", 20)):
        field = f"order_by[{index}]"
        item = _mapping(raw, field)
        _reject_keys(item, {"field", "sort", "data_type"}, field)
        direction = item.get("sort")
        if direction not in {0, 1, -1, "asc", "desc", "ASC", "DESC"}:
            raise InputValidationError(
                f"actual value: {actual_value(direction)}; allowed values: "
                f"{allowed_values({0, 1, -1, 'asc', 'desc', 'ASC', 'DESC'})}",
                field=f"{field}.sort",
            )
        normalized: dict[str, Any] = {
            "field": _bounded_string(item.get("field"), f"{field}.field"),
            "sort": direction,
        }
        if "data_type" in item:
            normalized["data_type"] = _choice(
                item["data_type"], {"STRING", "INT", "FLOAT", "BOOL", "DATE", "DATETIME", "LIST"}, f"{field}.data_type"
            )
        result.append(normalized)
    return result


def _copy_shared_controls(spec: Mapping[str, Any], inputs: dict[str, Any]) -> None:
    if "user_filters" in spec:
        inputs["user_filtering"] = dict(_mapping(spec["user_filters"], "user_filters"))
    if "user_reattribute_filters" in spec:
        inputs["user_re_attribute_filtering"] = dict(
            _mapping(spec["user_reattribute_filters"], "user_reattribute_filters")
        )
    if "user_logic" in spec:
        inputs["user_cond_logic"] = _logic(spec["user_logic"], "user_logic")
    if "property_conditions" in spec:
        inputs["property_condition"] = _list(
            spec["property_conditions"], "property_conditions", 100
        )


def _group_by(spec: Mapping[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    grain = spec.get("time_grain")
    if grain is not None:
        result.append(
            {
                "type": "default_event",
                "field": "create_time",
                "group_by": _bounded_string(grain, "time_grain"),
            }
        )
    for index, raw in enumerate(_list(spec.get("group_by", []), "group_by", 20)):
        item = _mapping(raw, f"group_by[{index}]")
        allowed = {
            "field",
            "source",
            "bucket",
            "bucket_values",
            "segment_type",
            "version_id",
            "dimension_table",
        }
        _reject_keys(item, allowed, f"group_by[{index}]")
        field = _bounded_string(item.get("field"), f"group_by[{index}].field")
        source = _bounded_string(item.get("source"), f"group_by[{index}].source")
        if source not in _GROUP_SOURCES:
            raise InputValidationError(
                f"actual value: {actual_value(source)}; allowed values: "
                f"{allowed_values(_GROUP_SOURCES)}",
                field=f"group_by[{index}].source",
            )
        group = {"type": _GROUP_SOURCES[source], "field": field, "group_by": field}
        for source_key, target_key in (
            ("bucket", "operator"),
            ("bucket_values", "values"),
            ("segment_type", "segment_type"),
            ("version_id", "version_id"),
            ("dimension_table", "dim_using_table_name"),
        ):
            if source_key in item:
                group[target_key] = item[source_key]
        result.append(group)
    return result


def _workspace(value: Workspace | str | None) -> Workspace:
    return value if isinstance(value, Workspace) else load_workspace(value)


def _resolve_app(workspace: Workspace, value: Any) -> int:
    try:
        return workspace.resolve_app(value)
    except ValueError:
        raise InputValidationError(
            f"actual value: {actual_value(value)}; allowed alternatives: a configured "
            "workspace App name or positive id; run `gravity run app.list` to discover Apps",
            field="app",
        ) from None


def _normalize_kind(value: Any) -> str:
    selected = str(value or "").strip().casefold()
    if selected not in ANALYSIS_SPEC_KINDS:
        raise InputValidationError(
            f"actual value: {actual_value(value)}; allowed values: "
            f"{allowed_values(ANALYSIS_SPEC_KINDS)}",
            field="kind",
        )
    return selected


def _validate_date_overrides(
    kind: str, start: str | None, end: str | None
) -> None:
    if (start is None) != (end is None):
        raise InputValidationError(
            f"actual value: {actual_value({'start': start, 'end': end})}; allowed "
            "alternatives: provide both overrides or remove both",
            field="start/end",
        )
    if kind == "property" and start is not None:
        raise InputValidationError(
            f"actual value: {actual_value({'start': start, 'end': end})}; allowed "
            "alternative: remove both overrides for property analysis",
            field="start/end",
        )


def _reject_unknown_fields(kind: str, value: Mapping[str, Any]) -> None:
    _reject_keys(value, _COMMON_FIELDS | _KIND_FIELDS[kind], "spec")
