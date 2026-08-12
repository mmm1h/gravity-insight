"""Strict compilation of persisted Dashboard chart artifacts.

Gravity Dashboard stores chart configuration in the Web representation.  This
module implements only the five request constructions proven by the bundled
frontend census.  It deliberately rejects unknown containers instead of
guessing that a Web-only setting is safe to omit.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .dashboard_artifact_contract import BODY_FIELDS, SUBJECT_KINDS, UI_FIELDS
from .domains import ANALYSIS_QUERY_OPERATIONS, new_analysis_query_id
from .errors import InputValidationError, UnsupportedOperationError


MAX_CONFIG_BYTES = 1_048_576
MAX_ANALYSIS_DAYS = 90
@dataclass(frozen=True)
class CompiledDashboardChart:
    """One Dashboard artifact compiled to an exact stable Analysis request."""

    report_id: str
    name: str
    subject: str
    kind: str
    operation_id: str
    inputs: dict[str, Any]
    validation_status: str
    date_override_applied: bool
    limitations: tuple[str, ...] = ()

    def safe_summary(self) -> dict[str, Any]:
        """Return chart identity and eligibility without configuration values."""

        return {
            "report_id": self.report_id,
            "name": self.name,
            "subject": self.subject,
            "kind": self.kind,
            "operation_id": self.operation_id,
            "supported": True,
            "validation_status": self.validation_status,
            "date_override_applied": self.date_override_applied,
            "limitations": list(self.limitations),
        }


def compile_dashboard_chart(
    client: Any,
    report: Mapping[str, Any],
    *,
    app_id: str | int,
    start: str,
    end: str,
) -> CompiledDashboardChart:
    """Compile one persisted chart and run the existing offline FieldPolicy."""

    item = _mapping(report, "report")
    report_id = _text(item.get("report_id"), "report.report_id", maximum=256)
    name = _text(item.get("name"), "report.name", maximum=512)
    subject = _text(item.get("subject"), "report.subject", maximum=64)
    kind = SUBJECT_KINDS.get(subject)
    if kind is None:
        raise UnsupportedOperationError(
            "dashboard chart subject is not supported by strict replay",
            field="report.subject",
            next_action="Keep this chart unsupported until its query contract is proven.",
        )
    selected_app = _app_id(app_id)
    validate_dashboard_window(start, end)
    config = _config(item.get("config"))
    _reject_unknown(config, UI_FIELDS[kind], "report.config")
    _validate_ui_config(kind, config)
    body = _mapping(config.get("calculateBody"), "report.config.calculateBody")
    _reject_unknown(body, BODY_FIELDS[kind], "report.config.calculateBody")
    inputs, applied, limitations = _compile_inputs(
        kind,
        config,
        body,
        app_id=selected_app,
        start=start,
        end=end,
    )
    operation_id = ANALYSIS_QUERY_OPERATIONS[kind]
    validation = client.validate(operation_id, inputs)
    if not isinstance(validation, Mapping) or validation.get("ok") is not True:
        raise UnsupportedOperationError(
            "dashboard chart cannot be validated against the stable Analysis contract",
            field="report.config",
            next_action="Keep this chart unsupported; do not translate or retry its Web config.",
        )
    return CompiledDashboardChart(
        report_id=report_id,
        name=name,
        subject=subject,
        kind=kind,
        operation_id=operation_id,
        inputs=inputs,
        validation_status=_validation_status(validation.get("status")),
        date_override_applied=applied,
        limitations=limitations,
    )


def validate_dashboard_window(start: str, end: str) -> None:
    """Validate the shared inclusive Dashboard window without client access."""

    _date_window(start, end)


def _compile_inputs(
    kind: str,
    config: Mapping[str, Any],
    body: Mapping[str, Any],
    *,
    app_id: str,
    start: str,
    end: str,
) -> tuple[dict[str, Any], bool, tuple[str, ...]]:
    if kind == "event":
        return _event_inputs(config, body, app_id, start, end), True, (
            "dashboard conditions are not applied by the stable event contract",
        )
    if kind == "property":
        return _property_inputs(body, app_id), False, (
            "property analysis has no date window in its stable contract",
            "dashboard conditions are not applied",
        )
    if kind == "retention":
        return _retention_inputs(config, body, app_id, start, end), True, (
            "dashboard conditions are not applied by the stable retention contract",
        )
    if kind == "funnel":
        return _funnel_inputs(config, body, app_id, start, end), True, (
            "dashboard conditions are not applied by the stable funnel contract",
        )
    return _scatter_inputs(config, body, app_id, start, end), True, (
        "dashboard conditions are not applied by the stable scatter contract",
    )


def _event_inputs(
    config: Mapping[str, Any],
    body: Mapping[str, Any],
    app_id: str,
    start: str,
    end: str,
) -> dict[str, Any]:
    if body.get("user_filtering") not in (None, [], {}):
        _unsupported("event user_filtering is not registered", "calculateBody.user_filtering")
    groups = _objects(body.get("group_by_list", []), "calculateBody.group_by_list")
    grain = _ui_object(
        config.get("groupByCreateTime", {}),
        "report.config.groupByCreateTime",
    ).get("value")
    if any(item.get("field") == "create_time" for item in groups) and grain is None:
        _unsupported(
            "event groupByCreateTime.value is required for create_time grouping",
            "report.config.groupByCreateTime.value",
        )
    if grain is not None:
        groups = [_event_time_group(item, grain) for item in groups]
    return {
        "query_id": new_analysis_query_id(),
        "app_id": app_id,
        "query_item_list": copy.deepcopy(body.get("query_item_list")),
        "custom_query_item_list": copy.deepcopy(body.get("custom_query_item_list", [])),
        "group_by_list": groups,
        "global_conditions": copy.deepcopy(body.get("global_conditions", [])),
        "global_cond_logic": body.get("global_cond_logic", "AND"),
        "split_event": copy.deepcopy(body.get("split_event", {})),
        "date_list": [_date_item(start, end)],
        "return_hierarchy_list": config.get("tableShowType") == "level",
        "calc_layer_y": True,
        "aggregate_config": copy.deepcopy(config.get("aggregate_config", {})),
        "extra_data": copy.deepcopy(body.get("extra_data", {})),
    }


def _property_inputs(body: Mapping[str, Any], app_id: str) -> dict[str, Any]:
    return {
        "query_id": new_analysis_query_id(),
        "app_id": app_id,
        **copy.deepcopy(dict(body)),
    }


def _retention_inputs(
    config: Mapping[str, Any],
    body: Mapping[str, Any],
    app_id: str,
    start: str,
    end: str,
) -> dict[str, Any]:
    reattribute = body.get("user_re_attribute_filtering")
    if reattribute not in (None, [], {}):
        _unsupported(
            "retention user_re_attribute_filtering is not sent by Dashboard Web",
            "calculateBody.user_re_attribute_filtering",
        )
    groups = _objects(body.get("group_by_list", []), "calculateBody.group_by_list")
    cascade = _sequence(config.get("cascaderValue", ["day", 7]), "report.config.cascaderValue")
    if len(cascade) != 2:
        _unsupported("retention cascaderValue must contain grain and offset", "report.config.cascaderValue")
    grain, offset_selector = cascade
    if not isinstance(grain, str) or not grain:
        _unsupported("retention grain is invalid", "report.config.cascaderValue")
    offset = config.get("cascaderInput", 7) if offset_selector == "custom" else offset_selector
    if isinstance(offset, bool) or not isinstance(offset, int):
        _unsupported("retention offset is invalid", "report.config.cascaderValue")
    groups.append({"type": "default_event", "field": "create_time", "group_by": cascade[0]})
    total = config.get("total_calc_type", "total_week")
    if not isinstance(total, str) or total not in {"total_week", "total_month"}:
        _unsupported("retention total_calc_type is invalid", "report.config.total_calc_type")
    total_enabled = config.get("is_total_calc", False)
    if not isinstance(total_enabled, bool):
        _unsupported("retention is_total_calc must be boolean", "report.config.is_total_calc")
    total_calc_type = "DAY"
    if total_enabled:
        total_calc_type = {"total_week": "WEEK", "total_month": "MONTH"}.get(total, "DAY")
    inputs = copy.deepcopy(dict(body))
    inputs.pop("user_re_attribute_filtering", None)
    inputs.update(
        {
            "query_id": new_analysis_query_id(),
            "app_id": app_id,
            "group_by_list": groups,
            "date_list": [_date_item(start, end)],
            "offset": offset,
            "week_first_day": config.get("week_first_day", 1),
            "total_calc_type": total_calc_type,
        }
    )
    return inputs


def _funnel_inputs(
    config: Mapping[str, Any],
    body: Mapping[str, Any],
    app_id: str,
    start: str,
    end: str,
) -> dict[str, Any]:
    series_type = config.get("seriesType")
    if not isinstance(series_type, str):
        _unsupported("funnel seriesType must be text", "report.config.seriesType")
    normalized_series = {
        "bar": "funnel_bar",
        "line": "funnel_line",
    }.get(series_type, series_type)
    inputs = copy.deepcopy(dict(body))
    inputs.update(
        {
            "query_id": new_analysis_query_id(),
            "app_id": app_id,
            "date_list": [_date_item(start, end)],
            "to_calc_each_day": normalized_series in {"funnel_line", "line_table"},
        }
    )
    return inputs


def _scatter_inputs(
    config: Mapping[str, Any],
    body: Mapping[str, Any],
    app_id: str,
    start: str,
    end: str,
) -> dict[str, Any]:
    groups = _objects(body.get("group_by_list", []), "calculateBody.group_by_list")
    if not groups or groups[-1].get("field") != "create_time":
        _unsupported("scatter config is missing its trailing create_time group", "calculateBody.group_by_list")
    series_type = config.get("seriesType")
    if not isinstance(series_type, str):
        _unsupported("scatter seriesType must be text", "report.config.seriesType")
    grain = _ui_object(
        config.get("groupByCreateTime"),
        "report.config.groupByCreateTime",
    ).get("value")
    if not isinstance(grain, str) or not grain:
        _unsupported("scatter groupByCreateTime.value is required", "report.config.groupByCreateTime.value")
    effective_grain = "total" if series_type == "scatter_bar" else grain
    groups[-1] = {
        "type": "default_event",
        "field": "create_time",
        "group_by": "day" if effective_grain == "total" else effective_grain,
    }
    inputs = copy.deepcopy(dict(body))
    inputs.update(
        {
            "query_id": new_analysis_query_id(),
            "app_id": app_id,
            "group_by_list": groups,
            "date_list": [_date_item(start, end)],
        }
    )
    return inputs


def _event_time_group(item: Mapping[str, Any], grain: Any) -> dict[str, Any]:
    result = copy.deepcopy(dict(item))
    if result.get("field") != "create_time":
        return result
    if isinstance(grain, bool) or not isinstance(grain, (str, int)):
        _unsupported("event groupByCreateTime.value is invalid", "report.config.groupByCreateTime.value")
    if grain in {1, 5, 10}:
        result.update({"group_by": "minute", "granularity": grain})
    elif isinstance(grain, str) and grain:
        result["group_by"] = grain
        result.pop("granularity", None)
    else:
        _unsupported("event groupByCreateTime.value is invalid", "report.config.groupByCreateTime.value")
    return result


def _validate_ui_config(kind: str, config: Mapping[str, Any]) -> None:
    """Validate proven UI-only containers before intentionally not executing them."""

    if kind == "event":
        if config.get("compareList") not in (None, []):
            _unsupported(
                "event comparison windows cannot be represented by one explicit date pair",
                "report.config.compareList",
            )
        _optional_object(config, "groupByCreateTime")
        _optional_object(config, "aggregate_config", fields=None)
        _optional_date_list(config, "date_list")
        for field in ("groupBy", "queryItemList", "customQueryItemList"):
            _optional_array(config, field)
        for field in ("cascaderValue", "checkIndexList", "customSortData"):
            _optional_array(config, field)
    elif kind == "property":
        _optional_array(config, "groupBy")
        _optional_array(config, "customSortData")
        _optional_object(config, "queryItem", fields=None)
    elif kind == "retention":
        _optional_array(config, "queryItemList")
        _optional_array(config, "group_by_list")
        _optional_array(config, "groupBy")
        _optional_array(config, "checkIndexList")
        _optional_array(config, "customSortData")
        _optional_array(config, "cascaderValue")
        _optional_array(config, "compareList")
        _optional_object(config, "groupByCreateTime")
        _optional_date_list(config, "date_list")
    elif kind == "funnel":
        for field in (
            "cascaderValue", "checkIndexList", "compareList", "groupBy",
            "queryItemList", "selectedSteps",
        ):
            _optional_array(config, field)
        _optional_object(config, "groupByCreateTime")
        _optional_date_list(config, "date_list")
    else:
        _optional_object(config, "groupByCreateTime")
        for field in ("groupBy", "queryItemList"):
            _optional_array(config, field)


def _optional_object(
    config: Mapping[str, Any],
    key: str,
    *,
    fields: frozenset[str] | None = frozenset({"label", "value"}),
) -> None:
    if key not in config or config.get(key) is None:
        return
    value = _mapping(config[key], f"report.config.{key}")
    if fields is not None:
        _reject_unknown(value, fields, f"report.config.{key}")


def _ui_object(value: Any, field: str) -> Mapping[str, Any]:
    selected = _mapping(value, field)
    _reject_unknown(selected, frozenset({"label", "value"}), field)
    return selected


def _optional_array(config: Mapping[str, Any], key: str) -> None:
    if key in config and config.get(key) is not None:
        _sequence(config[key], f"report.config.{key}")


def _optional_date_list(config: Mapping[str, Any], key: str) -> None:
    if key not in config or config.get(key) is None:
        return
    values = _sequence(config[key], f"report.config.{key}")
    if not values or any(not isinstance(item, Mapping) for item in values):
        _unsupported(
            "saved Dashboard date_list must contain date objects",
            f"report.config.{key}",
        )
    for item in values:
        _reject_unknown(
            item,
            frozenset({"start_date", "end_date"}),
            f"report.config.{key}",
        )


def _config(value: Any) -> Mapping[str, Any]:
    if isinstance(value, str):
        if len(value.encode("utf-8")) > MAX_CONFIG_BYTES:
            _unsupported("dashboard chart config exceeds its size limit", "report.config")
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            _unsupported("dashboard chart config is not valid JSON", "report.config")
    elif isinstance(value, Mapping):
        try:
            if len(json.dumps(value, ensure_ascii=False).encode("utf-8")) > MAX_CONFIG_BYTES:
                _unsupported("dashboard chart config exceeds its size limit", "report.config")
        except (TypeError, ValueError):
            _unsupported("dashboard chart config is not JSON-compatible", "report.config")
    return _mapping(value, "report.config")


def _date_window(start: str, end: str) -> None:
    left = _parse_date(start, "start")
    right = _parse_date(end, "end")
    days = (right - left).total_seconds() / 86_400
    if days < 0 or days > MAX_ANALYSIS_DAYS:
        raise InputValidationError(
            "dashboard analysis dates must be ordered within 90 days",
            field="start/end",
        )


def _validation_status(value: Any) -> str:
    selected = str(value or "").strip().casefold()
    return selected if selected in {"valid_offline", "needs_live_metadata"} else "valid_offline"


def _parse_date(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise InputValidationError(f"{field} must be an ISO date or timestamp", field=field)
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise InputValidationError(f"{field} must be an ISO date or timestamp", field=field) from exc
    return parsed.replace(tzinfo=parsed.tzinfo or timezone.utc).astimezone(timezone.utc)


def _date_item(start: str, end: str) -> dict[str, str]:
    return {"start_date": start.strip(), "end_date": end.strip()}


def _app_id(value: Any) -> str:
    if isinstance(value, bool):
        raise InputValidationError("app_id must be a positive integer", field="app_id")
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise InputValidationError("app_id must be a positive integer", field="app_id") from exc
    if parsed <= 0:
        raise InputValidationError("app_id must be a positive integer", field="app_id")
    return str(parsed)


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _unsupported(f"{field} must be an object", field)
    return value


def _objects(value: Any, field: str) -> list[dict[str, Any]]:
    values = _sequence(value, field)
    if any(not isinstance(item, Mapping) for item in values):
        _unsupported(f"{field} must contain objects", field)
    return [copy.deepcopy(dict(item)) for item in values]


def _sequence(value: Any, field: str) -> list[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        _unsupported(f"{field} must be an array", field)
    return list(value)


def _text(value: Any, field: str, *, maximum: int) -> str:
    if not isinstance(value, (str, int)) or isinstance(value, bool):
        raise InputValidationError(f"{field} must be text", field=field)
    rendered = str(value).strip()
    if not rendered or len(rendered) > maximum:
        raise InputValidationError(f"{field} is missing or too long", field=field)
    return rendered


def _reject_unknown(value: Mapping[str, Any], allowed: frozenset[str], field: str) -> None:
    if any(not isinstance(key, str) for key in value):
        _unsupported(f"{field} contains a non-text Web field", field)
    unknown = sorted(set(value) - set(allowed))
    if unknown:
        _unsupported(f"{field} contains unregistered Web fields", field)


def _unsupported(message: str, field: str) -> None:
    raise UnsupportedOperationError(
        message,
        field=field,
        next_action="Keep this chart unsupported until the Web artifact contract is proven.",
    )


__all__ = [
    "CompiledDashboardChart",
    "MAX_ANALYSIS_DAYS",
    "MAX_CONFIG_BYTES",
    "SUBJECT_KINDS",
    "compile_dashboard_chart",
    "validate_dashboard_window",
]
