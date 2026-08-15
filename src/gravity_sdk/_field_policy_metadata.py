"""Live metadata loading and membership checks for field policy validation."""

from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

from .actionable_error_values import actual_value, live_metadata_miss
from ._field_policy_operations import (
    ANALYSIS_EVENT,
    ANALYSIS_EVENT_INFO,
    ANALYSIS_EVENT_PROPERTY,
    ANALYSIS_SEGMENT,
    ANALYSIS_SEGMENT_HISTORY,
    ANALYSIS_USER_PROPERTY,
)
from ._field_policy_shared import (
    ANALYSIS_FIXED_EVENT_FIELDS,
    ANALYSIS_FIXED_USER_FIELDS,
    AnalysisReferences,
    MetadataLoader,
    MetadataView,
    reject_sensitive_metadata_fields,
    require_dimension_tables,
)
from .errors import GravityInsightError, InputValidationError


_CONTROLLED_READ_SCHEMA = "gravity-insight.read.v1"
_OMITTED_NESTED_CONTAINER_WARNING = re.compile(
    r"uncontracted nested item containers were omitted \(count=[1-9][0-9]*\)"
)
_OMITTED_NESTED_ITEM_KEYS_WARNING = re.compile(
    r"unregistered nested response item keys were omitted \(count=[1-9][0-9]*\)"
)


def wire_property_names(
    rows: Sequence[Mapping[str, Any]], prefix: str
) -> set[str]:
    result: set[str] = set()
    for row in rows:
        name = row.get("name")
        if not isinstance(name, str) or not name or len(name) > 256:
            continue
        result.add(name)
        result.add(f"{prefix}{name}")
    return result


def wire_dimension_tables(
    rows: Sequence[Mapping[str, Any]], prefix: str
) -> dict[str, str]:
    result: dict[str, str] = {}
    for row in rows:
        name = row.get("name")
        table = row.get("dim_using_table_name")
        if (
            isinstance(name, str)
            and name
            and isinstance(table, str)
            and table
            and len(table) <= 256
        ):
            result[name] = table
            result[f"{prefix}{name}"] = table
    return result


def load_view(
    operation_id: str,
    inputs: Mapping[str, Any],
    loader: MetadataLoader,
) -> MetadataView:
    try:
        envelope = loader(operation_id, inputs)
    except GravityInsightError:
        raise InputValidationError(
            "required live field metadata is unavailable; the upstream error is not "
            "echoed because errors may enter logs",
            field="metadata",
            next_action=f"Run `gravity run {operation_id} --input {actual_value(inputs)}` and retry the business request only after metadata succeeds.",
        ) from None
    if not isinstance(envelope, Mapping):
        raise InputValidationError(
            f"actual value: {actual_value(type(envelope).__name__)}; allowed metadata envelope type: object",
            field="metadata",
            next_action=f"Run `gravity run {operation_id} --input {actual_value(inputs)}` and stop if the envelope remains invalid.",
        )
    status = str(envelope.get("status", "error"))
    if status not in {"success", "empty"} and not _usable_segment_projection(
        operation_id, envelope
    ):
        raise InputValidationError(
            f"required live field metadata is unavailable; actual value: {actual_value(status)}; "
            "allowed metadata statuses: \"empty\", \"success\"",
            field="metadata.status",
            next_action=f"Run `gravity run {operation_id} --input {actual_value(inputs)}` and retry the business request only after metadata succeeds.",
        )
    return MetadataView(operation_id, status, tuple(flatten_rows(rows(envelope))))


def _usable_segment_projection(
    operation_id: str, envelope: Mapping[str, Any]
) -> bool:
    """Allow one proven-safe projected segment drift for metadata membership only."""

    if operation_id != ANALYSIS_SEGMENT:
        return False
    if not _controlled_projection_contract_change(
        operation_id, envelope, _OMITTED_NESTED_CONTAINER_WARNING
    ):
        return False
    data = envelope.get("data")
    projected_rows = data.get("list") if isinstance(data, Mapping) else None
    if not isinstance(projected_rows, (list, tuple)) or not projected_rows:
        return False
    return all(
        isinstance(row, Mapping)
        and any(
            isinstance(row.get(key), (str, int))
            and not isinstance(row.get(key), bool)
            and str(row.get(key))
            for key in ("segment_id", "id")
        )
        for row in projected_rows
    )


