"""Manifest-driven read execution, projection, drift checks, and privacy filtering."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Callable, Mapping

from .analysis_projection_contract import (
    ANALYSIS_DATE_RESPONSE_KEY_RE,
    ANALYSIS_INDEX_RESPONSE_KEY_RE,
    ANALYSIS_SAFE_RESPONSE_SCALARS,
    allowed_analysis_response_key as _allowed_analysis_response_key,
    analysis_group_shape,
    funnel_mode_shape_changed,
    nested_analysis_response_keys,
    operation_uses_dynamic_aggregate,
)
from .drift import ProjectionDrift, projection_drift_status
from .errors import ManifestError, PolicyViolation, error_for_status
from .list_row_projection import _project_list_rows
from .material_asset_source import _capture_private_material_asset_rows
from .models import (
    OperationSpec,
    ReadResult,
    _RESPONSE_PROJECTOR_NAMES,
    safe_read_inputs,
)
from .page_envelope import page_envelope
from .read_result_support import pagination_result_dimensions, result_warnings
from .receipt import capture_http_receipt_references, record_response_drift
from .registry import PolicyEngine, Registry
from .response_drift import ResponseDriftRecorder
from .response_projection import (
    _is_finite_number,
    _is_json_scalar,
    _project_data_containers,
)
from . import response_redaction_policy as _response_redaction
from .semantic_status import (
    SEMANTIC_EXPLICIT_EMPTY,
    enforce_semantic_rules as _enforce_semantic_rules,
)
from .transport import Transport
from .user_event_projection import project_analysis_user_event


_ABSENT = object()
class ReadExecutor:
    def __init__(self, registry: Registry, policy: PolicyEngine, transport: Transport) -> None:
        self._registry = registry
        self._policy = policy
        self._transport = transport
        self._field_validator: Callable[[OperationSpec, Mapping[str, Any]], None] | None = None
        self._call_guard: Callable[[str], Mapping[str, Any]] | None = None

    def _bind_field_validator(
        self,
        validator: Callable[[OperationSpec, Mapping[str, Any]], None],
    ) -> None:
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
        with capture_http_receipt_references() as http_receipts:
            response = self._transport.request(
                authorization.method, authorization.path, operation=operation,
                query=authorization.query, body=authorization.body,
                authorization=authorization,
            )
        payload = response.payload
        semantic_status = _enforce_semantic_rules(operation, payload, http_receipts, values)
        _capture_private_material_asset_rows(operation_id, payload)
        projected, drift_warnings, projection_drift, response_drift = _project_response(
            operation, payload, values, semantic_status,
            getattr(response, "status_code", 200), http_receipts,
        )
        projected = _redact(
            projected,
            operation.privacy_policy.redact_fields,
            allow_contracted_identifiers=True,
        )
        raw_items = _projected_items(operation, projected)
        items = (
            tuple(
                _redact(
                    item,
                    operation.privacy_policy.redact_fields,
                    allow_contracted_identifiers=True,
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
                allow_contracted_identifiers=True,
            )
            if isinstance(raw_page_info, Mapping)
            else {}
        )
        page = page_envelope(operation, values, page_info, len(items))
        safe_inputs = safe_read_inputs(operation, values, _redact)
        status = _read_status(getattr(response, "status_code", 200), semantic_status, projection_drift, _is_empty(projected, items))
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
            fetched_at=response.fetched_at, schema_fingerprint=_shape_fingerprint(projected),
            contract_version=operation.contract_version, request={"inputs": safe_inputs},
            page=page,
            data=projected,
            operation_id=operation.operation_id,
            warnings=result_warnings(operation, drift_warnings), error=error_for_status(status, operation_id=operation.operation_id),
            items=items, page_info=page_info,
            http_receipts=tuple(http_receipts),
            response_drift=response_drift,
            **pagination_result_dimensions(operation, page, all_pages=False),
        )


def _read_status(
    http_status: int, semantic_status: str,
    projection_drift: ProjectionDrift, is_empty: bool,
) -> str:
    if http_status == 204 or semantic_status == SEMANTIC_EXPLICIT_EMPTY:
        return "empty"
    if projection_drift is ProjectionDrift.BREAKING:
        return projection_drift_status(projection_drift)
    return "empty" if is_empty else "success"


def _project_response(
    operation: OperationSpec, payload: Mapping[str, Any], values: Mapping[str, Any],
    semantic_status: str, http_status: int, http_receipts: Any,
) -> tuple[Any, tuple[str, ...], ProjectionDrift, Mapping[str, Any] | None]:
    if http_status == 204 or semantic_status == SEMANTIC_EXPLICIT_EMPTY:
        return _empty_projection(operation), (), ProjectionDrift.NONE, None
    result = _project(operation, payload, values)
    record_response_drift(http_receipts, result[3])
    return result


def _empty_projection(operation: OperationSpec) -> Any:
    if operation.response_projection.data_shape == "list":
        return []
    item_field = operation.pagination.items_field
    if operation.pagination.kind != "none" or item_field in operation.response_projection.data_keys:
        return {item_field: []}
    return {}


def _project(
    operation: OperationSpec,
    payload: Mapping[str, Any],
    values: Mapping[str, Any],
) -> tuple[Any, tuple[str, ...], ProjectionDrift, Mapping[str, Any] | None]:
    data = payload.get("data")
    recorder = ResponseDriftRecorder()
    projector_name = _RESPONSE_PROJECTOR_NAMES.get(operation.operation_id)
    projector = globals().get(projector_name)
    if projector_name is not None and not callable(projector):
        raise ManifestError("runtime response projector binding names an unavailable projector")
    if projector is not None:
        result = projector(operation, data, values, recorder)
        return *result, recorder.to_contract()
    if operation_uses_dynamic_aggregate(operation):
        result = _project_analysis_aggregate(operation, data, values, recorder)
        return *result, recorder.to_contract()
    if operation.response_projection.empty_object_as_empty_result and data == {}:
        return {}, (), ProjectionDrift.NONE, None
    data = _normalize_empty_page(operation, data, values)
    if operation.response_projection.data_shape == "list":
        if not isinstance(data, list):
            return [], (
                "response data shape changed; the uncontracted value was omitted",
            ), ProjectionDrift.BREAKING, None
        result = _project_list_rows(operation, data, values, recorder)
        return *result, recorder.to_contract()
    if not isinstance(data, Mapping):
        return {}, (
            "response data shape changed; the uncontracted value was omitted",
        ), ProjectionDrift.BREAKING, None
    result = _project_mapping_data(operation, data, values, recorder)
    return *result, recorder.to_contract()


def _normalize_empty_page(
    operation: OperationSpec, data: Any, values: Mapping[str, Any]
) -> Any:
    if not operation.response_projection.empty_object_as_empty_page or data != {}:
        return data
    return {
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


def _project_mapping_data(
    operation: OperationSpec,
    data: Mapping[str, Any],
    values: Mapping[str, Any],
    recorder: ResponseDriftRecorder,
) -> tuple[Any, tuple[str, ...], ProjectionDrift]:
    projection = operation.response_projection
    required = set(projection.required_data_keys)
    missing = [key for key in required if _path_get(data, key) is _ABSENT]
    drift = ProjectionDrift.BREAKING if missing else ProjectionDrift.NONE
    warnings = (
        [f"required response data keys are absent (count={len(missing)})"]
        if missing else []
    )
    projected: dict[str, Any] = {}
    for key in projection.data_keys:
        value = _path_get(data, key)
        if value is not _ABSENT:
            projected[key] = value
        elif key not in required:
            warnings.append(f"optional response data key is absent: {key}")
    unknown = {str(key) for key in data} - set(projection.data_keys) - set(
        projection.known_omitted_data_keys
    )
    if unknown:
        recorder.add_unknown_fields(("data",), data, unknown)
        warnings.append(
            f"unregistered response data keys were omitted (count={len(unknown)})"
        )
        drift = max(drift, ProjectionDrift.ADDITIVE)
    primary = operation.pagination.list_path.rsplit(".", 1)[-1]
    if not primary and "list" in projection.data_keys:
        primary = "list"
    if primary not in projection.data_scalar_list_types:
        projected, item_warnings, item_drift = _project_list_rows(
            operation, projected, values, recorder
        )
        warnings.extend(item_warnings)
        drift = max(drift, item_drift)
    projected, nested_warnings, nested_drift = _project_data_containers(
        operation, projected, values, recorder
    )
    warnings.extend(nested_warnings)
    return projected, tuple(warnings), max(drift, nested_drift)


def _project_analysis_aggregate(
    operation: OperationSpec,
    data: Any,
    values: Mapping[str, Any],
    recorder: ResponseDriftRecorder,
) -> tuple[dict[str, Any], tuple[str, ...], ProjectionDrift]:
    """Project dynamic aggregate trees using request-derived response keys."""

    if not isinstance(data, Mapping):
        return (
            {},
            ("analysis response data shape changed; value was omitted",),
            ProjectionDrift.BREAKING,
        )
    allowed = set(operation.response_projection.data_keys)
    unknown = (
        {str(key) for key in data}
        - allowed
        - set(operation.response_projection.known_omitted_data_keys)
    )
    recorder.add_unknown_fields(("data",), data, unknown)
    blocked = {key.casefold() for key in operation.privacy_policy.redact_fields}
    allow_contracted_identifiers = (
        operation.privacy_policy.classification == "user_level"
    )
    response_keys = _analysis_response_keys(
        operation.response_projection,
        values,
        blocked,
        allow_contracted_identifiers=allow_contracted_identifiers,
    )
    numeric_paths = tuple(
        tuple(path.split(".")) for path in operation.response_projection.numeric_paths
    )
    projected: dict[str, Any] = {}
    dropped = int(funnel_mode_shape_changed(operation, data, values))
    drift = ProjectionDrift.BREAKING if dropped else (
        ProjectionDrift.ADDITIVE if unknown else ProjectionDrift.NONE
    )
    for key in operation.response_projection.data_keys:
        if key not in data:
            continue
        if (
            analysis_group_shape(operation.response_projection) == "property"
            and key == "target"
            and data[key] == ""
        ):
            projected[key] = ""
            continue
        normalized, value_drift = _project_analysis_value(
            data[key],
            blocked=blocked,
            response_keys=response_keys,
            numeric_paths=numeric_paths,
            path=(key,),
            depth=0,
            allow_contracted_identifiers=allow_contracted_identifiers,
            recorder=recorder,
        )
        if normalized is _ABSENT:
            dropped += 1
            continue
        projected[key] = normalized
        dropped += int(value_drift is ProjectionDrift.BREAKING)
        drift = max(drift, value_drift)
    warnings: list[str] = []
    if unknown:
        warnings.append(
            f"unregistered analysis response data keys were omitted (count={len(unknown)})"
        )
    if dropped:
        warnings.append(
            f"unsafe or unbounded analysis response values were omitted (count={dropped})"
        )
    return projected, tuple(warnings), drift


def _project_analysis_value(
    value: Any,
    *,
    blocked: set[str],
    response_keys: set[str],
    numeric_paths: tuple[tuple[str, ...], ...],
    path: tuple[str, ...],
    depth: int,
    allow_contracted_identifiers: bool,
    recorder: ResponseDriftRecorder,
) -> tuple[Any, ProjectionDrift]:
    if depth > 10:
        return _ABSENT, ProjectionDrift.BREAKING
    if _is_json_scalar(value):
        normalized = _project_analysis_scalar(
            value, blocked, response_keys, numeric_paths, path,
            allow_contracted_identifiers,
        )
        drift = (
            ProjectionDrift.BREAKING
            if normalized is _ABSENT
            else ProjectionDrift.NONE
        )
        return normalized, drift
    arguments = (
        blocked, response_keys, numeric_paths, path, depth,
        allow_contracted_identifiers, recorder,
    )
    if isinstance(value, Mapping):
        return _project_analysis_mapping(value, *arguments)
    if isinstance(value, (list, tuple)):
        return _project_analysis_sequence(value, *arguments)
    return _ABSENT, ProjectionDrift.BREAKING


def _project_analysis_scalar(
    value: Any,
    blocked: set[str],
    response_keys: set[str],
    numeric_paths: tuple[tuple[str, ...], ...],
    path: tuple[str, ...],
    allow_identifiers: bool,
) -> Any:
    if (
        _is_finite_number(value)
        and not allow_identifiers
        and not _analysis_numeric_path_allowed(path, numeric_paths)
    ):
        return _ABSENT
    if isinstance(value, str) and (
        len(value) > 4_096
        or not allow_identifiers
        and (
            _sensitive_analysis_scalar(value, blocked)
            or not _allowed_analysis_response_scalar(value, response_keys)
        )
    ):
        return _ABSENT
    return value


def _project_analysis_mapping(
    value: Mapping[Any, Any],
    blocked: set[str],
    response_keys: set[str],
    numeric_paths: tuple[tuple[str, ...], ...],
    path: tuple[str, ...],
    depth: int,
    allow_identifiers: bool,
    recorder: ResponseDriftRecorder,
) -> tuple[Any, ProjectionDrift]:
    if len(value) > 10_000:
        return _ABSENT, ProjectionDrift.BREAKING
    result: dict[str, Any] = {}
    drift = ProjectionDrift.NONE
    for key, item in value.items():
        name = str(key)
        if (
            len(name) > 256
            or _sensitive_key(
                name, blocked,
                allow_contracted_identifiers=allow_identifiers,
            )
            or not _allowed_analysis_response_key(name, response_keys, path)
        ):
            audit_path = ("data", *("*" if part == "[]" else part for part in path))
            recorder.add_unknown_fields(audit_path, value, {name})
            drift = max(drift, ProjectionDrift.ADDITIVE)
            continue
        normalized, nested_drift = _project_analysis_value(
            item, blocked=blocked, response_keys=response_keys,
            numeric_paths=numeric_paths, path=(*path, name), depth=depth + 1,
            allow_contracted_identifiers=allow_identifiers, recorder=recorder,
        )
        if normalized is _ABSENT:
            drift = ProjectionDrift.BREAKING
        else:
            result[name] = normalized
            drift = max(drift, nested_drift)
    return result, drift


def _project_analysis_sequence(
    value: tuple[Any, ...] | list[Any],
    blocked: set[str],
    response_keys: set[str],
    numeric_paths: tuple[tuple[str, ...], ...],
    path: tuple[str, ...],
    depth: int,
    allow_identifiers: bool,
    recorder: ResponseDriftRecorder,
) -> tuple[Any, ProjectionDrift]:
    if len(value) > 100_000:
        return _ABSENT, ProjectionDrift.BREAKING
    result: list[Any] = []
    drift = ProjectionDrift.NONE
    for item in value:
        normalized, nested_drift = _project_analysis_value(
            item, blocked=blocked, response_keys=response_keys,
            numeric_paths=numeric_paths, path=(*path, "[]"), depth=depth + 1,
            allow_contracted_identifiers=allow_identifiers, recorder=recorder,
        )
        if normalized is _ABSENT:
            drift = ProjectionDrift.BREAKING
        else:
            result.append(normalized)
            drift = max(drift, nested_drift)
    return result, drift


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
    projection: Any,
    values: Mapping[str, Any],
    blocked: set[str],
    *,
    allow_contracted_identifiers: bool,
) -> set[str]:
    """Return only request-derived labels that may name aggregate result slots."""

    result = set(nested_analysis_response_keys(projection))

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


def _allowed_analysis_response_scalar(value: str, response_keys: set[str]) -> bool:
    stripped = value.strip()
    return bool(
        stripped in response_keys
        or stripped in ANALYSIS_SAFE_RESPONSE_SCALARS
        or ANALYSIS_DATE_RESPONSE_KEY_RE.fullmatch(stripped)
        or ANALYSIS_INDEX_RESPONSE_KEY_RE.fullmatch(stripped)
    )


def _sensitive_analysis_scalar(value: str, blocked: set[str]) -> bool:
    stripped = value.strip()
    normalized = stripped.casefold().replace("-", "_")
    if _sensitive_key(normalized, blocked):
        return True
    if ANALYSIS_DATE_RESPONSE_KEY_RE.fullmatch(stripped):
        return False
    if "@" in stripped or stripped.startswith(("http://", "https://")):
        return True
    digits = re.sub(r"[\s()+-]", "", stripped)
    return digits.isdigit() and 7 <= len(digits) <= 15


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
        return (
            normalized in _response_redaction.RESPONSE_CREDENTIALS
            or normalized.endswith(_response_redaction.RESPONSE_CREDENTIAL_SUFFIXES)
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
