"""Bounded realtime diagnostics, metadata validation and selected-property projection."""

from __future__ import annotations

import copy
import math
import re
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any

from ._field_policy_metadata import load_event_property_rows, load_view
from ._field_policy_operations import ANALYSIS_EVENT, ANALYSIS_EVENT_INFO, ANALYSIS_EVENT_PROPERTY
from ._field_policy_shared import (
    MetadataLoader, is_direct_personal_response_field, is_sensitive_analysis_field,
    is_sensitive_control_key, reject_sensitive_metadata_fields,
)
from .drift import ProjectionDrift
from .errors import InputValidationError
from .models import OperationSpec
from .response_drift import ResponseDriftRecorder


MAX_REALTIME_ROWS = 1000
MAX_WINDOW = timedelta(days=1)
FILTER_FIELDS = ("event_name", "client_lib", "client_lib_version", "client_id", "request_id", "properties")
PUBLIC_FILTER_FIELDS = frozenset({"event_name", "event_type", "client_lib", "client_lib_version"})
ITEM_KEYS = ("client_id", "client_time", "event_name", "event_type", "request_id", "request_time", "client_lib", "client_lib_version")
_SCALAR_TYPES = frozenset({"STRING", "BOOL", "INT", "FLOAT", "DATETIME", "DATE"})
_PROPERTY_NAME = re.compile(r"^[A-Za-z_$][A-Za-z0-9_.$-]{0,127}$")


