"""Manifest-driven read execution, projection, drift checks, and privacy filtering."""

from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any, Callable, Mapping

from .analysis_projection_contract import (
    ANALYSIS_DATE_RESPONSE_KEY_RE,
    ANALYSIS_INDEX_RESPONSE_KEY_RE,
    ANALYSIS_SAFE_RESPONSE_SCALARS,
    funnel_mode_shape_changed,
)
from .drift import ProjectionDrift, projection_drift_status
from .errors import PolicyViolation, UpstreamError
from .models import OperationSpec, ReadResult, SemanticErrorRule
from .multidim import projected_keys
from .registry import PolicyEngine, Registry
from .transport import Transport


_ABSENT = object()
_ANALYSIS_USER_EVENT_OPERATION = "analysis.user_event.list"
_ANALYSIS_AGGREGATE_OPERATIONS = frozenset(
    {
        "analysis.event.query",
        "analysis.funnel.query",
        "analysis.retention.query",
        "analysis.scatter.query",
        "analysis.property.query",
    }
)
_ANALYSIS_NESTED_RESPONSE_KEYS = {
    "analysis.event.query": frozenset(
        {
            "cname", "count",
            "data_type", "date_list",
            "end_date", "event_index",
            "field", "list",
            "name", "start_date",
            "target",
            "total",
            "value",
            "values",
            "阶段总和",
        }
    ),
    "analysis.funnel.query": frozenset(
        {"cnt", "count", "group", "rate", "ratio", "total", "value", "values"}
    ),
    "analysis.retention.query": frozenset(
        {
            "group_cols",
            "init_custom_before_components",
            "init_custom_before_num",
            "init_num",
            "is_total",
            "percent_values",
            "percent_values_loss",
            "values",
            "values_another_event",
            "values_loss",
        }
    ),
    "analysis.scatter.query": frozenset(
        {
            "aggregate_date",
            "count",
            "group",
            "total",
            "val",
            "val_list",
            "val_list_to_aggregate_date_group",
            "value",
            "values",
            "zone_tags",
        }
    ),
    "analysis.property.query": frozenset(
        {"cname", "data_type", "field", "method", "name", "target", "value"}
    ),
}
class ReadExecutor:
    def __init__(self, registry: Registry, policy: PolicyEngine, transport: Transport) -> None:
        self._registry = registry
        self._policy = policy
        self._transport = transport
        self._field_validator: Callable[[OperationSpec, Mapping[str, Any]], None] | None = None
        self._call_guard: Callable[[str], Mapping[str, Any]] | None = None

    def _bind_field_validator(self, validator: Callable[[OperationSpec, Mapping[str, Any]], None]) -> None:
        if not callable(validator):
            raise TypeError("executor field validator must be callable")
        if self._field_validator is not None:
            raise RuntimeError("executor field validator is already bound")
        self._field_validator = validator

    def _bind_call_guard(self, guard: Callable[[str], Mapping[str, Any]]) -> None:
        if not callable(guard):
            raise TypeError("executor call guard must be callable")
        if self._call_guard is not None:
            raise RuntimeError("executor call guard is already bound")
        self._call_guard = guard

    def execute(self, operation_id: str, inputs: Mapping[str, Any] | None = None) -> ReadResult:
        if self._field_validator is None or self._call_guard is None:
            raise PolicyViolation("read executor is not bound to the controlled client")
        self._call_guard(operation_id)
        operation = self._policy.authorize_operation(operation_id)
        values = operation.validate_inputs(inputs)
        self._field_validator(operation, values)
        authorization = self._policy._prepare_request(operation_id, values)
        response = self._transport.request(
            authorization.method,
            authorization.path,
            operation=operation,
            query=authorization.query,
            body=authorization.body,
            authorization=authorization,
        )
        payload = response.payload
        _enforce_semantic_rules(operation, payload)
        projected, drift_warnings, projection_drift = _project(operation, payload, values)
        allow_contracted_identifiers = operation.privacy_policy.classification == "user_level"
        projected = _redact(
            projected,
            operation.privacy_policy.redact_fields,
            allow_contracted_identifiers=allow_contracted_identifiers,
        )
        raw_items = _projected_items(operation, projected)
        items = (
            tuple(
                _redact(
                    item,
                    operation.privacy_policy.redact_fields,
                    allow_contracted_identifiers=allow_contracted_identifiers,
                )
                for item in raw_items
            )
            if isinstance(raw_items, list)
            else ()
        )
        raw_page_info = _path_get(payload, operation.pagination.page_info_path)
        page_info = (
            _redact(
                dict(raw_page_info),
                operation.privacy_policy.redact_fields,
                allow_contracted_identifiers=allow_contracted_identifiers,
            )
            if isinstance(raw_page_info, Mapping)
            else {}
        )
        page = _page_envelope(operation, values, page_info, len(items))
        safe_inputs = {
            key: "[REDACTED]" if spec.sensitive else value
            for key, value in values.items()
            if (spec := operation.fields.get(key)) is not None
        }
        safe_inputs = _redact(
            safe_inputs,
            operation.privacy_policy.redact_fields,
            allow_contracted_identifiers=False,
        )
        warnings: list[str] = list(drift_warnings)
        if operation.stability == "experimental":
            warnings.append("operation contract is experimental")
        is_empty = _is_empty(projected, items)
        status = (
            projection_drift_status(projection_drift)
            if projection_drift
            else "empty"
            if is_empty
            else "success"
        )
        return ReadResult(
            schema_version="gravity-insight.read.v1",
            status=status,
            source={
                "system": "gravity_insight",
                "domain": operation.domain,
                "resource": operation.resource,
                "platform": operation.platform,
                "contract_fingerprint": self._registry.fingerprint(operation_id),
            },
            fetched_at=response.fetched_at,
            schema_fingerprint=_shape_fingerprint(projected),
            contract_version=operation.contract_version,
            request={"inputs": safe_inputs},
            page=page,
            data=projected,
            operation_id=operation.operation_id,
            warnings=tuple(warnings),
            error=None,
            items=items,
            page_info=page_info,
        )


