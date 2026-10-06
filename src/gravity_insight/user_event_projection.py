"""Request contract and bounded projection for the Analysis user-event operation."""

from __future__ import annotations

import math
from dataclasses import dataclass
from collections.abc import Callable, Mapping
from typing import Any

from .actionable_error_values import actual_value
from .drift import ProjectionDrift
from .errors import InputValidationError
from .models import OperationSpec
from .response_drift import ResponseDriftRecorder


_ABSENT = object()
# Fixed timeline keys; property keys are registered display labels (#238).
_TIMELINE_EVENT_KEYS = ("事件名称", "事件时间", "事件英文名")
# Bounds event.info metadata reads for event-scoped timeline labels.
_EVENT_SCOPED_LABEL_LIMIT = 50
_CREDENTIALS = frozenset({"access_token", "authorization", "cookie", "password", "secret", "token"})
_CREDENTIAL_SUFFIXES = ("_access_token", "_authorization", "_cookie", "_password", "_secret", "_token")


def validate_user_event_request(inputs: Mapping[str, Any]) -> None:
    has_date = inputs.get("date") not in (None, "")
    has_date_list = inputs.get("date_list") not in (None, (), [])
    if has_date == has_date_list:
        raise InputValidationError(
            f"actual value: {actual_value({'date_present': has_date, 'date_list_present': has_date_list})}; "
            "allowed shape: provide exactly one of date or date_list",
            field="date/date_list",
        )
    page = inputs.get("page", 1)
    page_size = inputs.get("page_size", 20)
    if (
        not isinstance(page, int)
        or isinstance(page, bool)
        or page < 1
        or not isinstance(page_size, int)
        or isinstance(page_size, bool)
        or not 1 <= page_size <= 200
    ):
        raise InputValidationError(
            f"actual value: {actual_value({'page': page, 'page_size': page_size})}; "
            "allowed range: page is an integer >= 1 and page_size is 1 through 200",
            field="page/page_size",
        )


def user_event_response_labels(
    inputs: Mapping[str, Any],
    property_rows: Any,
    load_event_rows: Callable[[str], Any],
) -> dict[str, Any]:
    """Map selected property names to the display labels timeline rows use.

    Labels are unique only within one event. App-wide unique labels are safe to
    map; a label shared across events maps only through listed events' bindings.
    """
    selected = set(inputs.get("fields", ()))
    owners = _label_owners(property_rows)
    labels = _selected_labels(owners, selected)
    names = {name for group in owners.values() for name in group}
    known = set(owners)
    event_labels: dict[str, dict[str, str]] = {}
    events = sorted(set(inputs.get("event_list", ())))
    if (selected & names) - set(labels) and 0 < len(events) <= _EVENT_SCOPED_LABEL_LIMIT:
        for event in events:
            scoped = _label_owners(load_event_rows(event))
            event_labels[event] = _selected_labels(scoped, selected)
            known.update(scoped)
            names.update(name for group in scoped.values() for name in group)
    return {
        "labels": labels,
        "event_labels": event_labels,
        "known_labels": frozenset(known),
        "shared_labels": frozenset(label for label, group in owners.items() if len(group) > 1),
        "event_fields": frozenset(selected & (names | known)),
    }


def _label_owners(rows: Any) -> dict[str, set[str]]:
    owners: dict[str, set[str]] = {}
    for row in rows:
        name, label = row.get("name"), row.get("cname")
        if isinstance(name, str) and isinstance(label, str) and label:
            owners.setdefault(label, set()).add(name)
    return owners


def _selected_labels(owners: Mapping[str, set[str]], selected: set[str]) -> dict[str, str]:
    candidates: dict[str, set[str]] = {}
    for label, names in owners.items():
        if len(names) == 1 and label not in selected - names:
            candidates.setdefault(next(iter(names)), set()).add(label)
    # A name with several unique labels has no single timeline key; leave it unmapped.
    return {name: next(iter(labels)) for name, labels in candidates.items() if name in selected and len(labels) == 1}


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
    selected = _SelectedEventFields.from_validation(values.get("_validated_response_fields"))
    drift = max(drift, _project_fixed_components(data, declared, requested, recorder, result, warnings, selected))
    drift = max(drift, _project_profiles(operation, data, declared, requested, recorder, result, warnings))
    drift = max(drift, _project_records(operation, data, declared, requested, recorder, result, warnings))
    if any(isinstance(group, Mapping) and group.get("list") for group in result.get("event_timeline", ())):
        # Only non-empty pages carry coverage; an all-empty page stays status=empty.
        result["field_coverage"] = selected.coverage(result["event_timeline"], warnings)
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
    selected: "_SelectedEventFields",
) -> ProjectionDrift:
    drift = ProjectionDrift.NONE
    if "event_timeline" in data and "event_timeline" in declared:
        value, item_drift = _project_timeline(data["event_timeline"], requested, recorder, selected)
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
    value: Any, requested: set[str], recorder: ResponseDriftRecorder, selected: "_SelectedEventFields",
) -> tuple[Any, ProjectionDrift]:
    if not isinstance(value, (list, tuple)) or len(value) > 10_000:
        return _ABSENT, ProjectionDrift.BREAKING
    result: list[dict[str, Any]] = []
    drift = ProjectionDrift.NONE
    for row in value:
        projected, row_drift = _project_timeline_row(row, requested, recorder, selected)
        if projected is not _ABSENT:
            result.append(projected)
        drift = max(drift, row_drift)
    return result, drift