def realtime_property_filter_schema() -> dict[str, Any]:
    value_types = {"STRING": {"type": "string", "maxLength": 8192}, "BOOL": {"type": "boolean"},
                   "INT": {"type": "integer"}, "FLOAT": {"type": "number"},
                   "DATE": {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}$"},
                   "DATETIME": {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$"}}
    return {
        "type": "array", "minItems": 1, "maxItems": 1,
        "items": {"oneOf": [
            {"type": "object", "additionalProperties": False,
             "required": ["field", "datatype", "operator", "values"],
             "properties": {
                 "field": {"type": "string", "pattern": _PROPERTY_NAME.pattern, "maxLength": 128,
                           "description": "Exact same-App event property metadata name, matched to its datatype and privacy policy."},
                 "datatype": {"const": datatype}, "operator": {"const": "EQUALS"},
                 "values": {"type": "array", "minItems": 1, "maxItems": 1, "items": value_type},
             }} for datatype, value_type in value_types.items()
        ]},
    }


def realtime_property_fields_schema() -> dict[str, Any]:
    return {"type": "array", "maxItems": 20, "uniqueItems": True,
            "items": {"type": "string", "pattern": _PROPERTY_NAME.pattern, "maxLength": 128}}


def realtime_event_inputs(app_id: int, start: str, end: str, event_type: str, optional: Mapping[str, Any]) -> dict[str, Any]:
    if set(optional) - {*FILTER_FIELDS, "property_fields"}:
        _invalid("inputs", "registered realtime diagnostic fields only")
    filters = {key: optional[key] for key in FILTER_FIELDS if optional.get(key) is not None}
    if event_type != "":
        filters["event_type"] = event_type
    selected = {"app_id": app_id, "filters": filters, "page": 1, "page_size": 50,
                "request_time": [start, end], "property_fields": optional.get("property_fields", ())}
    validate_realtime_event_request(selected)
    return selected


def _invalid(field: str, allowed: str) -> None:
    raise InputValidationError(
        f"actual value: invalid or unsupported realtime diagnostic input; allowed: {allowed}",
        field=field,
        next_action="Use an explicit window of at most24 hours and exact same-App metadata names/types; remove unsupported or sensitive fields.",
    )


def validate_realtime_event_request(inputs: Mapping[str, Any]) -> None:
    app_id = inputs.get("app_id")
    if type(app_id) is not int or app_id < 1:
        _invalid("app_id", "a positive integer")
    _validate_window(inputs.get("request_time"))
    _validate_page(inputs)
    _validate_filters(inputs.get("filters"))
    _validate_property_selection(inputs.get("property_fields", ()))


def _validate_window(window: Any) -> None:
    if not isinstance(window, (list, tuple)) or len(window) != 2:
        _invalid("request_time", "two ordered local datetimes")
    try:
        dates = [datetime.strptime(value, "%Y-%m-%d %H:%M:%S") for value in window]
        valid = all(date.strftime("%Y-%m-%d %H:%M:%S") == value for date, value in zip(dates, window))
    except (TypeError, ValueError):
        valid = False
    if not valid or not timedelta(0) <= dates[1] - dates[0] <= MAX_WINDOW:
        _invalid("request_time", "YYYY-MM-DD HH:MM:SS in Asia/Shanghai, start<=end, at most24 hours")


def _validate_page(inputs: Mapping[str, Any]) -> None:
    if type(inputs.get("page", 1)) is not int or inputs.get("page", 1) != 1:
        _invalid("page", "1; native realtime paging is unproven")
    size = inputs.get("page_size", 50)
    if type(size) is not int or not 1 <= size <= MAX_REALTIME_ROWS:
        _invalid("page_size", "an integer from1 through1000; this is not a native completeness guarantee")


def _validate_filters(filters: Any) -> None:
    if not isinstance(filters, Mapping) or set(filters) - {*FILTER_FIELDS, "event_type"}:
        _invalid("filters", "only registered AND filters")
    for key in set(filters) - {"properties"}:
        value = filters[key]
        bound = 256 if key in {"client_id", "request_id"} else 64 if key in {"event_name", "event_type"} else 128
        if not isinstance(value, str) or not value or len(value) > bound:
            _invalid(f"filters.{key}", f"a nonempty string of at most{bound} characters")
    name = filters.get("event_name")
    if name is not None and (not name.isascii() or not name.isprintable()):
        _invalid("filters.event_name", "the English metadata name, never its display label")
    _property_filter(filters)


def _validate_property_selection(selected: Any) -> None:
    if not isinstance(selected, (list, tuple)) or len(selected) > 20:
        _invalid("property_fields", "at most20 distinct safe property names")
    if any(not isinstance(name, str) or not _PROPERTY_NAME.fullmatch(name) for name in selected) or len(selected) != len(set(selected)):
        _invalid("property_fields", "distinct English metadata names")


def _property_filter(filters: Mapping[str, Any]) -> Mapping[str, Any] | None:
    if "properties" not in filters:
        return None
    properties = filters["properties"]
    if not isinstance(properties, (list, tuple)) or len(properties) != 1:
        _invalid("filters.properties", "exactly one property filter, never silently discard extras")
    item = properties[0]
    if not isinstance(item, Mapping) or set(item) != {"field", "datatype", "operator", "values"}:
        _invalid("filters.properties", "field/datatype/operator/values only")
    name, datatype, values = item["field"], item["datatype"], item["values"]
    if not isinstance(name, str) or not _PROPERTY_NAME.fullmatch(name):
        _invalid("filters.properties.field", "an English metadata property name")
    if not isinstance(datatype, str) or datatype not in _SCALAR_TYPES or item["operator"] != "EQUALS":
        _invalid("filters.properties", "EQUALS with an exact scalar metadata datatype; LIST/DICT comparison semantics are unverified")
    if not isinstance(values, (list, tuple)) or len(values) != 1 or not _typed_scalar(values[0], datatype):
        _invalid("filters.properties.values", "exactly one scalar matching the metadata datatype")
    return item


def realtime_event_metadata_dependencies(inputs: Mapping[str, Any]) -> tuple[str, ...]:
    filters = inputs.get("filters")
    if not isinstance(filters, Mapping):
        return ()
    properties = bool(inputs.get("property_fields")) or "properties" in filters
    event = bool(filters.get("event_name"))
    return ((ANALYSIS_EVENT,) if event else ()) + ((ANALYSIS_EVENT_INFO if event else ANALYSIS_EVENT_PROPERTY,) if properties else ())


def validate_realtime_event_fields(inputs: Mapping[str, Any], loader: MetadataLoader) -> dict[str, str]:
    validate_realtime_event_request(inputs)
    filters, app_id = inputs["filters"], str(inputs["app_id"])
    event = filters.get("event_name")
    if event is not None:
        events = load_view(ANALYSIS_EVENT, {"app_id": app_id}, loader)
        if event not in {row.get("name") for row in events.rows}:
            _invalid("filters.event_name", "an exact event name from same-App live metadata")
    item = _property_filter(filters)
    selected = set(inputs.get("property_fields", ()))
    requested = selected | ({item["field"]} if item else set())
    if not requested:
        return {}
    rows = load_event_property_rows((event,), app_id, loader) if event else load_view(ANALYSIS_EVENT_PROPERTY, {"app_id": app_id}, loader).rows
    reject_sensitive_metadata_fields(rows, requested)
    types = {name: _metadata_datatype(name, rows, item) for name in requested}
    return {name: types[name] for name in selected}


def _metadata_datatype(name: str, rows: Any, condition: Mapping[str, Any] | None) -> str:
    matches = [row for row in rows if row.get("name") == name]
    if not matches or any(_private_property(row.get(key)) for row in matches for key in ("name", "cname", "remark")):
        _invalid("property_fields", "registered nonidentifying properties only")
    if any(not isinstance(row.get("data_type"), str) for row in matches):
        _invalid("property_fields", "one scalar metadata datatype")
    datatypes = {row["data_type"] for row in matches}
    if len(datatypes) != 1:
        _invalid("property_fields", "one unambiguous metadata datatype")
    datatype = next(iter(datatypes))
    if datatype not in _SCALAR_TYPES or (condition and condition["field"] == name and condition["datatype"] != datatype):
        _invalid("property_fields", "exact scalar metadata datatype; collection semantics remain unavailable")
    return datatype


def _private_property(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    name = value.casefold().strip().lstrip("$").replace("-", "_")
    return (
        is_sensitive_analysis_field(value) or is_sensitive_control_key(value)
        or is_direct_personal_response_field(value)
        or name in {"id", "uid", "clientid", "requestid", "request_ip", "request_ua", "ua", "deviceid", "userid"}
        or name.endswith(("_id", ".id"))
        or any(text in name for text in ("身份证", "手机号", "邮箱", "设备标识", "用户标识"))
    )


def _typed_scalar(value: Any, datatype: str) -> bool:
    if datatype == "BOOL":
        return type(value) is bool
    if datatype == "INT":
        return type(value) is int
    if datatype == "FLOAT":
        return type(value) is int or (type(value) is float and math.isfinite(value))
    if not isinstance(value, str) or len(value) > 8192:
        return False
    if datatype == "STRING":
        return True
    pattern = "%Y-%m-%d" if datatype == "DATE" else "%Y-%m-%d %H:%M:%S"
    try:
        return datetime.strptime(value, pattern).strftime(pattern) == value
    except ValueError:
        return False


def project_analysis_realtime_event(
    operation: OperationSpec, data: Any, values: Mapping[str, Any], recorder: ResponseDriftRecorder,
) -> tuple[dict[str, Any], tuple[str, ...], ProjectionDrift]:
    if not isinstance(data, Mapping) or not isinstance(data.get("list"), list) or len(data["list"]) > MAX_REALTIME_ROWS:
        recorder.add_breaking_field(("data", "list"), "array", data.get("list") if isinstance(data, Mapping) else data)
        return {}, ("realtime list shape or1000-row bound changed; result omitted",), ProjectionDrift.BREAKING
    unknown = set(data) - set(operation.response_projection.data_keys) - set(operation.response_projection.known_omitted_data_keys)
    recorder.add_unknown_fields(("data",), data, unknown)
    drift = ProjectionDrift.ADDITIVE if unknown else ProjectionDrift.NONE
    selected = _selected_projection(values)
    items: list[dict[str, Any]] = []
    warnings: set[str] = set()
    for row in data["list"]:
        if not isinstance(row, Mapping):
            recorder.add_breaking_field(("data", "list", "[]"), "object", row)
            return {}, ("realtime row shape changed; result omitted",), ProjectionDrift.BREAKING
        if not _matches_filters(row, values.get("filters", {})):
            return {"list": []}, ("native realtime rows do not match the requested filters; result omitted",), ProjectionDrift.BREAKING
        item, row_drift = _project_row(operation, row, selected, recorder)
        drift = max(drift, row_drift)
        items.append(item)
    if drift:
        warnings.add("unregistered or invalid realtime diagnostic fields were omitted")
    return {"list": items}, tuple(sorted(warnings)), drift


def _selected_projection(values: Mapping[str, Any]) -> dict[str, str]:
    hints = values.get("_validated_response_fields")
    if not isinstance(hints, Mapping):
        return {}
    return {name: datatype for name, datatype in hints.items() if isinstance(name, str) and name in values.get("property_fields", ()) and isinstance(datatype, str) and datatype in _SCALAR_TYPES and not _private_property(name)}


def _project_row(operation: OperationSpec, row: Mapping[str, Any], selected: Mapping[str, str], recorder: ResponseDriftRecorder) -> tuple[dict[str, Any], ProjectionDrift]:
    extra = set(row) - set(ITEM_KEYS) - set(operation.response_projection.known_omitted_item_keys)
    recorder.add_unknown_fields(("data", "list", "[]"), row, extra)
    item, drift = _project_base_fields(row, recorder)
    drift = max(drift, ProjectionDrift.ADDITIVE if extra else ProjectionDrift.NONE)
    if selected:
        properties, coverage, property_drift = _project_properties(row.get("raw_properties"), selected, recorder)
        item.update(properties=properties, property_coverage=coverage)
        drift = max(drift, property_drift)
    return item, drift


def _matches_filters(row: Mapping[str, Any], filters: Any) -> bool:
    if not isinstance(filters, Mapping) or any(row.get(key) != value for key, value in filters.items() if key != "properties"):
        return False
    condition = _property_filter(filters)
    if condition is None:
        return True
    raw = row.get("raw_properties")
    value = raw.get(condition["field"]) if isinstance(raw, Mapping) else None
    return _typed_scalar(value, condition["datatype"]) and value == condition["values"][0]


def _project_base_fields(row: Mapping[str, Any], recorder: ResponseDriftRecorder) -> tuple[dict[str, Any], ProjectionDrift]:
    item, drift = {}, ProjectionDrift.NONE
    for key in ITEM_KEYS:
        value = row.get(key)
        if (key in {"event_name", "request_time"} and not isinstance(value, str)) or (value is not None and not isinstance(value, str)):
            recorder.add_breaking_field(("data", "list", "[]", key), "string", value)
            drift = ProjectionDrift.BREAKING
        else:
            item[key] = value
    return item, drift


def _project_properties(raw: Any, selected: Mapping[str, str], recorder: ResponseDriftRecorder) -> tuple[dict[str, Any], dict[str, str], ProjectionDrift]:
    projected, coverage = {}, {}
    drift = ProjectionDrift.NONE
    if raw is not None and not isinstance(raw, Mapping):
        recorder.add_breaking_field(("data", "list", "[]", "raw_properties"), "object", raw)
        drift = ProjectionDrift.BREAKING
    for name, datatype in selected.items():
        if not isinstance(raw, Mapping) or name not in raw:
            coverage[name] = "unavailable"
        elif raw[name] is None:
            projected[name], coverage[name] = None, "null"
        elif _typed_scalar(raw[name], datatype):
            projected[name], coverage[name] = copy.deepcopy(raw[name]), "returned"
        else:
            coverage[name] = "type_mismatch"
            expected = {"BOOL": "boolean", "INT": "integer", "FLOAT": "number"}.get(datatype, "string")
            recorder.add_breaking_field(("data", "list", "[]", "raw_properties", name), expected, raw[name])
            drift = ProjectionDrift.BREAKING
    return projected, coverage, drift