def _controlled_projection_contract_change(
    operation_id: str,
    envelope: Mapping[str, Any],
    safe_warning: re.Pattern[str],
) -> bool:
    if envelope.get("status") != "contract_changed":
        return False
    if envelope.get("schema_version") != _CONTROLLED_READ_SCHEMA:
        return False
    if (
        envelope.get("operation_id") != operation_id
        or envelope.get("error") is not None
    ):
        return False
    source = envelope.get("source")
    if (
        not isinstance(source, Mapping)
        or source.get("system") != "gravity_insight"
        or not isinstance(source.get("contract_fingerprint"), str)
        or not source.get("contract_fingerprint")
    ):
        return False
    warnings = envelope.get("warnings")
    return (
        isinstance(warnings, (list, tuple))
        and bool(warnings)
        and all(
            isinstance(warning, str) and safe_warning.fullmatch(warning) is not None
            for warning in warnings
        )
    )


def load_event_property_rows(
    event_names: Sequence[str],
    app_id: str,
    loader: MetadataLoader,
) -> tuple[Mapping[str, Any], ...]:
    result: list[Mapping[str, Any]] = []
    for event_name in sorted(set(event_names)):
        result.extend(_load_one_event_property(event_name, app_id, loader))
    return tuple(result)


def _load_one_event_property(
    event_name: str,
    app_id: str,
    loader: MetadataLoader,
) -> tuple[Mapping[str, Any], ...]:
    try:
        envelope = loader(
            ANALYSIS_EVENT_INFO,
            {"app_id": app_id, "event_name": event_name},
        )
    except GravityInsightError:
        raise InputValidationError(
            "required event-specific field metadata is unavailable; "
            "the upstream error is not echoed because errors may enter logs",
            field="event_metadata",
            next_action=f"Run `gravity run {ANALYSIS_EVENT_INFO} --input {actual_value({'app_id': app_id, 'event_name': event_name})}` and retry only after metadata succeeds.",
        ) from None
    if not isinstance(envelope, Mapping):
        raise InputValidationError(
            f"actual value: {actual_value(type(envelope).__name__)}; allowed event-specific metadata envelope type: object",
            field="event_metadata",
            next_action=f"Run `gravity run {ANALYSIS_EVENT_INFO} --input {actual_value({'app_id': app_id, 'event_name': event_name})}` and stop if the envelope remains invalid.",
        )
    status = str(envelope.get("status", "error"))
    if status not in {"success", "empty"} and not _usable_event_info_projection(
        envelope
    ):
        raise InputValidationError(
            f"required event-specific field metadata is unavailable; actual value: {actual_value(status)}; "
            "allowed metadata statuses: \"empty\", \"success\"",
            field="event_metadata.status",
            next_action=f"Run `gravity run {ANALYSIS_EVENT_INFO} --input {actual_value({'app_id': app_id, 'event_name': event_name})}` and retry only after metadata succeeds.",
        )
    data = envelope.get("data")
    properties = data.get("properties") if isinstance(data, Mapping) else None
    if not isinstance(properties, Mapping):
        return ()
    result: list[Mapping[str, Any]] = []
    for category in ("common", "custom", "preset"):
        values = properties.get(category, ())
        if isinstance(values, Mapping):
            values = (values,)
        if isinstance(values, (list, tuple)):
            result.extend(
                flatten_rows(tuple(item for item in values if isinstance(item, Mapping)))
            )
    return tuple(result)


def _usable_event_info_projection(envelope: Mapping[str, Any]) -> bool:
    if not _controlled_projection_contract_change(
        ANALYSIS_EVENT_INFO, envelope, _OMITTED_NESTED_ITEM_KEYS_WARNING
    ):
        return False
    data = envelope.get("data")
    properties = data.get("properties") if isinstance(data, Mapping) else None
    categories = ("common", "custom", "preset")
    if not isinstance(properties, Mapping) or set(properties) != set(categories):
        return False
    for category in categories:
        values = properties[category]
        if not isinstance(values, (list, tuple)):
            return False
        if any(
            not isinstance(item, Mapping)
            or not isinstance(item.get("name"), str)
            or not item.get("name")
            or len(item["name"]) > 256
            for item in values
        ):
            return False
    return True