def _enforce_semantic_rules(operation: OperationSpec, payload: Mapping[str, Any]) -> None:
    rules = operation.semantic_error_rules or (
        SemanticErrorRule("code", "not_in", values=(0, 200)),
        SemanticErrorRule("extra.error"),
    )
    for rule in rules:
        current = _path_get(payload, rule.path)
        exists = current is not _ABSENT
        triggered = {
            "equals": exists and current == rule.value,
            "not_equals": exists and current != rule.value,
            "exists": exists,
            "truthy": exists and bool(current),
            "falsy": exists and not bool(current),
            "in": exists and current in rule.values,
            "not_in": exists and current not in rule.values,
        }[rule.operator]
        if triggered:
            raise UpstreamError(rule.message)


def _project(
    operation: OperationSpec,
    payload: Mapping[str, Any],
    values: Mapping[str, Any],
) -> tuple[Any, tuple[str, ...], ProjectionDrift]:
    data = payload.get("data")
    if operation.operation_id == _ANALYSIS_USER_EVENT_OPERATION:
        projected, warnings, changed = _project_analysis_user_event(operation, data, values)
        return projected, warnings, (
            ProjectionDrift.BREAKING if changed else ProjectionDrift.NONE
        )
    if operation.operation_id in _ANALYSIS_AGGREGATE_OPERATIONS:
        projected, warnings, changed = _project_analysis_aggregate(operation, data, values)
        return projected, warnings, (
            ProjectionDrift.BREAKING if changed else ProjectionDrift.NONE
        )
    if operation.response_projection.empty_object_as_empty_result and data == {}:
        return {}, (), ProjectionDrift.NONE
    if operation.response_projection.empty_object_as_empty_page and data == {}:
        data = {
            "list": [],
            "page_info": {
                operation.pagination.page_field: values.get(
                    operation.pagination.page_field, 1
                ),
                operation.pagination.page_size_field: values.get(
                    operation.pagination.page_size_field,
                    operation.pagination.default_page_size,
                ),
                operation.pagination.total_page_field: 1,
                "total_number": 0,
            },
        }
    if operation.response_projection.data_shape == "list":
        if not isinstance(data, list):
            return [], (
                "response data shape changed; the uncontracted value was omitted",
            ), ProjectionDrift.BREAKING
        return _project_list_rows(operation, data, values)
    if not isinstance(data, Mapping):
        return {}, (
            "response data shape changed; the uncontracted value was omitted",
        ), ProjectionDrift.BREAKING
    keys = operation.response_projection.data_keys
    warnings: list[str] = []
    missing_required = [
        key
        for key in operation.response_projection.required_data_keys
        if _path_get(data, key) is _ABSENT
    ]
    drift = ProjectionDrift.BREAKING if missing_required else ProjectionDrift.NONE
    if missing_required:
        warnings.append(
            f"required response data keys are absent (count={len(missing_required)})"
        )
    projected = {}
    for key in keys:
        value = _path_get(data, key)
        if value is not _ABSENT:
            projected[key] = value
        elif key not in operation.response_projection.required_data_keys:
            warnings.append(f"optional response data key is absent: {key}")
    unregistered = sorted(
        str(key)
        for key in set(data)
        - set(keys)
        - set(operation.response_projection.known_omitted_data_keys)
    )
    if unregistered:
        drift = max(drift, ProjectionDrift.ADDITIVE)
        warnings.append(
            f"unregistered response data keys were omitted (count={len(unregistered)})"
        )
    primary_list_name = operation.pagination.list_path.rsplit(".", 1)[-1]
    if not primary_list_name and "list" in operation.response_projection.data_keys:
        primary_list_name = "list"
    if primary_list_name not in operation.response_projection.data_scalar_list_types:
        projected, item_warnings, item_drift = _project_list_rows(operation, projected, values)
        warnings.extend(item_warnings)
        drift = max(drift, item_drift)
    projected, data_warnings, data_drift = _project_data_containers(
        operation,
        projected, values
    )
    warnings.extend(data_warnings)
    drift = max(drift, data_drift)
    return projected, tuple(warnings), drift


def _project_analysis_user_event(
    operation: OperationSpec,
    data: Any,
    values: Mapping[str, Any],
) -> tuple[dict[str, Any], tuple[str, ...], bool]:
    """Project event-flow trees and caller-selected metadata fields."""

    if not isinstance(data, Mapping):
        return {}, ("user event response data shape changed; value was omitted",), True
    declared = set(operation.response_projection.data_keys)
    omitted = set(operation.response_projection.known_omitted_data_keys)
    unknown_top = {str(key) for key in data} - declared - omitted
    warnings: list[str] = []
    changed = bool(unknown_top)
    requested_fields = {
        item
        for item in values.get("fields", ())
        if isinstance(item, str) and item and len(item) <= 256
    }
    if unknown_top:
        warnings.append(
            f"unregistered user event data keys were omitted (count={len(unknown_top)})"
        )

    result: dict[str, Any] = {}
    if "event_timeline" in data and "event_timeline" in declared:
        projected, drift = _project_user_event_timeline(
            data["event_timeline"], requested_fields
        )
        if projected is not _ABSENT:
            result["event_timeline"] = projected
        changed = changed or drift
        if drift:
            warnings.append("unregistered user event timeline values were omitted")
    if "summary" in data and "summary" in declared:
        projected, drift = _project_user_event_summary(data["summary"])
        if projected is not _ABSENT:
            result["summary"] = projected
        changed = changed or drift
        if drift:
            warnings.append("unregistered user event summary values were omitted")
    for key in ("device", "user"):
        if key not in data or key not in declared:
            continue
        allowed = (
            set(operation.response_projection.data_item_keys.get(key, ()))
            | requested_fields
        )
        nested, drift = _project_user_event_profile(data[key], allowed)
        if nested is not _ABSENT:
            result[key] = nested
        else:
            changed = True
            warnings.append(f"invalid contracted user event {key} data was omitted")
        if drift:
            changed = True
            warnings.append(
                f"invalid selected user event {key} values were omitted"
            )
    if "re_attribute_records" in data and "re_attribute_records" in declared:
        allowed = (
            set(
                operation.response_projection.data_item_keys.get(
                    "re_attribute_records", ()
                )
            )
            | requested_fields
        )
        records, drift = _project_user_event_records(
            data["re_attribute_records"], allowed
        )
        if records is not _ABSENT:
            result["re_attribute_records"] = records
        else:
            changed = True
            warnings.append(
                "invalid contracted user event re_attribute_records were omitted"
            )
        if drift:
            changed = True
            warnings.append(
                "invalid selected user event re_attribute values were omitted"
            )
    missing = set(operation.response_projection.required_data_keys) - set(result)
    if missing:
        warnings.append(
            f"required user event response keys are absent (count={len(missing)})"
        )
        changed = True
    return result, tuple(warnings), changed


