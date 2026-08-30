"""Bounded projection for the dynamic Analysis user-event response."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from .drift import ProjectionDrift
from .models import OperationSpec
from .response_drift import ResponseDriftRecorder


_ABSENT = object()
_CREDENTIALS = frozenset({"access_token", "authorization", "cookie", "password", "secret", "token"})
_CREDENTIAL_SUFFIXES = ("_access_token", "_authorization", "_cookie", "_password", "_secret", "_token")


def project_analysis_user_event(
    operation: OperationSpec,
    data: Any,
    values: Mapping[str, Any],
    recorder: ResponseDriftRecorder,
) -> tuple[dict[str, Any], tuple[str, ...], ProjectionDrift]:
    if not isinstance(data, Mapping):
        return {}, ("user event response data shape changed; value was omitted",), ProjectionDrift.BREAKING
    declared = set(operation.response_projection.data_keys)
    unknown = {str(key) for key in data} - declared - set(
        operation.response_projection.known_omitted_data_keys
    )
    recorder.add_unknown_fields(("data",), data, unknown)
    drift = ProjectionDrift.ADDITIVE if unknown else ProjectionDrift.NONE
    warnings = (
        [f"unregistered user event data keys were omitted (count={len(unknown)})"]
        if unknown else []
    )
    requested = {
        item for item in values.get("fields", ())
        if isinstance(item, str) and item and len(item) <= 256
    }
    result: dict[str, Any] = {}
    drift = max(drift, _project_fixed_components(data, declared, requested, recorder, result, warnings))
    drift = max(drift, _project_profiles(operation, data, declared, requested, recorder, result, warnings))
    drift = max(drift, _project_records(operation, data, declared, requested, recorder, result, warnings))
    missing = set(operation.response_projection.required_data_keys) - set(result)
    if missing:
        warnings.append(f"required user event response keys are absent (count={len(missing)})")
        drift = ProjectionDrift.BREAKING
    return result, tuple(warnings), drift


def _project_fixed_components(
    data: Mapping[str, Any],
    declared: set[str],
    requested: set[str],
    recorder: ResponseDriftRecorder,
    result: dict[str, Any],
    warnings: list[str],
) -> ProjectionDrift:
    drift = ProjectionDrift.NONE
    if "event_timeline" in data and "event_timeline" in declared:
        value, item_drift = _project_timeline(data["event_timeline"], requested, recorder)
        if value is not _ABSENT:
            result["event_timeline"] = value
        drift = max(drift, item_drift)
        if item_drift:
            warnings.append("unregistered or invalid user event timeline values were omitted")
    if "summary" in data and "summary" in declared:
        value, item_drift = _project_summary(data["summary"], recorder)
        if value is not _ABSENT:
            result["summary"] = value
        drift = max(drift, item_drift)
        if item_drift:
            warnings.append("unregistered or invalid user event summary values were omitted")
    return drift


def _project_profiles(
    operation: OperationSpec,
    data: Mapping[str, Any],
    declared: set[str],
    requested: set[str],
    recorder: ResponseDriftRecorder,
    result: dict[str, Any],
    warnings: list[str],
) -> ProjectionDrift:
    drift = ProjectionDrift.NONE
    for key in ("device", "user"):
        if key not in data or key not in declared:
            continue
        allowed = set(operation.response_projection.data_item_keys.get(key, ())) | requested
        value, item_drift = _project_profile(data[key], allowed, recorder, ("data", key))
        if value is _ABSENT:
            warnings.append(f"invalid contracted user event {key} data was omitted")
            drift = ProjectionDrift.BREAKING
        else:
            result[key] = value
            drift = max(drift, item_drift)
        if item_drift:
            warnings.append(f"unregistered or invalid selected user event {key} values were omitted")
    return drift


def _project_records(
    operation: OperationSpec,
    data: Mapping[str, Any],
    declared: set[str],
    requested: set[str],
    recorder: ResponseDriftRecorder,
    result: dict[str, Any],
    warnings: list[str],
) -> ProjectionDrift:
    key = "re_attribute_records"
    if key not in data or key not in declared:
        return ProjectionDrift.NONE
    allowed = set(operation.response_projection.data_item_keys.get(key, ())) | requested
    value, drift = _project_record_rows(data[key], allowed, recorder)
    if value is _ABSENT:
        warnings.append("invalid contracted user event re_attribute_records were omitted")
        return ProjectionDrift.BREAKING
    result[key] = value
    if drift:
        warnings.append("unregistered or invalid selected user event re_attribute values were omitted")
    return drift


def _project_timeline(
    value: Any, requested: set[str], recorder: ResponseDriftRecorder
) -> tuple[Any, ProjectionDrift]:
    if not isinstance(value, (list, tuple)) or len(value) > 10_000:
        return _ABSENT, ProjectionDrift.BREAKING
    result: list[dict[str, Any]] = []
    drift = ProjectionDrift.NONE
    for row in value:
        projected, row_drift = _project_timeline_row(row, requested, recorder)
        if projected is not _ABSENT:
            result.append(projected)
        drift = max(drift, row_drift)
    return result, drift


def _project_timeline_row(
    row: Any, requested: set[str], recorder: ResponseDriftRecorder
) -> tuple[Any, ProjectionDrift]:
    if not isinstance(row, Mapping):
        return _ABSENT, ProjectionDrift.BREAKING
    unknown = {str(key) for key in row} - {"timeline", "list"}
    recorder.add_unknown_fields(("data", "event_timeline", "*"), row, unknown)
    drift = ProjectionDrift.ADDITIVE if unknown else ProjectionDrift.NONE
    timeline, events = row.get("timeline"), row.get("list")
    if not _bounded_json_scalar(timeline) or not isinstance(events, (list, tuple)):
        return _ABSENT, ProjectionDrift.BREAKING
    if len(events) > 10_000:
        events, drift = events[:10_000], ProjectionDrift.BREAKING
    safe_events: list[dict[str, Any]] = []
    for event in events:
        projected, event_drift = _project_timeline_event(event, requested, recorder)
        if projected is not _ABSENT:
            safe_events.append(projected)
        drift = max(drift, event_drift)
    return {"timeline": timeline, "list": safe_events}, drift


def _project_timeline_event(
    event: Any, requested: set[str], recorder: ResponseDriftRecorder
) -> tuple[Any, ProjectionDrift]:
    if not isinstance(event, Mapping):
        return _ABSENT, ProjectionDrift.BREAKING
    allowed = {"事件名称", "事件时间"} | requested
    unknown = {str(key) for key in event} - allowed
    recorder.add_unknown_fields(("data", "event_timeline", "*", "list", "*"), event, unknown)
    drift = ProjectionDrift.ADDITIVE if unknown else ProjectionDrift.NONE
    result: dict[str, Any] = {}
    for key in allowed:
        if key not in event:
            continue
        normalized = _bounded_json_contract_value(event[key])
        if normalized is _ABSENT:
            drift = ProjectionDrift.BREAKING
        else:
            result[key] = normalized
    return result, drift


def _project_profile(
    value: Any,
    allowed: set[str],
    recorder: ResponseDriftRecorder,
    path: tuple[str, ...],
) -> tuple[Any, ProjectionDrift]:
    if not isinstance(value, Mapping) or len(value) > 10_000:
        return _ABSENT, ProjectionDrift.BREAKING
    unknown = {str(key) for key in value} - allowed
    recorder.add_unknown_fields(path, value, unknown)
    drift = ProjectionDrift.ADDITIVE if unknown else ProjectionDrift.NONE
    result: dict[str, Any] = {}
    for key, item in value.items():
        if str(key) not in allowed:
            continue
        normalized = _bounded_json_contract_value(item)
        if normalized is _ABSENT:
            drift = ProjectionDrift.BREAKING
        else:
            result[str(key)] = normalized
    return result, drift


def _project_record_rows(
    value: Any, allowed: set[str], recorder: ResponseDriftRecorder
) -> tuple[Any, ProjectionDrift]:
    if not isinstance(value, (list, tuple)) or len(value) > 10_000:
        return _ABSENT, ProjectionDrift.BREAKING
    result: list[dict[str, Any]] = []
    drift = ProjectionDrift.NONE
    for row in value:
        projected, row_drift = _project_profile(
            row, allowed, recorder, ("data", "re_attribute_records", "*")
        )
        if projected is not _ABSENT:
            result.append(projected)
        drift = max(drift, row_drift)
    return result, drift


def _project_summary(
    value: Any, recorder: ResponseDriftRecorder
) -> tuple[Any, ProjectionDrift]:
    if not isinstance(value, (list, tuple)) or len(value) > 10_000:
        return _ABSENT, ProjectionDrift.BREAKING
    result: list[dict[str, Any]] = []
    drift = ProjectionDrift.NONE
    for row in value:
        projected, row_drift = _project_summary_row(row, recorder)
        if projected is not _ABSENT:
            result.append(projected)
        drift = max(drift, row_drift)
    return result, drift


def _project_summary_row(
    row: Any, recorder: ResponseDriftRecorder
) -> tuple[Any, ProjectionDrift]:
    if not isinstance(row, Mapping):
        return _ABSENT, ProjectionDrift.BREAKING
    unknown = {str(key) for key in row} - {"timeline", "cnt", "list"}
    recorder.add_unknown_fields(("data", "summary", "*"), row, unknown)
    drift = ProjectionDrift.ADDITIVE if unknown else ProjectionDrift.NONE
    timeline, count, items = row.get("timeline"), row.get("cnt"), row.get("list")
    if not _bounded_json_scalar(timeline) or not _finite_number(count) or not isinstance(items, (list, tuple)):
        return _ABSENT, ProjectionDrift.BREAKING
    if len(items) > 10_000:
        items, drift = items[:10_000], ProjectionDrift.BREAKING
    safe_items: list[dict[str, Any]] = []
    for item in items:
        projected, item_drift = _project_summary_item(item, recorder)
        if projected is not _ABSENT:
            safe_items.append(projected)
        drift = max(drift, item_drift)
    return {"timeline": timeline, "cnt": count, "list": safe_items}, drift


def _project_summary_item(
    item: Any, recorder: ResponseDriftRecorder
) -> tuple[Any, ProjectionDrift]:
    if not isinstance(item, Mapping):
        return _ABSENT, ProjectionDrift.BREAKING
    unknown = {str(key) for key in item} - {"event", "cnt"}
    recorder.add_unknown_fields(("data", "summary", "*", "list", "*"), item, unknown)
    event, count = item.get("event"), item.get("cnt")
    if not _bounded_json_scalar(event) or not _finite_number(count):
        return _ABSENT, ProjectionDrift.BREAKING
    return {"event": event, "cnt": count}, (
        ProjectionDrift.ADDITIVE if unknown else ProjectionDrift.NONE
    )


def _bounded_json_scalar(value: Any) -> bool:
    return _json_scalar(value) and (not isinstance(value, str) or len(value) <= 4_096)


def _bounded_json_contract_value(value: Any, *, depth: int = 0) -> Any:
    if depth > 6:
        return _ABSENT
    if _bounded_json_scalar(value):
        return value
    if isinstance(value, (list, tuple)):
        return _bounded_sequence(value, depth)
    if isinstance(value, Mapping):
        return _bounded_mapping(value, depth)
    return _ABSENT


def _bounded_sequence(value: Any, depth: int) -> Any:
    if len(value) > 10_000:
        return _ABSENT
    result: list[Any] = []
    for item in value:
        normalized = _bounded_json_contract_value(item, depth=depth + 1)
        if normalized is _ABSENT:
            return _ABSENT
        result.append(normalized)
    return result


def _bounded_mapping(value: Mapping[Any, Any], depth: int) -> Any:
    if len(value) > 1_000:
        return _ABSENT
    result: dict[str, Any] = {}
    for key, item in value.items():
        name = str(key)
        if len(name) > 256 or _credential_key(name):
            return _ABSENT
        normalized = _bounded_json_contract_value(item, depth=depth + 1)
        if normalized is _ABSENT:
            return _ABSENT
        result[name] = normalized
    return result


def _credential_key(value: str) -> bool:
    normalized = value.casefold().replace("-", "_")
    return normalized in _CREDENTIALS or normalized.endswith(_CREDENTIAL_SUFFIXES)


def _finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and (
        not isinstance(value, float) or math.isfinite(value)
    )


def _json_scalar(value: Any) -> bool:
    return value is None or isinstance(value, (str, bool, int)) or (
        isinstance(value, float) and math.isfinite(value)
    )


__all__ = ["project_analysis_user_event"]
