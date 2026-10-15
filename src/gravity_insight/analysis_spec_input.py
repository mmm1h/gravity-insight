"""Compile dated compact Analysis specs into governed operation inputs."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import Any

from ._field_policy_shared import ANALYSIS_FORMULA_RE
from .actionable_error_values import actual_value
from .analysis_execution_support import is_analysis_time_group
from .analysis_spec_controls import (
    apply_scatter_zone,
    funnel_window,
    retention_controls,
)
from .analysis_spec_validation import (
    boolean as _boolean,
    bounded_string as _bounded_string,
    choice as _choice,
    compile_event_quantile,
    integer_range as _integer_range,
    list_items as _list,
    logic as _logic,
    mapping as _mapping,
    optional_string as _optional_string,
    reject_keys as _reject_keys,
)
from .errors import InputValidationError


def compile_dated_query(
    kind: str,
    spec: Mapping[str, Any],
    inputs: dict[str, Any],
    *,
    start: str | None,
    end: str | None,
) -> None:
    selected_start = start if start is not None else spec.get("start")
    selected_end = end if end is not None else spec.get("end")
    inputs["date_list"] = _date_ranges(
        kind,
        spec,
        selected_start=selected_start,
        selected_end=selected_end,
        overrides_supplied=start is not None,
    )
    formulas = _event_formulas(spec.get("formulas", ())) if kind == "event" else []
    steps = _steps(
        spec.get("steps", ()),
        kind,
        minimum=0 if kind == "event" and formulas else None,
    )
    inputs["query_item_list"] = [
        _event_step(item, index=index, kind=kind)
        for index, item in enumerate(steps)
    ]
    if formulas:
        inputs["custom_query_item_list"] = formulas
    if kind in {"event", "funnel"}:
        inputs["global_conditions"] = _list(
            spec.get("global_filters", []), "global_filters", 100
        )
        inputs["global_cond_logic"] = _logic(
            spec.get("global_logic", "AND"), "global_logic"
        )
    if kind == "event":
        _compile_event_controls(spec, inputs)
    elif kind == "funnel":
        _compile_funnel_controls(spec, inputs)
    elif kind == "retention":
        _compile_retention_controls(spec, inputs)
    elif kind == "scatter":
        apply_scatter_zone(inputs["query_item_list"][0], spec.get("zone"))
        inputs["extra_data"] = {"client_server_time": "CLIENT"}


def compile_metric(
    value: Any, field: str, *, require_data_type: bool = False
) -> dict[str, Any]:
    item = _mapping(value, field)
    allowed = {"field", "aggregation", "dimension_table"}
    allowed |= {"label", "data_type", "source"} if require_data_type else {"quantile"}
    _reject_keys(item, allowed, field)
    metric_field = _bounded_string(item.get("field"), f"{field}.field")
    aggregation = _bounded_string(item.get("aggregation"), f"{field}.aggregation")
    result = {"field": metric_field, "name": aggregation}
    if "label" in item:
        result["label"] = _optional_string(item["label"], f"{field}.label", "")
        result["cname"] = result["label"]
    if require_data_type:
        result["data_type"] = _bounded_string(item.get("data_type"), f"{field}.data_type")
        result.setdefault("cname", "")
        if "source" in item:
            result["type"] = _bounded_string(item["source"], f"{field}.source")
    elif "quantile" in item:
        quantile = item["quantile"]
        if not isinstance(quantile, (int, float)) or isinstance(quantile, bool):
            raise InputValidationError(
                f"actual value: {actual_value(quantile)}; allowed type: number",
                field=f"{field}.quantile",
            )
        result["quantile_level"] = quantile
    if "dimension_table" in item:
        result["dim_using_table_name"] = _bounded_string(
            item["dimension_table"], f"{field}.dimension_table"
        )
    return result


def _compile_event_controls(
    spec: Mapping[str, Any], inputs: dict[str, Any]
) -> None:
    if "calculate_y" in spec:
        inputs["calc_y"] = _boolean(spec["calculate_y"], "calculate_y")
    inputs["calc_layer_y"] = _boolean(
        spec.get("calculate_layer_y", False), "calculate_layer_y"
    )
    if "return_hierarchy_list" in spec:
        inputs["return_hierarchy_list"] = _boolean(
            spec["return_hierarchy_list"], "return_hierarchy_list"
        )
    if "aggregate" in spec:
        inputs["aggregate_config"] = dict(_mapping(spec["aggregate"], "aggregate"))
    if "page_size" in spec:
        inputs["page_size"] = _integer_range(spec["page_size"], 1, 10_000, "page_size")
    inputs["extra_data"] = {"client_server_time": "CLIENT"}


def _compile_funnel_controls(
    spec: Mapping[str, Any], inputs: dict[str, Any]
) -> None:
    inputs["stat_time_window"] = funnel_window(spec.get("window"))
    inputs["to_calc_each_day"] = _boolean(
        spec.get("calculate_each_day", False), "calculate_each_day"
    )


def _compile_retention_controls(
    spec: Mapping[str, Any], inputs: dict[str, Any]
) -> None:
    inputs.update(retention_controls(spec))
    if spec.get("time_grain") is None and not any(
        is_analysis_time_group(item) for item in inputs.get("group_by_list", ())
    ):
        inputs["group_by_list"] = [
            {
                "type": "default_event",
                "field": "create_time",
                "group_by": "day",
            },
            *inputs.get("group_by_list", ()),
        ]


def _event_step(value: Mapping[str, Any], *, index: int, kind: str) -> dict[str, Any]:
    item = _mapping(value, f"steps[{index}]")
    allowed = {"event", "metric", "label", "conditions", "condition_logic"}
    _reject_keys(item, allowed, f"steps[{index}]")
    event = _bounded_string(item.get("event"), f"steps[{index}].event")
    metric = compile_metric(item.get("metric"), f"steps[{index}].metric")
    if kind == "event":
        compile_event_quantile(metric, f"steps[{index}].metric")
    label = _optional_string(item.get("label"), f"steps[{index}].label", event)
    step = {
        "event_name": event,
        "event_label": label,
        "custom_name": label,
        "target": metric,
        "conditions": _list(
            item.get("conditions", []), f"steps[{index}].conditions", 100
        ),
        "cond_logic": _logic(
            item.get("condition_logic", "AND"), f"steps[{index}].condition_logic"
        ),
        "event_index": index,
    }
    if kind == "scatter":
        step["prop_to_calc"] = metric["field"]
        step["prop_to_calc_sub"] = (
            "" if metric["name"] == metric["field"] else metric["name"]
        )
    return step


def _event_formulas(value: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for index, raw in enumerate(_list(value, "formulas", 100)):
        field = f"formulas[{index}]"
        item = _mapping(raw, field)
        _reject_keys(item, {"name", "formula", "steps", "precision"}, field)
        name = _bounded_string(item.get("name"), f"{field}.name")
        if len(name) > 200:
            raise InputValidationError(
                f"actual value: {actual_value(name)}; formula name must contain at "
                "most 200 characters",
                field=f"{field}.name",
            )
        formula = item.get("formula")
        if not isinstance(formula, str) or ANALYSIS_FORMULA_RE.fullmatch(formula) is None:
            raise InputValidationError(
                f"actual value: {actual_value(formula)}; formula must contain 1 through "
                "1000 characters using x placeholders, digits, whitespace, and + - * / ( ) .",
                field=f"{field}.formula",
            )
        nested = _steps(item.get("steps", ()), "event")
        result.append(
            {
                "custom_name": name,
                "formula": formula,
                "query_item_list": [
                    _event_step(step, index=step_index, kind="event")
                    for step_index, step in enumerate(nested)
                ],
                "decimal_point": _choice(
                    item.get("precision", "two_point"),
                    {"two_point", "three_point", "four_point"},
                    f"{field}.precision",
                ),
                "event_index": index,
            }
        )
    return result


def _steps(
    value: Any, kind: str, *, minimum: int | None = None
) -> list[Mapping[str, Any]]:
    maximum = (
        2
        if kind == "retention"
        else (1 if kind == "scatter" else (20 if kind == "funnel" else 100))
    )
    items = _list(value, "steps", maximum)
    selected_minimum = (
        minimum
        if minimum is not None
        else (2 if kind in {"funnel", "retention"} else 1)
    )
    if not selected_minimum <= len(items) <= maximum:
        qualifier = (
            "exactly 2"
            if selected_minimum == maximum
            else f"{selected_minimum} through {maximum}"
        )
        raise InputValidationError(
            f"actual value: {len(items)} items; allowed count: {qualifier} items",
            field="steps",
        )
    return [_mapping(item, f"steps[{index}]") for index, item in enumerate(items)]


def _date_ranges(
    kind: str,
    spec: Mapping[str, Any],
    *,
    selected_start: Any,
    selected_end: Any,
    overrides_supplied: bool,
) -> list[dict[str, str]]:
    ranges = spec.get("date_ranges")
    if ranges is None:
        return [_date_range(selected_start, selected_end)]
    if (
        kind != "event"
        or overrides_supplied
        or spec.get("start") is not None
        or spec.get("end") is not None
    ):
        raise InputValidationError(
            "actual value: conflicting date owners; event date_ranges cannot be "
            "combined with start/end or date overrides",
            field="date_ranges",
            next_action="Use either date_ranges or one start/end pair, not both.",
        )
    result: list[dict[str, str]] = []
    for index, raw in enumerate(_list(ranges, "date_ranges", 10)):
        field = f"date_ranges[{index}]"
        item = _mapping(raw, field)
        _reject_keys(item, {"start", "end"}, field)
        result.append(_date_range(item.get("start"), item.get("end")))
    if not result:
        raise InputValidationError(
            "actual value: 0 items; date_ranges requires 1 through 10 windows",
            field="date_ranges",
        )
    return result


def _date_range(start: Any, end: Any) -> dict[str, str]:
    if not isinstance(start, str) or not isinstance(end, str):
        _invalid_date_range(start, end)
    try:
        start_date, end_date = date.fromisoformat(start), date.fromisoformat(end)
    except ValueError:
        _invalid_date_range(start, end)
    if start_date > end_date or (end_date - start_date).days > 90:
        raise InputValidationError(
            f"actual value: {actual_value({'start': start, 'end': end})}; allowed "
            "range: ordered ISO dates spanning no more than 90 days",
            field="start/end",
        )
    return {"start_date": start, "end_date": end}


def _invalid_date_range(start: Any, end: Any) -> None:
    raise InputValidationError(
        f"actual value: {actual_value({'start': start, 'end': end})}; allowed "
        "format: ISO dates for both fields",
        field="start/end",
        next_action=(
            "Set spec.start and spec.end to inclusive YYYY-MM-DD, or pass "
            "paired `--start/--end` (ISO or a closed relative phrase such as "
            "`last 7 days`)."
        ),
    )


__all__ = ["compile_dated_query", "compile_metric"]