def _project_user_event_timeline(
    value: Any, requested_fields: set[str]
) -> tuple[Any, bool]:
    if not isinstance(value, (list, tuple)) or len(value) > 10_000:
        return _ABSENT, True
    result: list[dict[str, Any]] = []
    changed = False
    for row in value:
        if not isinstance(row, Mapping):
            changed = True
            continue
        unknown = {str(key) for key in row} - {"timeline", "list"}
        changed = changed or bool(unknown)
        timeline = row.get("timeline")
        events = row.get("list")
        if not _bounded_json_scalar(timeline) or not isinstance(events, (list, tuple)):
            changed = True
            continue
        safe_events: list[dict[str, Any]] = []
        if len(events) > 10_000:
            changed = True
            events = events[:10_000]
        for event in events:
            if not isinstance(event, Mapping):
                changed = True
                continue
            allowed_fields = {"事件名称", "事件时间"} | requested_fields
            safe_event: dict[str, Any] = {}
            for key in allowed_fields:
                if key not in event:
                    continue
                normalized = _bounded_json_contract_value(event[key])
                if normalized is _ABSENT:
                    changed = True
                    continue
                safe_event[key] = normalized
            if len(safe_event) != sum(key in event for key in allowed_fields):
                changed = True
            safe_events.append(safe_event)
        result.append({"timeline": timeline, "list": safe_events})
    return result, changed


def _project_user_event_profile(
    value: Any, allowed_fields: set[str]
) -> tuple[Any, bool]:
    if not isinstance(value, Mapping) or len(value) > 10_000:
        return _ABSENT, True
    result: dict[str, Any] = {}
    changed = False
    for key, item in value.items():
        name = str(key)
        if name not in allowed_fields:
            continue
        normalized = _bounded_json_contract_value(item)
        if normalized is _ABSENT:
            changed = True
            continue
        result[name] = normalized
    return result, changed


def _project_user_event_records(
    value: Any, allowed_fields: set[str]
) -> tuple[Any, bool]:
    if not isinstance(value, (list, tuple)) or len(value) > 10_000:
        return _ABSENT, True
    result: list[dict[str, Any]] = []
    changed = False
    for row in value:
        if not isinstance(row, Mapping):
            changed = True
            continue
        projected, row_changed = _project_user_event_profile(row, allowed_fields)
        if projected is _ABSENT:
            changed = True
            continue
        result.append(projected)
        changed = changed or row_changed
    return result, changed


def _project_user_event_summary(value: Any) -> tuple[Any, bool]:
    if not isinstance(value, (list, tuple)) or len(value) > 10_000:
        return _ABSENT, True
    result: list[dict[str, Any]] = []
    changed = False
    for row in value:
        if not isinstance(row, Mapping):
            changed = True
            continue
        changed = changed or bool({str(key) for key in row} - {"timeline", "cnt", "list"})
        timeline = row.get("timeline")
        count = row.get("cnt")
        items = row.get("list")
        if (
            not _bounded_json_scalar(timeline)
            or not _is_finite_number(count)
            or not isinstance(items, (list, tuple))
        ):
            changed = True
            continue
        safe_items: list[dict[str, Any]] = []
        if len(items) > 10_000:
            changed = True
            items = items[:10_000]
        for item in items:
            if not isinstance(item, Mapping):
                changed = True
                continue
            changed = changed or bool({str(key) for key in item} - {"event", "cnt"})
            event = item.get("event")
            event_count = item.get("cnt")
            if not _bounded_json_scalar(event) or not _is_finite_number(event_count):
                changed = True
                continue
            safe_items.append({"event": event, "cnt": event_count})
        result.append({"timeline": timeline, "cnt": count, "list": safe_items})
    return result, changed


def _bounded_json_scalar(value: Any) -> bool:
    return _is_json_scalar(value) and (
        not isinstance(value, str) or len(value) <= 4_096
    )


def _bounded_json_contract_value(value: Any, *, depth: int = 0) -> Any:
    if depth > 6:
        return _ABSENT
    if _bounded_json_scalar(value):
        return value
    if isinstance(value, (list, tuple)):
        if len(value) > 10_000:
            return _ABSENT
        result: list[Any] = []
        for item in value:
            normalized = _bounded_json_contract_value(item, depth=depth + 1)
            if normalized is _ABSENT:
                return _ABSENT
            result.append(normalized)
        return result
    if isinstance(value, Mapping):
        if len(value) > 1_000:
            return _ABSENT
        blocked = {
            "authorization",
            "access_token",
            "token",
            "cookie",
            "password",
            "secret",
        }
        result: dict[str, Any] = {}
        for key, item in value.items():
            name = str(key)
            if len(name) > 256 or _sensitive_key(
                name,
                blocked,
                allow_contracted_identifiers=True,
            ):
                return _ABSENT
            normalized = _bounded_json_contract_value(item, depth=depth + 1)
            if normalized is _ABSENT:
                return _ABSENT
            result[name] = normalized
        return result
    return _ABSENT


