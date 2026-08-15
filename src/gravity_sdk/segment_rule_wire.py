"""Frontend-compatible request codecs for Segment Rule mutations."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from datetime import date as calendar_date, timedelta
from typing import Any

from .errors import PolicyViolation
from .segment_mutation_contracts import (
    FROM_HISTORY_CREATE,
    FROM_RULE_CREATE,
    FROM_RULE_UPDATE,
    FROM_TMP_CREATE,
    MANUAL_UPDATE,
    SAVE,
)
from .wire import isolated_wire as _isolated_wire


def _decimal_int(values: Mapping[str, Any], field: str) -> int:
    value = str(values.get(field, ""))
    if not value.isdecimal():
        raise PolicyViolation(f"analysis segment mutation {field} must be decimal")
    return int(value)


def _analysis_segment_rule_request_parts(
    values: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Compile the public segment-rule contract into Gravity's frontend wire shape."""

    app_id = values.get("app_id")
    if not isinstance(app_id, str) or not app_id.isdecimal():
        raise PolicyViolation("analysis segment-rule app_id must be decimal")
    property_rules = values.get("user_property_rules", {})
    event_rules = values.get("user_event_rules", {})
    if not isinstance(property_rules, Mapping) or not isinstance(event_rules, Mapping):
        raise PolicyViolation("analysis segment rules are invalid")

    property_groups = [
        _compile_segment_property_group(group)
        for group in property_rules.get("groups", ())
    ]
    event_groups = [
        _compile_segment_event_group(group)
        for group in event_rules.get("groups", ())
    ]
    frontend_property_groups = [
        _frontend_segment_property_group(group)
        for group in property_rules.get("groups", ())
    ]
    frontend_event_groups = [
        _frontend_segment_event_group(group)
        for group in event_rules.get("groups", ())
    ]
    body = {
        "app_id": int(app_id),
        "segment_name": values.get("name"),
        "segment_remark": values.get("remark", ""),
        "update_type": values.get("update_type", "Manual"),
        "update_date_range": values.get("date_range"),
        "cond_logic": values.get("cond_logic", "AND"),
        "from_user_prop": {
            "cond_logic": property_rules.get("cond_logic", "AND"),
            "list": property_groups,
        },
        "from_event_prop": {
            "cond_logic": event_rules.get("cond_logic", "AND"),
            "list": event_groups,
        },
        "FE_CONFIG": json.dumps(
            {
                "userPropertyRules": frontend_property_groups,
                "userBehaviorRules": frontend_event_groups,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ),
    }
    return _isolated_wire({}, body)


def _analysis_segment_rule_update_request_parts(
    values: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    query, body = _analysis_segment_rule_request_parts(values)
    segment_id = str(values.get("segment_id", ""))
    if not segment_id.isdecimal():
        raise PolicyViolation("analysis segment-rule segment_id must be decimal")
    body["segment_id"] = int(segment_id)
    body["to_update_latest_result"] = values.get(
        "to_update_latest_result", True
    )
    return _isolated_wire(query, body)


def _analysis_segment_save_request_parts(
    values: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    body = {
        "segment_id": _decimal_int(values, "segment_id"),
        "segment_name": values.get("segment_name"),
        "action": values.get("action"),
    }
    if values.get("action") == "UPDATE_NAME":
        body["segment_remark"] = values.get("segment_remark", "")
    return _isolated_wire({}, body)


def _analysis_segment_manual_request_parts(
    values: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    return _isolated_wire({}, {"segment_id": _decimal_int(values, "segment_id")})


def _analysis_segment_history_request_parts(
    values: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    return _isolated_wire(
        {},
        {
            "app_id": _decimal_int(values, "app_id"),
            "segment_id": _decimal_int(values, "segment_id"),
            "version_id": _decimal_int(values, "version_id"),
            "segment_name": values.get("segment_name"),
            "segment_remark": values.get("segment_remark", ""),
        },
    )


def _analysis_segment_tmp_request_parts(
    values: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    return _isolated_wire(
        {},
        {
            "from_tmp_segment_id": _decimal_int(values, "from_tmp_segment_id"),
            "app_id": _decimal_int(values, "app_id"),
            "segment_name": values.get("segment_name"),
            "segment_remark": values.get("segment_remark", ""),
        },
    )


def segment_mutation_request_builder(
    operation_id: str,
) -> Callable[[Mapping[str, Any]], tuple[dict[str, Any], dict[str, Any]]] | None:
    """Return the exact frontend codec for a registered Segment mutation."""

    return {
        FROM_RULE_CREATE: _analysis_segment_rule_request_parts,
        FROM_RULE_UPDATE: _analysis_segment_rule_update_request_parts,
        SAVE: _analysis_segment_save_request_parts,
        MANUAL_UPDATE: _analysis_segment_manual_request_parts,
        FROM_HISTORY_CREATE: _analysis_segment_history_request_parts,
        FROM_TMP_CREATE: _analysis_segment_tmp_request_parts,
    }.get(operation_id)


def _compile_segment_property_group(group: Any) -> dict[str, Any]:
    if not isinstance(group, Mapping):
        raise PolicyViolation("analysis segment property group is invalid")
    return {
        "cond_logic": group.get("cond_logic", "AND"),
        "list": [
            _compile_segment_condition(item)
            for item in group.get("conditions", ())
        ],
    }


def _compile_segment_event_group(group: Any) -> dict[str, Any]:
    if not isinstance(group, Mapping):
        raise PolicyViolation("analysis segment event group is invalid")
    return {
        "cond_logic": group.get("cond_logic", "AND"),
        "list": [
            _compile_segment_event(item)

            for item in group.get("conditions", ())
        ],
    }


def _compile_segment_condition(item: Any) -> dict[str, Any]:
    if not isinstance(item, Mapping):
        raise PolicyViolation("analysis segment condition is invalid")
    operator = str(item.get("operator", ""))
    wire: dict[str, Any] = {
        "operator": _segment_condition_operator(item),
        "field": item.get("field"),
        "type": item.get("type"),
        "value": _segment_condition_values(item),
    }
    dim_table = item.get("dim_using_table_name")
    if dim_table not in {None, ""}:
        wire["dim_using_table_name"] = dim_table
    if operator == "TRUE":
        wire["value"] = [True]
    elif operator == "FALSE":
        wire["value"] = [False]
    elif item.get("type") == "user_segment":
        wire["value"] = [True]
    return wire


def _segment_condition_operator(item: Mapping[str, Any]) -> str:
    operator = str(item.get("operator", ""))
    if operator in {"TRUE", "FALSE"}:
        return "EQUALS"
    if operator == "RELATIVE_DAY":
        return "CURRENT_DAY"
    if operator != "RELATIVELY_CURRENT_TIME":
        return operator
    relative_type = item.get("date_relative_type")
    relative_unit = item.get("date_relative_unit")
    if relative_type == "range" and relative_unit == "day":
        return "RELATIVE_DAY"
    if relative_type == "range" and relative_unit == "hour":
        return "RELATIVE_HOUR"
    if relative_type == "range" and relative_unit == "minute":
        return "RELATIVE_MINUTE"
    if relative_type == "day":
        return "RELATIVE_DAY"
    if relative_type == "week":
        return "RELATIVE_WEEK"
    if relative_type == "month":
        return "RELATIVE_MONTH"
    return operator


def _segment_condition_values(item: Mapping[str, Any]) -> list[Any]:
    raw_values = item.get("value", ())
    values = list(raw_values) if isinstance(raw_values, (list, tuple)) else []
    operator = item.get("operator")
    date_type = item.get("date_type")
    date_unit = item.get("date_unit")
    if operator == "CURRENT_DAY" and values:
        amount = values[0]
        if date_type == "past":
            return [-amount, 0] if date_unit == "within" else [-999, -amount]
        return [0, amount] if date_unit == "within" else [amount, 999]
    if operator == "RELATIVE_DAY" and len(values) >= 2:
        if date_type == "past":
            return [-values[0], -values[1]]
        return [values[0], values[1]]
    if operator == "RELATIVELY_CURRENT_TIME":
        relative_type = item.get("date_relative_type")
        if relative_type != "range":
            return ["event", "$EventCreateTime", 0, 0]
        if len(values) >= 2:
            left, right = values[:2]
            if item.get("date_relative_left") == "past":
                left = -left
            if item.get("date_relative_right") == "past":
                right = -right
            return ["event", "$EventCreateTime", left, right]
    return values


def _compile_segment_event(item: Any) -> dict[str, Any]:
    if not isinstance(item, Mapping):
        raise PolicyViolation("analysis segment event is invalid")
    target = item.get("target")
    did_condition = item.get("did_condition")
    if not isinstance(target, Mapping) or not isinstance(did_condition, Mapping):
        raise PolicyViolation("analysis segment event target is invalid")
    wire_target = {"name": target.get("name"), "field": target.get("field")}
    dim_table = target.get("dim_using_table_name")
    if dim_table not in {None, ""}:
        wire_target["dim_using_table_name"] = dim_table
    wire_did = {
        "operator": did_condition.get("operator"),
        "field": target.get("field"),
        "type": "event",
        "value": list(did_condition.get("value", ())),
    }
    if dim_table not in {None, ""}:
        wire_did["dim_using_table_name"] = dim_table

    return {
        "event_name": item.get("event_name"),
        "did": item.get("did"),
        "target": wire_target,
        "did_condition": wire_did,
        "time_zone": _segment_event_time_zone(item.get("date_range")),
        "cond_logic": item.get("cond_logic", "AND"),
        "conditions": [
            _compile_segment_condition(condition)
            for condition in item.get("conditions", ())
        ],
    }


def _segment_event_time_zone(value: Any) -> dict[str, list[int]]:
    if not isinstance(value, Mapping):
        raise PolicyViolation("analysis segment event date range is invalid")
    fixed: list[int] = []
    dynamic: list[int] = []
    mixed: list[int] = []
    quick_select = value.get("quick_select")
    if isinstance(quick_select, str) and quick_select:
        dynamic = list(_segment_quick_offsets(quick_select))
    elif value.get("date_type") == "static":
        raw_dates = value.get("date", ())
        if not isinstance(raw_dates, (list, tuple)) or len(raw_dates) != 2:
            raise PolicyViolation("analysis segment static date range is invalid")
        fixed = [_compact_date(item) for item in raw_dates]
    else:
        end_type = value.get("dynamic_end_type", "today")
        end_offset = 0 if end_type == "today" else -1
        if end_type == "dynamic":
            end_offset = -int(value.get("end_date_input", 0))
        if value.get("dynamic_start_type") == "static":
            mixed = [_compact_date(value.get("start_date")), end_offset]
        else:
            dynamic = [-int(value.get("start_date_input", 0)), end_offset]
    return {"fixed_date": fixed, "dynamic_date": dynamic, "mixed_date": mixed}


def _segment_quick_offsets(name: str) -> tuple[int, int]:
    fixed = {
        "yesterday": (-1, -1),
        "today": (0, 0),
        "last3day": (-3, -1),
        "recent3day": (-3, 0),
        "last7day": (-7, -1),
        "last14day": (-14, -1),
        "recent7day": (-7, 0),
        "last30day": (-30, -1),
        "recent30day": (-30, 0),
        "last90day": (-90, -1),
        "last120day": (-120, -1),
    }
    if name in fixed:
        return fixed[name]
    today = calendar_date.today()
    start_of_week = today - timedelta(days=today.weekday())
    if name == "week":
        return (-(today - start_of_week).days, 0)
    if name == "lastweek":
        previous_start = start_of_week - timedelta(days=7)
        return (-(today - previous_start).days, -(today - (start_of_week - timedelta(days=1))).days)
    start_of_month = today.replace(day=1)
    if name == "month":
        return (-(today - start_of_month).days, 0)
    if name == "lastmonth":
        previous_end = start_of_month - timedelta(days=1)
        previous_start = previous_end.replace(day=1)
        return (-(today - previous_start).days, -(today - previous_end).days)
    raise PolicyViolation("analysis segment quick date range is invalid")


def _compact_date(value: Any) -> int:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise PolicyViolation("analysis segment date is invalid")
    try:
        parsed = calendar_date.fromisoformat(value)
    except ValueError as exc:
        raise PolicyViolation("analysis segment date is invalid") from exc
    return int(parsed.strftime("%Y%m%d"))


def _frontend_segment_property_group(group: Any) -> dict[str, Any]:
    if not isinstance(group, Mapping):
        raise PolicyViolation("analysis segment property group is invalid")
    return {
        "cond_logic": group.get("cond_logic", "AND"),
        "conditions": [
            _frontend_segment_condition(item)
            for item in group.get("conditions", ())
        ],
    }


def _frontend_segment_condition(item: Any) -> dict[str, Any]:
    if not isinstance(item, Mapping):
        raise PolicyViolation("analysis segment condition is invalid")
    result: dict[str, Any] = {
        "filed_value": item.get("field"),

        "type": item.get("type"),
        "operator": item.get("operator"),
        "values": list(item.get("value", ())),
    }
    for key in (
        "dim_using_table_name",
        "segment_type",
        "version_id",
        "date_type",
        "date_unit",
        "date_relative_type",
        "date_relative_unit",
        "date_relative_left",
        "date_relative_right",
    ):
        if item.get(key) not in {None, ""}:
            result[key] = item[key]
    return result


def _frontend_segment_event_group(group: Any) -> dict[str, Any]:
    if not isinstance(group, Mapping):
        raise PolicyViolation("analysis segment event group is invalid")
    return {
        "cond_logic": group.get("cond_logic", "AND"),
        "conditions": [
            _frontend_segment_event(item)
            for item in group.get("conditions", ())
        ],
    }


def _frontend_segment_event(item: Any) -> dict[str, Any]:
    if not isinstance(item, Mapping):
        raise PolicyViolation("analysis segment event is invalid")
    target = item.get("target")
    did_condition = item.get("did_condition")
    date_range = item.get("date_range")
    if not all(isinstance(value, Mapping) for value in (target, did_condition, date_range)):
        raise PolicyViolation("analysis segment event is invalid")
    target_values = [target.get("field")]
    if target.get("name") != target.get("field"):
        target_values.append(target.get("name"))
    return {
        "eventValue": item.get("event_name"),
        "is_did": item.get("did"),
        "targetValue": target_values,
        "operator": did_condition.get("operator"),
        "values": list(did_condition.get("value", ())),
        "dateRangeInfo": {
            "resultDate": _segment_event_result_dates(date_range),
            "extra_data": _frontend_segment_date_range(date_range),
        },
        "cond_logic": item.get("cond_logic", "AND"),
        "filters": [
            _frontend_segment_condition(condition)
            for condition in item.get("conditions", ())
        ],
    }


def _frontend_segment_date_range(value: Mapping[str, Any]) -> dict[str, Any]:
    key_map = {
        "date_type": "dateType",
        "date": "date",
        "quick_select": "quickSelect",
        "start_date": "startDate",
        "dynamic_start_type": "dynamicStartType",
        "dynamic_end_type": "dynamicEndType",
        "start_date_input": "startDateInput",
        "end_date_input": "endDateInput",
    }
    result: dict[str, Any] = {}
    for source, target in key_map.items():
        item = value.get(source)
        if item is None or item == "":
            continue
        result[target] = list(item) if isinstance(item, tuple) else item
    return result


def _segment_event_result_dates(value: Mapping[str, Any]) -> list[str]:
    if value.get("date_type") == "static":
        raw = value.get("date", ())
        return list(raw) if isinstance(raw, (list, tuple)) else []
    if isinstance(value.get("quick_select"), str):
        start, end = _segment_quick_offsets(str(value["quick_select"]))
        today = calendar_date.today()
        return [
            (today + timedelta(days=start)).isoformat(),
            (today + timedelta(days=end)).isoformat(),
        ]
    end_type = value.get("dynamic_end_type", "today")
    today = calendar_date.today()
    end_offset = 0 if end_type == "today" else -1
    if end_type == "dynamic":
        end_offset = -int(value.get("end_date_input", 0))
    if value.get("dynamic_start_type") == "static":
        start = str(value.get("start_date"))
    else:
        start = (today - timedelta(days=int(value.get("start_date_input", 0)))).isoformat()
    return [start, (today + timedelta(days=end_offset)).isoformat()]


__all__ = [
    "_analysis_segment_rule_request_parts",
    "_analysis_segment_rule_update_request_parts",
    "_analysis_segment_save_request_parts",
    "segment_mutation_request_builder",
]