def rows(envelope: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    data = envelope.get("data")
    raw_rows: Any = data
    if isinstance(data, Mapping):
        raw_rows = data.get("list", data.get("items", ()))
    if not isinstance(raw_rows, (list, tuple)):
        return ()
    return tuple(item for item in raw_rows if isinstance(item, Mapping))


def flatten_rows(rows_value: Sequence[Mapping[str, Any]]):
    for row in rows_value:
        yield row
        for nested_key in ("children", "dim_table"):
            children = row.get(nested_key)
            if isinstance(children, Mapping):
                yield from flatten_rows((children,))
            elif isinstance(children, (list, tuple)):
                yield from flatten_rows(
                    tuple(item for item in children if isinstance(item, Mapping))
                )


def names(
    rows_value: Sequence[Mapping[str, Any]],
    *,
    keys: Sequence[str] = ("name", "cname", "id"),
) -> set[str]:
    result: set[str] = set()
    for row in rows_value:
        for key in keys:
            value = row.get(key)
            if isinstance(value, (str, int)) and not isinstance(value, bool):
                result.add(str(value))
    return result


def enumerable_property_names(rows_value: Sequence[Mapping[str, Any]]) -> set[str]:
    result: set[str] = set()
    for row in rows_value:
        name = row.get("name")
        data_type = row.get("data_type")
        if (
            isinstance(name, str)
            and name
            and isinstance(data_type, str)
            and data_type.upper() in {"STRING", "BOOL", "BOOLEAN", "LIST"}
        ):
            result.add(name)
    return result


def select_rows(
    rows_value: Sequence[Mapping[str, Any]],
    requested: Sequence[str],
    label: str,
) -> tuple[Mapping[str, Any], ...]:
    by_name: dict[str, Mapping[str, Any]] = {}
    for row in rows_value:
        for name in names((row,)):
            by_name[name] = row
    missing = [item for item in requested if item not in by_name]
    if missing:
        raise InputValidationError(
            live_metadata_miss(actual_value(missing)),
            field=label,
            next_action="Run `gravity multidim metadata` and retry with a listed value.",
        )
    return tuple(by_name[item] for item in requested)


def all_exclusion_dimensions(
    rows_value: Sequence[Mapping[str, Any]],
) -> tuple[set[str], bool]:
    dimensions: set[str] = set()
    for row in rows_value:
        value = row.get("exclusion_dims")
        if not isinstance(value, (list, tuple)) or any(
            not isinstance(item, str) for item in value
        ):
            return dimensions, False
        dimensions.update(value)
    return dimensions, True


def validate_analysis_reference_membership(
    app_id: str,
    references: AnalysisReferences,
    metadata_loader: MetadataLoader,
) -> None:
    metadata_inputs = {"app_id": app_id, "page": 1, "page_size": 2_000}
    _validate_events(references, metadata_inputs, metadata_loader)
    _validate_event_fields(app_id, references, metadata_inputs, metadata_loader)
    _validate_user_fields(references, metadata_inputs, metadata_loader)
    _validate_segments(app_id, references, metadata_loader)


def _validate_events(
    references: AnalysisReferences,
    metadata_inputs: Mapping[str, Any],
    loader: MetadataLoader,
) -> None:
    if not references.events:
        return
    allowed = names(load_view(ANALYSIS_EVENT, metadata_inputs, loader).rows, keys=("name",))
    missing = sorted(references.events - allowed)
    if missing:
        raise InputValidationError(
            live_metadata_miss(actual_value(missing), noun="events"),
            field="event_name",
            next_action="Run `gravity metadata events \"\"` and retry with a listed event.",
        )


def _validate_event_fields(
    app_id: str,
    references: AnalysisReferences,
    metadata_inputs: Mapping[str, Any],
    loader: MetadataLoader,
) -> None:
    if not references.event_fields and not references.event_dimension_tables:
        return
    global_rows = load_view(ANALYSIS_EVENT_PROPERTY, metadata_inputs, loader).rows
    unresolved_global = (
        references.event_fields
        - ANALYSIS_FIXED_EVENT_FIELDS
        - names(global_rows, keys=("name",))
    )
    specific_rows = (
        load_event_property_rows(references.events, app_id, loader)
        if unresolved_global or references.event_dimension_tables
        else ()
    )
    property_rows = (*global_rows, *specific_rows)
    unresolved = references.event_fields - ANALYSIS_FIXED_EVENT_FIELDS
    allowed = names(property_rows, keys=("name",))
    missing = sorted(unresolved - allowed)
    if missing:
        raise InputValidationError(
            live_metadata_miss(actual_value(missing), noun="event fields"),
            field="event_fields",
            next_action="Run `gravity metadata properties \"\"` and retry with a listed event field.",
        )
    if unresolved:
        reject_sensitive_metadata_fields(property_rows, unresolved)
    require_dimension_tables(property_rows, references.event_dimension_tables, "event")


def _validate_user_fields(
    references: AnalysisReferences,
    metadata_inputs: Mapping[str, Any],
    loader: MetadataLoader,
) -> None:
    if not references.user_fields and not references.user_dimension_tables:
        return
    properties = load_view(ANALYSIS_USER_PROPERTY, metadata_inputs, loader)
    unresolved = references.user_fields - ANALYSIS_FIXED_USER_FIELDS
    allowed = names(properties.rows, keys=("name",))
    missing = sorted(unresolved - allowed)
    if missing:
        raise InputValidationError(
            live_metadata_miss(actual_value(missing), noun="user fields"),
            field="user_fields",
            next_action="Run `gravity metadata properties \"\"` and retry with a listed user field.",
        )
    if unresolved:
        reject_sensitive_metadata_fields(properties.rows, unresolved)
    require_dimension_tables(properties.rows, references.user_dimension_tables, "user")


def _validate_segments(
    app_id: str,
    references: AnalysisReferences,
    loader: MetadataLoader,
) -> None:
    if not references.segment_fields:
        return
    segments = load_view(
        ANALYSIS_SEGMENT,
        {"app_id": app_id, "page": 1, "page_size": 100},
        loader,
    )
    segment_ids = names(segments.rows, keys=("segment_id", "id"))
    missing = sorted({item[0] for item in references.segment_fields} - segment_ids)
    segment_discovery = (
        f"gravity run {ANALYSIS_SEGMENT} --input "
        f"{actual_value({'app_id': app_id, 'page': 1, 'page_size': 100})}"
    )
    if missing:
        raise InputValidationError(
            live_metadata_miss(actual_value(missing), noun="segment ids"),
            field="segment_id",
            next_action=f"Run `{segment_discovery}` and retry with a listed segment id.",
        )
    for segment_id, segment_type, version_id in references.segment_fields:
        if segment_type != "FIXED_VERSION":
            continue
        history = load_view(
            ANALYSIS_SEGMENT_HISTORY,
            {"segment_id": segment_id, "page": 1, "page_size": 100},
            loader,
        )
        available = names(history.rows, keys=("version_id", "id"))
        if version_id not in available:
            history_discovery = (
                f"gravity run {ANALYSIS_SEGMENT_HISTORY} --input "
                f"{actual_value({'segment_id': segment_id, 'page': 1, 'page_size': 100})}"
            )
            raise InputValidationError(
                live_metadata_miss(actual_value(version_id), noun="versions"),
                field="version_id",
                next_action=f"Run `{history_discovery}` and retry with a listed version id.",
            )


def validate_analysis_property_values(
    property_kind: str,
    inputs: Mapping[str, Any],
    metadata_loader: MetadataLoader,
) -> None:
    app_id = inputs.get("app_id")
    property_name = inputs.get("property_name")
    if not isinstance(app_id, str) or not app_id:
        raise InputValidationError(
            f"actual value: {actual_value(app_id)}; allowed value: a non-empty app_id string",
            field="app_id",
        )
    if not isinstance(property_name, str) or not property_name:
        raise InputValidationError(
            f"actual value: {actual_value(property_name)}; allowed value: a non-empty property name",
            field="property_name",
            next_action="Run `gravity metadata properties \"\"` and retry with an enumerable property.",
        )
    if property_kind == "user":
        _validate_user_property_value(app_id, property_name, metadata_loader)
        return
    _validate_event_property_value(app_id, property_name, inputs, metadata_loader)


def _validate_user_property_value(
    app_id: str, property_name: str, loader: MetadataLoader
) -> None:
    view = load_view(
        ANALYSIS_USER_PROPERTY,
        {"app_id": app_id, "page": 1, "page_size": 100},
        loader,
    )
    available = enumerable_property_names(view.rows)
    if property_name not in available:
        raise InputValidationError(
            live_metadata_miss(
                actual_value(property_name),
                noun="enumerable properties",
                source="enumerable metadata",
            ),
            field="property_name",
            next_action="Run `gravity metadata properties \"\"` and retry with a listed enumerable property.",
        )


def _validate_event_property_value(
    app_id: str,
    property_name: str,
    inputs: Mapping[str, Any],
    loader: MetadataLoader,
) -> None:
    event_names = inputs.get("event_name_list")
    if not isinstance(event_names, (list, tuple)) or not event_names:
        raise InputValidationError(
            f"actual value: {actual_value(event_names)}; allowed value: a non-empty array of event names",
            field="event_name_list",
            next_action="Run `gravity metadata events \"\"` and retry with listed events.",
        )
    event_view = load_view(
        ANALYSIS_EVENT,
        {"app_id": app_id, "page": 1, "page_size": 100},
        loader,
    )
    allowed_events = names(event_view.rows, keys=("name",))
    normalized: list[str] = []
    for event_name in event_names:
        if not isinstance(event_name, str) or event_name not in allowed_events:
            raise InputValidationError(
                live_metadata_miss(actual_value(event_name), noun="events"),
                field="event_name_list[]",
                next_action="Run `gravity metadata events \"\"` and retry with a listed event.",
            )
        normalized.append(event_name)
    for event_name in normalized:
        event_rows = load_event_property_rows((event_name,), app_id, loader)
        available = enumerable_property_names(event_rows)
        if property_name not in available:
            raise InputValidationError(
                live_metadata_miss(
                    actual_value(property_name),
                    noun="enumerable event properties",
                    source="enumerable metadata",
                ),
                field="property_name",
                next_action="Run `gravity metadata properties \"\"` and retry with a listed enumerable event property.",
            )