def _project_analysis_aggregate(
    operation: OperationSpec,
    data: Any,
    values: Mapping[str, Any],
) -> tuple[dict[str, Any], tuple[str, ...], bool]:
    """Project dynamic aggregate trees using request-derived response keys."""

    if not isinstance(data, Mapping):
        return (
            {},
            ("analysis response data shape changed; value was omitted",),
            True,
        )
    allowed = set(operation.response_projection.data_keys)
    unknown = (
        {str(key) for key in data}
        - allowed
        - set(operation.response_projection.known_omitted_data_keys)
    )
    blocked = {key.casefold() for key in operation.privacy_policy.redact_fields}
    allow_contracted_identifiers = (
        operation.privacy_policy.classification == "user_level"
    )
    response_keys = _analysis_response_keys(
        operation.operation_id,
        values,
        blocked,
        allow_contracted_identifiers=allow_contracted_identifiers,
    )
    numeric_paths = tuple(
        tuple(path.split(".")) for path in operation.response_projection.numeric_paths
    )
    projected: dict[str, Any] = {}
    dropped = int(funnel_mode_shape_changed(operation, data, values))
    for key in operation.response_projection.data_keys:
        if key not in data:
            continue
        if (
            operation.operation_id == "analysis.property.query"
            and key == "target"
            and data[key] == ""
        ):
            projected[key] = ""
            continue
        normalized, changed = _project_analysis_value(
            data[key],
            blocked=blocked,
            response_keys=response_keys,
            numeric_paths=numeric_paths,
            path=(key,),
            depth=0,
            allow_contracted_identifiers=allow_contracted_identifiers,
        )
        if normalized is _ABSENT:
            dropped += 1
            continue
        projected[key] = normalized
        dropped += int(changed)
    warnings: list[str] = []
    if unknown:
        warnings.append(
            f"unregistered analysis response data keys were omitted (count={len(unknown)})"
        )
    if dropped:
        warnings.append(
            f"unsafe or unbounded analysis response values were omitted (count={dropped})"
        )
    return projected, tuple(warnings), bool(unknown or dropped)


def _project_analysis_value(
    value: Any,
    *,
    blocked: set[str],
    response_keys: set[str],
    numeric_paths: tuple[tuple[str, ...], ...],
    path: tuple[str, ...],
    depth: int,
    allow_contracted_identifiers: bool,
) -> tuple[Any, bool]:
    if depth > 10:
        return _ABSENT, True
    if _is_json_scalar(value):
        if (
            _is_finite_number(value)
            and not allow_contracted_identifiers
            and not _analysis_numeric_path_allowed(path, numeric_paths)
        ):
            return _ABSENT, True
        if isinstance(value, str) and (
            len(value) > 4_096
            or (
                not allow_contracted_identifiers
                and (
                    _sensitive_analysis_scalar(value, blocked)
                    or not _allowed_analysis_response_scalar(value, response_keys)
                )
            )
        ):
            return _ABSENT, True
        return value, False
    if isinstance(value, Mapping):
        if len(value) > 10_000:
            return _ABSENT, True
        result: dict[str, Any] = {}
        changed = False
        for key, item in value.items():
            name = str(key)
            if (
                len(name) > 256
                or _sensitive_key(
                    name,
                    blocked,
                    allow_contracted_identifiers=allow_contracted_identifiers,
                )
                or not _allowed_analysis_response_key(name, response_keys)
            ):
                changed = True
                continue
            normalized, nested_changed = _project_analysis_value(
                item,
                blocked=blocked,
                response_keys=response_keys,
                numeric_paths=numeric_paths,
                path=(*path, name),
                depth=depth + 1,
                allow_contracted_identifiers=allow_contracted_identifiers,
            )
            if normalized is _ABSENT:
                changed = True
                continue
            result[name] = normalized
            changed = changed or nested_changed
        return result, changed
    if isinstance(value, (list, tuple)):
        if len(value) > 100_000:
            return _ABSENT, True
        result: list[Any] = []
        changed = False
        for item in value:
            normalized, nested_changed = _project_analysis_value(
                item,
                blocked=blocked,
                response_keys=response_keys,
                numeric_paths=numeric_paths,
                path=(*path, "[]"),
                depth=depth + 1,
                allow_contracted_identifiers=allow_contracted_identifiers,
            )
            if normalized is _ABSENT:
                changed = True
                continue
            result.append(normalized)
            changed = changed or nested_changed
        return result, changed
    return _ABSENT, True


def _analysis_numeric_path_allowed(
    path: tuple[str, ...],
    numeric_paths: tuple[tuple[str, ...], ...],
) -> bool:
    return any(
        len(pattern) == len(path)
        and all(expected == "*" or expected == actual for expected, actual in zip(pattern, path))
        for pattern in numeric_paths
    )


def _analysis_response_keys(
    operation_id: str,
    values: Mapping[str, Any],
    blocked: set[str],
    *,
    allow_contracted_identifiers: bool,
) -> set[str]:
    """Return only request-derived labels that may name aggregate result slots."""

    result = set(_ANALYSIS_NESTED_RESPONSE_KEYS.get(operation_id, ()))

    def add(value: Any) -> None:
        if (
            isinstance(value, str)
            and value
            and len(value) <= 256
            and not _sensitive_key(
                value,
                blocked,
                allow_contracted_identifiers=allow_contracted_identifiers,
            )
            and (
                allow_contracted_identifiers
                or not _sensitive_analysis_scalar(value, blocked)
            )
        ):
            result.add(value)

    def add_target(value: Any) -> None:
        if not isinstance(value, Mapping):
            return
        for key in ("name", "field", "cname"):
            add(value.get(key))

    def add_query_item(value: Any) -> None:
        if not isinstance(value, Mapping):
            return
        for key in ("event_name", "event_label", "custom_name"):
            add(value.get(key))
        add_target(value.get("target"))

    query_items = values.get("query_item_list")
    if isinstance(query_items, (list, tuple)):
        for item in query_items:
            add_query_item(item)
    custom_items = values.get("custom_query_item_list")
    if isinstance(custom_items, (list, tuple)):
        for item in custom_items:
            if not isinstance(item, Mapping):
                continue
            add(item.get("custom_name"))
            nested = item.get("query_item_list")
            if isinstance(nested, (list, tuple)):
                for query_item in nested:
                    add_query_item(query_item)
    property_item = values.get("query_item")
    if isinstance(property_item, Mapping):
        add(property_item.get("custom_name"))
        add_target(property_item.get("target"))
    groups = values.get("group_by_list")
    if isinstance(groups, (list, tuple)):
        for group in groups:
            if not isinstance(group, Mapping):
                continue
            add(group.get("field"))
            add(group.get("group_by"))
    return result