def _project_timeline_row(
    row: Any, requested: set[str], recorder: ResponseDriftRecorder, selected: "_SelectedEventFields",
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
        projected, event_drift = _project_timeline_event(event, requested, recorder, selected)
        if projected is not _ABSENT:
            safe_events.append(projected)
        drift = max(drift, event_drift)
    return {"timeline": timeline, "list": safe_events}, drift


def _project_timeline_event(
    event: Any, requested: set[str], recorder: ResponseDriftRecorder, selected: "_SelectedEventFields",
) -> tuple[Any, ProjectionDrift]:
    if not isinstance(event, Mapping):
        return _ABSENT, ProjectionDrift.BREAKING
    sources = {key: key for key in (*_TIMELINE_EVENT_KEYS, *requested)}
    sources.update(selected.labels_for(event.get("事件英文名")))
    # Unselected registered properties are omitted by request, not drift.
    unknown = {str(key) for key in event} - set(sources) - set(sources.values()) - selected.known_labels
    recorder.add_unknown_fields(("data", "event_timeline", "*", "list", "*"), event, unknown)
    drift = ProjectionDrift.ADDITIVE if unknown else ProjectionDrift.NONE
    result: dict[str, Any] = {}
    for key, source in sources.items():
        if source not in event:
            continue
        normalized = _bounded_json_contract_value(event[source])
        if normalized is _ABSENT:
            drift = ProjectionDrift.BREAKING
        else:
            result[key] = normalized
    return result, drift


@dataclass(frozen=True)
class _SelectedEventFields:
    labels: Mapping[str, str]
    event_labels: Mapping[str, Mapping[str, str]]
    known_labels: frozenset[str]
    shared_labels: frozenset[str]
    event_fields: frozenset[str]

    @classmethod
    def from_validation(cls, value: Any) -> "_SelectedEventFields":
        if not isinstance(value, Mapping):
            return cls({}, {}, frozenset(), frozenset(), frozenset())
        labels, scoped = value.get("labels"), value.get("event_labels")
        return cls(
            dict(labels) if isinstance(labels, Mapping) else {},
            {str(k): dict(v) for k, v in scoped.items() if isinstance(v, Mapping)}
            if isinstance(scoped, Mapping) else {},
            frozenset(value.get("known_labels", ())),
            frozenset(value.get("shared_labels", ())),
            frozenset(value.get("event_fields", ())),
        )

    def labels_for(self, event_name: Any) -> Mapping[str, str]:
        # App-wide unique labels hold on every row; listed events add their bindings.
        scoped = self.event_labels.get(event_name, {}) if isinstance(event_name, str) else {}
        return {**self.labels, **scoped}

    def coverage(self, timeline: Any, warnings: list[str]) -> dict[str, Any]:
        events = [
            event for group in timeline if isinstance(group, Mapping)
            for event in group.get("list", ()) if isinstance(event, Mapping)
        ]
        unmapped = self._unmapped()
        mapped = self.event_fields - set(unmapped)
        counts = {
            name: sum(name not in event for event in events if self._applies(name, event))
            for name in sorted(mapped)
        }
        missing = [name for name, count in counts.items() if count]
        if unmapped:
            warnings.append(
                "selected event properties have no unique display label; select property names "
                "rather than shared labels, list their events in event_list for event-scoped "
                "mapping, and see field_coverage"
            )
        elif missing:
            warnings.append("selected event properties are absent from some timeline rows; see field_coverage")
        return {
            "scope": "returned_timeline_rows",
            "row_count": len(events),
            "status": _coverage_status(bool(self.event_fields), bool(events), bool(missing or unmapped)),
            "missing_fields": missing,
            "missing_counts": counts,
            "unmapped_fields": unmapped,
        }

    def _unmapped(self) -> list[str]:
        mapped = set(self.labels).union(*self.event_labels.values())
        # A selected label shared by several properties mixes their values; never certify it.
        return sorted((self.event_fields - mapped - self.known_labels) | (self.event_fields & self.shared_labels))

    def _applies(self, name: str, event: Mapping[str, Any]) -> bool:
        # With event-scoped labels a field counts only on rows whose event maps it.
        if not self.event_labels or name in self.known_labels:
            return True
        return name in self.labels_for(event.get("事件英文名"))


def _coverage_status(requested: bool, observed: bool, gaps: bool) -> str:
    if not requested:
        return "not_requested"
    if not observed:
        return "not_observed"
    return "partial" if gaps else "complete"


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