def _allowed_analysis_response_key(name: str, response_keys: set[str]) -> bool:
    return bool(
        name in response_keys
        or ANALYSIS_DATE_RESPONSE_KEY_RE.fullmatch(name)
        or ANALYSIS_INDEX_RESPONSE_KEY_RE.fullmatch(name)
    )


def _allowed_analysis_response_scalar(value: str, response_keys: set[str]) -> bool:
    stripped = value.strip()
    return bool(
        stripped in response_keys
        or stripped in ANALYSIS_SAFE_RESPONSE_SCALARS
        or ANALYSIS_DATE_RESPONSE_KEY_RE.fullmatch(stripped)
        or re.fullmatch(r"^\d{4}-(?:\d{2}|W\d{2})$", stripped)
        or ANALYSIS_INDEX_RESPONSE_KEY_RE.fullmatch(stripped)
    )


def _sensitive_analysis_scalar(value: str, blocked: set[str]) -> bool:
    stripped = value.strip()
    normalized = stripped.casefold().replace("-", "_")
    if _sensitive_key(normalized, blocked):
        return True
    if ANALYSIS_DATE_RESPONSE_KEY_RE.fullmatch(stripped) or re.fullmatch(
        r"^\d{4}-(?:\d{2}|W\d{2})$", stripped
    ):
        return False
    if "@" in stripped or stripped.startswith(("http://", "https://")):
        return True
    digits = re.sub(r"[\s()+-]", "", stripped)
    return digits.isdigit() and 7 <= len(digits) <= 15


def _project_data_containers(
    operation: OperationSpec,
    projected: Any,
    values: Mapping[str, Any],
) -> tuple[Any, tuple[str, ...], ProjectionDrift]:
    if not isinstance(projected, Mapping):
        return projected, (), ProjectionDrift.NONE
    copied = dict(projected)
    warnings: list[str] = []
    drift = ProjectionDrift.NONE
    copied, path_warnings, path_changed, contracted_roots = _project_data_path_items(
        operation, copied
    )
    warnings.extend(path_warnings)
    if path_changed:
        drift = ProjectionDrift.BREAKING
    primary_list = operation.pagination.list_path.rsplit(".", 1)[-1]
    if not primary_list and "list" in operation.response_projection.data_keys:
        primary_list = "list"
    page_info_name = operation.pagination.page_info_path.rsplit(".", 1)[-1]
    for name, value in tuple(copied.items()):
        if name in contracted_roots:
            continue
        scalar_list_type = operation.response_projection.data_scalar_list_types.get(name)
        if scalar_list_type is not None:
            scalar_list, valid = _project_scalar_list(value, scalar_list_type)
            if valid:
                copied[name] = scalar_list
            else:
                copied.pop(name, None)
                warnings.append("invalid contracted response scalar list was omitted")
                drift = ProjectionDrift.BREAKING
            continue
        if name == primary_list and isinstance(value, list):
            continue
        if name == page_info_name and isinstance(value, Mapping):
            allowed_page_keys = {
                operation.pagination.page_field,
                operation.pagination.page_size_field,
                operation.pagination.total_page_field,
                "total",
                "total_number",
            }
            unknown = {str(key) for key in value} - allowed_page_keys
            invalid_values = {
                str(key)
                for key, item in value.items()
                if str(key) in allowed_page_keys and not _is_json_scalar(item)
            }
            copied[name] = {
                str(key): item
                for key, item in value.items()
                if str(key) in allowed_page_keys and _is_json_scalar(item)
            }
            if unknown or invalid_values:
                warnings.append(
                    "unregistered or non-scalar page_info fields were omitted "
                    f"(count={len(unknown | invalid_values)})"
                )
                drift = max(drift, ProjectionDrift.BREAKING if invalid_values else ProjectionDrift.ADDITIVE)
            continue
        if _is_json_scalar(value):
            continue
        if not isinstance(value, (Mapping, list, tuple)):
            copied.pop(name, None)
            warnings.append("non-JSON response data values were omitted (count=1)")
            drift = ProjectionDrift.BREAKING
            continue
        recursive_allowed = operation.response_projection.recursive_data_item_keys.get(name)
        if recursive_allowed is not None:
            recursive, recursive_unknown, contracted = _project_recursive_collection(
                value,
                recursive_allowed,
                privacy_keys=operation.privacy_policy.redact_fields,
            )
            if not contracted:
                copied.pop(name, None)
                warnings.append("invalid recursive response collection was omitted")
                drift = ProjectionDrift.BREAKING
            else:
                copied[name] = recursive
                if recursive_unknown:
                    warnings.append(
                        "unregistered recursive response item keys were omitted "
                        f"(count={len(recursive_unknown)})"
                    )
                    drift = max(drift, ProjectionDrift.ADDITIVE)
            continue
        static_allowed = operation.response_projection.data_item_keys.get(name)
        dynamic_inputs = operation.response_projection.data_dynamic_item_fields.get(name, ())
        numeric_inputs = operation.response_projection.data_numeric_suffix_item_fields.get(name, ())
        dynamic_allowed = projected_keys((), dynamic_inputs, numeric_inputs, values, value)
        allowed = (
            tuple(dict.fromkeys((*(static_allowed or ()), *sorted(dynamic_allowed))))
            if static_allowed is not None or dynamic_inputs
            else None
        )
        nested, unknown, contracted = _project_nested_item_value(
            value,
            allowed,
            operation.response_projection.nested_item_keys,
            operation.response_projection.known_omitted_nested_item_keys,
            operation.response_projection.opaque_json_item_keys,
        )
        unknown -= set(
            operation.response_projection.known_omitted_data_item_keys.get(name, ())
        )
        if not contracted:
            copied.pop(name, None)
            warnings.append("uncontracted response data containers were omitted (count=1)")
            drift = ProjectionDrift.BREAKING
            continue
        copied[name] = nested
        if unknown:
            warnings.append(
                f"unregistered response data item keys were omitted (count={len(unknown)})"
            )
            drift = max(drift, ProjectionDrift.ADDITIVE)
    return copied, tuple(warnings), drift


def _project_recursive_collection(
    value: Any,
    allowed_keys: tuple[str, ...],
    *,
    privacy_keys: tuple[str, ...],
) -> tuple[Any, set[str], bool]:
    allowed = set(allowed_keys)
    blocked = {key.casefold() for key in privacy_keys}

    def project_row(row: Mapping[Any, Any]) -> tuple[dict[str, Any], set[str]]:
        row_keys = {str(key) for key in row}
        privacy_omitted = {key for key in row_keys if _sensitive_key(key, blocked)}
        unknown = row_keys - allowed - privacy_omitted
        result: dict[str, Any] = {}
        for key, item in row.items():
            name = str(key)
            if name not in allowed:
                continue
            if name == "children":
                nested, nested_unknown, contracted = _project_recursive_collection(
                    item, allowed_keys, privacy_keys=privacy_keys
                )
                if contracted:
                    result[name] = nested
                    unknown.update(nested_unknown)
                else:
                    unknown.add(name)
            elif isinstance(item, (Mapping, list, tuple)) or not _is_json_scalar(item):
                unknown.add(name)
            else:
                result[name] = item
        return result, unknown

    if isinstance(value, Mapping):
        projected, unknown = project_row(value)
        return projected, unknown, True
    if isinstance(value, (list, tuple)):
        if any(not isinstance(item, Mapping) for item in value):
            return None, set(), False
        result: list[dict[str, Any]] = []
        unknown: set[str] = set()
        for item in value:
            projected, item_unknown = project_row(item)
            result.append(projected)
            unknown.update(item_unknown)
        return result, unknown, True
    return None, set(), False


def _project_data_path_items(
    operation: OperationSpec,
    projected: Mapping[str, Any],
) -> tuple[dict[str, Any], tuple[str, ...], bool, set[str]]:
    rules_by_root: dict[str, dict[str, tuple[str, ...]]] = {}
    for path, keys in operation.response_projection.data_path_item_keys.items():
        root, child = path.split(".", 1)
        rules_by_root.setdefault(root, {})[child] = keys
    if not rules_by_root:
        return dict(projected), (), False, set()

    copied = dict(projected)
    warnings: list[str] = []
    changed = False
    for root, child_rules in rules_by_root.items():
        value = projected.get(root)
        if not isinstance(value, Mapping):
            copied.pop(root, None)
            warnings.append("contracted nested response data is absent or invalid")
            changed = True
            continue
        safe_root: dict[str, Any] = {}
        unknown_children = (
            {str(key) for key in value}
            - set(child_rules)
            - set(
                operation.response_projection.known_omitted_data_item_keys.get(
                    root, ()
                )
            )
        )
        if unknown_children:
            warnings.append(
                f"unregistered nested response paths were omitted (count={len(unknown_children)})"
            )
            changed = True
        for child, allowed in child_rules.items():
            if child not in value:
                continue
            nested, unknown, contracted = _project_nested_item_value(
                value[child],
                allowed,
                operation.response_projection.nested_item_keys,
                operation.response_projection.known_omitted_nested_item_keys,
                operation.response_projection.opaque_json_item_keys,
            )
            if not contracted:
                warnings.append("invalid contracted nested response collection was omitted")
                changed = True
                continue
            safe_root[child] = nested
            unknown -= set(
                operation.response_projection.known_omitted_data_item_keys.get(
                    root, ()
                )
            )
            if unknown:
                warnings.append(
                    f"unregistered nested response item keys were omitted (count={len(unknown)})"
                )
                changed = True
        copied[root] = safe_root
    return copied, tuple(warnings), changed, set(rules_by_root)


def _project_list_rows(
    operation: OperationSpec,
    projected: Any,
    values: Mapping[str, Any],
) -> tuple[Any, tuple[str, ...], ProjectionDrift]:
    allowed = projected_keys(
        operation.response_projection.item_keys,
        operation.response_projection.dynamic_item_fields,
        (), values, None,
    )
    known_omitted = set(operation.response_projection.known_omitted_item_keys)
    privacy_blocked = {key.casefold() for key in operation.privacy_policy.redact_fields}
    field_name = operation.pagination.list_path.rsplit(".", 1)[-1]
    if isinstance(projected, Mapping):
        if not field_name or not isinstance(projected.get(field_name), list):
            field_name = "list" if isinstance(projected.get("list"), list) else ""
        rows = projected.get(field_name) if field_name else None
    else:
        rows = projected if isinstance(projected, list) else None
    if not isinstance(rows, list):
        return projected, (), ProjectionDrift.NONE

    allowed.update(projected_keys((), (), operation.response_projection.numeric_suffix_item_fields, values, rows))

    unknown: set[str] = set()
    filtered: list[Any] = []
    non_object_items = 0
    uncontracted_containers = 0
    invalid_scalar_items = 0
    unknown_nested_keys: set[str] = set()
    for row in rows:
        if not isinstance(row, Mapping):
            # List contracts are row/object contracts.  Scalars and nested arrays
            # have no field-level policy surface, so fail closed on schema drift.
            non_object_items += 1
            continue
        row_keys = {str(key) for key in row}
        privacy_omitted = {
            key
            for key in row_keys
            if _sensitive_key(
                key,
                privacy_blocked,
                allow_contracted_identifiers=(
                    operation.privacy_policy.classification == "user_level"
                ),
            )
        }
        unknown.update(row_keys - allowed - known_omitted - privacy_omitted)
        projected_row: dict[str, Any] = {}
        for key, value in row.items():
            name = str(key)
            if name not in allowed:
                continue
            if isinstance(value, (Mapping, list, tuple)):
                if name in operation.response_projection.opaque_json_item_keys:
                    opaque_json, valid = _copy_json_value(value)
                    if valid:
                        projected_row[name] = opaque_json
                    else:
                        uncontracted_containers += 1
                    continue
                scalar_item_type = operation.response_projection.scalar_list_item_types.get(name)
                if scalar_item_type is not None:
                    scalar_list, valid = _project_scalar_list(value, scalar_item_type)
                    if valid:
                        projected_row[name] = scalar_list
                    else:
                        uncontracted_containers += 1
                    continue
                nested, nested_unknown, contracted = _project_nested_item_value(
                    value,
                    operation.response_projection.nested_item_keys.get(name),
                    operation.response_projection.nested_item_keys,
                    operation.response_projection.known_omitted_nested_item_keys,
                    operation.response_projection.opaque_json_item_keys,
                )
                if not contracted:
                    uncontracted_containers += 1
                    continue
                projected_row[name] = nested
                nested_unknown -= set(
                    operation.response_projection.known_omitted_nested_item_keys.get(
                        name, ()
                    )
                )
                unknown_nested_keys.update(nested_unknown)
            elif _is_json_scalar(value):
                projected_row[name] = value
            else:
                invalid_scalar_items += 1
        filtered.append(projected_row)
    warnings: list[str] = []
    if not allowed:
        warnings.append("list rows were suppressed because the operation has no item allowlist")
    if unknown:
        warnings.append(f"unregistered list item keys were omitted (count={len(unknown)})")
    if non_object_items:
        warnings.append(f"non-object list items were omitted (count={non_object_items})")
    if uncontracted_containers:
        warnings.append(
            "uncontracted nested item containers were omitted "
            f"(count={uncontracted_containers})"
        )
    if invalid_scalar_items:
        warnings.append(
            f"non-JSON scalar item values were omitted (count={invalid_scalar_items})"
        )
    if unknown_nested_keys:
        warnings.append(
            "unregistered nested item keys were omitted "
            f"(count={len(unknown_nested_keys)})"
        )
    breaking = bool(
        non_object_items
        or uncontracted_containers
        or invalid_scalar_items
        or unknown_nested_keys
        or (rows and not allowed)
    )
    drift = ProjectionDrift.NONE
    if unknown:
        drift = ProjectionDrift.ADDITIVE
    if breaking and drift < ProjectionDrift.BREAKING:
        drift = ProjectionDrift.BREAKING
    if isinstance(projected, Mapping):
        copied = dict(projected)
        copied[field_name] = filtered
        return copied, tuple(warnings), drift
    return filtered, tuple(warnings), drift


def _project_scalar_list(value: Any, item_type: str) -> tuple[list[Any] | None, bool]:
    if not isinstance(value, (list, tuple)):
        return None, False
    checks = {
        "string": lambda item: isinstance(item, str),
        "integer": lambda item: isinstance(item, int) and not isinstance(item, bool),
        "number": lambda item: _is_finite_number(item),
        "boolean": lambda item: isinstance(item, bool),
    }
    check = checks[item_type]
    if any(not check(item) for item in value):
        return None, False
    return list(value), True


def _copy_json_value(value: Any, *, depth: int = 0) -> tuple[Any, bool]:
    if depth > 32:
        return None, False
    if _is_json_scalar(value):
        return value, True
    if isinstance(value, Mapping):
        copied: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                return None, False
            nested, valid = _copy_json_value(item, depth=depth + 1)
            if not valid:
                return None, False
            copied[key] = nested
        return copied, True
    if isinstance(value, (list, tuple)):
        copied_items: list[Any] = []
        for item in value:
            nested, valid = _copy_json_value(item, depth=depth + 1)
            if not valid:
                return None, False
            copied_items.append(nested)
        return copied_items, True
    return None, False


def _project_nested_item_value(
    value: Any, allowed_keys: tuple[str, ...] | None,
    nested_item_keys: Mapping[str, tuple[str, ...]] | None = None,
    known_omitted_nested_item_keys: Mapping[str, tuple[str, ...]] | None = None,
    opaque_json_item_keys: tuple[str, ...] | None = None,
) -> tuple[Any, set[str], bool]:
    """Project one contracted nested object or list of objects.

    Scalar lists are intentionally unsupported: the manifest must first gain a
    typed scalar-list contract instead of treating an arbitrary container as safe.
    """

    if allowed_keys is None:
        return None, set(), False
    allowed = set(allowed_keys)
    nested_contracts = nested_item_keys or {}
    known_omitted_contracts = known_omitted_nested_item_keys or {}
    opaque_contracts = set(opaque_json_item_keys or ())

    def project_mapping(item: Mapping[Any, Any]) -> tuple[dict[str, Any], set[str]]:
        unknown = {str(key) for key in item} - allowed
        result: dict[str, Any] = {}
        for key, nested_value in item.items():
            name = str(key)
            if name not in allowed:
                continue
            if isinstance(nested_value, (Mapping, list, tuple)):
                if name in opaque_contracts:
                    opaque_json, valid = _copy_json_value(nested_value)
                    if valid:
                        result[name] = opaque_json
                    else:
                        unknown.add(name)
                    continue
                nested_allowed = nested_contracts.get(name)
                nested, nested_unknown, contracted = _project_nested_item_value(
                    nested_value,
                    nested_allowed,
                    nested_contracts,
                    known_omitted_contracts,
                    opaque_json_item_keys,
                )
                if not contracted:
                    unknown.add(name)
                    continue
                nested_unknown -= set(known_omitted_contracts.get(name, ()))
                unknown.update(nested_unknown)
                result[name] = nested
                continue
            if not _is_json_scalar(nested_value):
                unknown.add(name)
                continue
            result[name] = nested_value
        return result, unknown

    if isinstance(value, Mapping):
        projected, unknown = project_mapping(value)
        return projected, unknown, True
    if isinstance(value, (list, tuple)):
        if not value:
            return [], set(), True
        projected_items: list[dict[str, Any]] = []
        unknown: set[str] = set()
        for item in value:
            if not isinstance(item, Mapping):
                return None, set(), False
            projected, item_unknown = project_mapping(item)
            projected_items.append(projected)
            unknown.update(item_unknown)
        return projected_items, unknown, True
    return None, set(), False


def _is_finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and (
        not isinstance(value, float) or math.isfinite(value)
    )


def _is_json_scalar(value: Any) -> bool:
    return (
        value is None
        or isinstance(value, (str, bool))
        or isinstance(value, int)
        or (isinstance(value, float) and math.isfinite(value))
    )


def _projected_items(operation: OperationSpec, projected: Any) -> list[Any] | object:
    if isinstance(projected, list):
        return projected
    if isinstance(projected, Mapping):
        field_name = operation.pagination.list_path.rsplit(".", 1)[-1]
        if field_name and isinstance(projected.get(field_name), list):
            return projected[field_name]
        if isinstance(projected.get("list"), list):
            return projected["list"]
    return _ABSENT


def _path_get(value: Any, path: str) -> Any:
    if not path:
        return value
    current = value
    parts = path.split(".")
    # Response data keys are conventionally relative to data; JSON paths may be absolute.
    if parts and parts[0] == "data" and isinstance(current, Mapping) and "data" not in current:
        parts = parts[1:]
    for part in parts:
        if not isinstance(current, Mapping) or part not in current:
            return _ABSENT
        current = current[part]
    return current


def _redact(
    value: Any,
    keys: tuple[str, ...],
    *,
    allow_contracted_identifiers: bool = False,
) -> Any:
    blocked = {key.casefold() for key in keys}
    if isinstance(value, Mapping):
        semantic_field = value.get("field")
        if isinstance(semantic_field, str) and _sensitive_filter_field(
            semantic_field,
            blocked,
            allow_contracted_identifiers=allow_contracted_identifiers,
        ):
            return {
                "field": "[REDACTED]",
                **({"operator": value["operator"]} if "operator" in value else {}),
                "redacted": True,
            }
        return {
            str(key): _redact(
                item,
                keys,
                allow_contracted_identifiers=allow_contracted_identifiers,
            )
            for key, item in value.items()
            if not _sensitive_key(
                str(key),
                blocked,
                allow_contracted_identifiers=allow_contracted_identifiers,
            )
        }
    if isinstance(value, list):
        return [
            _redact(
                item,
                keys,
                allow_contracted_identifiers=allow_contracted_identifiers,
            )
            for item in value
        ]
    if isinstance(value, tuple):
        return [
            _redact(
                item,
                keys,
                allow_contracted_identifiers=allow_contracted_identifiers,
            )
            for item in value
        ]
    return value


def _sensitive_filter_field(
    field: str,
    blocked: set[str],
    *,
    allow_contracted_identifiers: bool = False,
) -> bool:
    normalized = field.casefold().replace("-", "_")
    return _sensitive_key(
        normalized,
        blocked,
        allow_contracted_identifiers=allow_contracted_identifiers,
    ) or (not allow_contracted_identifiers and normalized in {
        "account_name",
        "advertiser_name",
        "company_name",
        "operator_name",
        "real_name",
        "user_name",
        "username",
    })


def _sensitive_key(
    key: str,
    blocked: set[str],
    *,
    allow_contracted_identifiers: bool = False,
) -> bool:
    normalized = key.casefold().replace("-", "_")
    if allow_contracted_identifiers:
        return normalized in blocked or normalized in {
            "authorization",
            "cookie",
            "password",
            "secret",
            "token",
        } or normalized.endswith(
            (
                "_authorization",
                "_cookie",
                "_password",
                "_secret",
                "_token",
            )
        )
    if normalized in blocked or normalized in {
        "album_authority",
        "authorization",
        "cookie",
        "designer_id",
        "designer_name",
        "email",
        "email_address",
        "mobile",
        "mobile_phone",
        "password",
        "phone",
        "phone_number",
        "secret",
        "token",
        "url",
    }:
        return True
    return normalized.endswith(
        (
            "_authorization",
            "_cookie",
            "_email",
            "_designer_id",
            "_designer_name",
            "_mobile",
            "_password",
            "_phone",
            "_secret",
            "_token",
            "_url",
            "_user_id",
            "_user_name",
        )
    )


def _page_envelope(
    operation: OperationSpec,
    values: Mapping[str, Any],
    page_info: Mapping[str, Any],
    item_count: int,
) -> Mapping[str, Any] | None:
    if operation.pagination.kind == "none":
        return None
    page_number = page_info.get(operation.pagination.page_field, values.get(operation.pagination.page_field, 1))
    page_size = page_info.get(
        operation.pagination.page_size_field,
        values.get(operation.pagination.page_size_field, operation.pagination.default_page_size),
    )
    total_pages = page_info.get(operation.pagination.total_page_field)
    total_items = page_info.get("total_number", page_info.get("total"))
    has_more = bool(
        isinstance(page_number, int)
        and isinstance(total_pages, int)
        and page_number < total_pages
    )
    return {
        "number": page_number,
        "size": page_size,
        "item_count": item_count,
        "total_pages": total_pages,
        "total_items": total_items,
        "has_more": has_more,
    }


def _is_empty(data: Any, items: tuple[Any, ...]) -> bool:
    if items:
        return False
    if isinstance(data, (list, tuple, set)):
        return not data
    if isinstance(data, Mapping):
        if not data:
            return True
        if isinstance(data.get("list"), list):
            return not data["list"]
        return bool(data) and all(value in (None, "", [], {}) for value in data.values())
    return data is None


def _shape(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _shape(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, list):
        item_shapes = {_canonical(_shape(item)) for item in value}
        return {"type": "array", "items": [json.loads(item) for item in sorted(item_shapes)]}
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    return "string"


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _shape_fingerprint(value: Any) -> str:
    return hashlib.sha256(_canonical(_shape(value)).encode("utf-8")).hexdigest()
