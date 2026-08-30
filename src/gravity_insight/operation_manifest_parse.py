"""Private parsers for operation-manifest dataclasses in models.py.

These helpers keep OperationSpec.from_dict, InputField.from_value,
InputField.validate, and load_operation_manifest below the function SLOC
and complexity ratchets. Callers stay on models.py; error types and
message text are unchanged.
"""

from __future__ import annotations

import json
import re
import string
from pathlib import Path
from typing import Any, Mapping, Sequence

from .errors import ManifestError
from .operation_input_field import (
    mapping_or_error as _mapping,
    parse_input_field,
    sequence_or_empty as _sequence_or_empty,
    validate_input_field,
)
from .analysis_projection_contract import validate_group_identity_invariant
from .operation_effect_policy import validate_operation_effect
from .projection_validation import validate_projection_bindings


_OPERATION_ID_RE = re.compile(r"^[a-z][a-z0-9_.-]{2,127}$")
_SAFE_PATH_RE = re.compile(r"^/[A-Za-z0-9_{}./-]+/$")
_READ_METHODS = frozenset({"GET", "POST"})
_STABILITY_VALUES = frozenset({
    "stable", "experimental", "permission_unavailable", "blocked_privacy",
    "blocked_write", "deprecated",
})
_NON_EXECUTABLE_STABILITIES = frozenset(
    {"permission_unavailable", "blocked_privacy", "blocked_write", "deprecated"}
)



def parse_operation_spec(cls: Any, value: Mapping[str, Any], models: Any) -> Any:
    config = _mapping(value, "operation")
    operation_id, method, path = _parse_operation_identity(config)
    fields = _parse_input_fields(config, models.InputField)
    names = models._input_field_names(fields)
    request = models.RequestSpec.from_dict(config.get("request", {}))
    _validate_request_bindings(path, request, names)
    response_projection = models.ResponseProjection.from_dict(
        config.get("response_projection", {})
    )
    validate_projection_bindings(response_projection, names)
    raw_rules = _parse_semantic_error_rules(config)
    stability, executable, block_reason, effect = _parse_operation_flags(config)
    validate_group_identity_invariant(
        fields,
        response_projection,
        executable=executable,
        effect=effect,
    )
    pagination = models.PaginationSpec.from_dict(config.get("pagination"))
    _validate_projection_normalization(response_projection, pagination)
    _validate_stable_pagination(stability, pagination)
    required_parent = models.RequiredParent.from_value(config.get("required_parent"))
    _validate_required_parent_inputs(required_parent, names)
    live_probe = models.LiveProbe.from_value(config.get("live_probe"))
    validate_operation_effect(
        stability=stability, effect=effect, executable=executable,
        non_executable_stability=stability in _NON_EXECUTABLE_STABILITIES,
        response_projection=response_projection, live_probe=live_probe,
    )
    _validate_live_probe_inputs(live_probe, fields, names, request)
    return cls(
        operation_id=operation_id,
        domain=_string(config.get("domain"), "domain"),
        resource=_string(config.get("resource"), "resource"),
        action=_string(config.get("action"), "action"),
        contract_version=str(config.get("contract_version", "1")),
        upstream_method=method,
        path_template=path,
        auth_profile=_string(config.get("auth_profile"), "auth_profile"),
        stability=stability,
        input_fields=tuple(fields),
        request=request,
        response_projection=response_projection,
        pagination=pagination,
        semantic_error_rules=tuple(
            models.SemanticErrorRule.from_dict(item) for item in raw_rules
        ),
        privacy_policy=models.PrivacyPolicy.from_value(config.get("privacy_policy")),
        required_parent=required_parent,
        live_probe=live_probe,
        platform=str(config["platform"]) if config.get("platform") else None,
        description=str(config.get("description", "")),
        effect=effect,
        executable=executable,
        block_reason=block_reason,
    )


def load_operations(
    source: str | Path | Mapping[str, Any] | Sequence[Any],
    *,
    operation_spec: Any,
    load_operation_manifest: Any,
) -> tuple[Any, ...]:
    raw = _read_manifest_source(source, load_operation_manifest)
    if isinstance(raw, _LoadedOperations):
        return raw.operations
    if isinstance(raw, Mapping) and "operations" in raw:
        raw = raw["operations"]
    elif isinstance(raw, Mapping) and "operation_id" in raw:
        raw = [raw]
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        raise ManifestError(
            "manifest must be an operation list or an object containing operations"
        )
    operations = tuple(
        operation_spec.from_dict(_mapping(item, "operations[]")) for item in raw
    )
    if not operations:
        raise ManifestError("manifest must contain at least one operation")
    ids = [item.operation_id for item in operations]
    if len(ids) != len(set(ids)):
        raise ManifestError("manifest contains duplicate operation_id values")
    return operations


def _string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ManifestError(f"{label} must be a non-empty string")
    return value.strip()


def _parse_operation_identity(config: Mapping[str, Any]) -> tuple[str, str, str]:
    operation_id = _string(config.get("operation_id"), "operation_id")
    if not _OPERATION_ID_RE.fullmatch(operation_id):
        raise ManifestError(f"invalid operation_id: {operation_id!r}")
    method = _string(config.get("upstream_method"), "upstream_method").upper()
    if method not in _READ_METHODS:
        raise ManifestError("upstream_method must be GET or read-semantic POST")
    path = _string(config.get("path_template"), "path_template")
    if not _SAFE_PATH_RE.fullmatch(path) or "//" in path or "/../" in path or "/./" in path:
        raise ManifestError("path_template must be a normalized absolute API path ending in /")
    return operation_id, method, path


def _parse_input_fields(config: Mapping[str, Any], input_field_cls: Any) -> list[Any]:
    raw_fields = config.get("input_fields", {})
    fields: list[Any] = []
    if isinstance(raw_fields, Mapping):
        return [input_field_cls.from_value(str(name), item) for name, item in raw_fields.items()]
    if isinstance(raw_fields, Sequence) and not isinstance(raw_fields, (str, bytes)):
        for item in raw_fields:
            if isinstance(item, str):
                fields.append(input_field_cls.from_value(item, {}))
            else:
                item_config = _mapping(item, "input_fields[]")
                name = _string(item_config.get("name"), "input_fields[].name")
                fields.append(input_field_cls.from_value(name, item_config))
        return fields
    raise ManifestError("input_fields must be an object or list")


def _validate_request_bindings(path: str, request: Any, names: Sequence[str]) -> None:
    placeholders = tuple(
        field_name for _, field_name, _, _ in string.Formatter().parse(path) if field_name
    )
    undeclared_placeholders = set(placeholders) - set(names)
    if undeclared_placeholders:
        raise ManifestError("path_template placeholders must be declared input fields")
    if request.path_fields and tuple(request.path_fields) != placeholders:
        raise ManifestError("request.path_fields must exactly match path_template placeholders")
    request_names = (
        set(request.path_fields)
        | set(request.query_fields)
        | set(request.body_fields)
        | set(request.defaults)
    )
    undeclared_request = request_names - set(names)
    if undeclared_request:
        raise ManifestError("request references undeclared input fields")


def _parse_semantic_error_rules(config: Mapping[str, Any]) -> Sequence[Any]:
    raw_rules = config.get("semantic_error_rules", ())
    if raw_rules is None:
        raw_rules = ()
    if not isinstance(raw_rules, Sequence) or isinstance(raw_rules, (str, bytes)):
        raise ManifestError("semantic_error_rules must be a list")
    return raw_rules


def _parse_operation_flags(config: Mapping[str, Any]) -> tuple[str, bool, str | None, str]:
    stability = _string(config.get("stability"), "stability").lower()
    if stability not in _STABILITY_VALUES:
        raise ManifestError(f"unsupported operation stability: {stability}")
    executable = config.get("executable", True)
    if not isinstance(executable, bool):
        raise ManifestError("operation executable must be a boolean")
    block_reason = str(config.get("block_reason", "")).strip() or None
    if not executable and not block_reason:
        raise ManifestError("non-executable operations must declare block_reason")
    effect = str(config.get("effect", "read")).strip()
    return stability, executable, block_reason, effect


def _validate_projection_normalization(response_projection: Any, pagination: Any) -> None:
    if response_projection.empty_object_as_empty_page and (
        pagination.kind != "page_info"
        or not {"list", "page_info"}.issubset(response_projection.data_keys)
    ):
        raise ManifestError(
            "empty-object page normalization requires an explicit paginated list contract"
        )
    if response_projection.empty_object_as_empty_result and (
        response_projection.data_shape != "object"
        or response_projection.required_data_keys
    ):
        raise ManifestError(
            "empty-object result normalization requires an object response with no required keys"
        )


def _validate_stable_pagination(stability: str, pagination: Any) -> None:
    if stability == "stable" and pagination.kind == "page_info":
        if pagination.default_page_size is None or pagination.max_page_size is None:
            raise ManifestError(
                "stable paginated operations must declare default_page_size and max_page_size"
            )


def _validate_required_parent_inputs(
    required_parent: Sequence[Any], names: Sequence[str]
) -> None:
    undeclared_parent_inputs = {
        parent.input_field
        for parent in required_parent
        if parent.input_field and parent.input_field not in names
    }
    if undeclared_parent_inputs:
        raise ManifestError("required_parent input fields must be declared operation inputs")


def _validate_live_probe_inputs(
    live_probe: Any, fields: Sequence[Any], names: Sequence[str], request: Any
) -> None:
    if set(live_probe.inputs) - set(names):
        raise ManifestError("live_probe inputs must reference declared operation inputs")
    required_probe_inputs = {field.name for field in fields if field.required}
    if live_probe.enabled and not required_probe_inputs <= (
        set(live_probe.inputs) | set(request.defaults)
    ):
        raise ManifestError("live_probe is missing required minimum inputs")


class _LoadedOperations:
    __slots__ = ("operations",)

    def __init__(self, operations: tuple[Any, ...]) -> None:
        self.operations = operations


def _read_manifest_source(
    source: str | Path | Mapping[str, Any] | Sequence[Any],
    load_operation_manifest: Any,
) -> Any:
    if isinstance(source, Path):
        try:
            return json.loads(source.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ManifestError("could not load the operation manifest") from exc
    if isinstance(source, str):
        candidate = Path(source)
        if candidate.is_file():
            return _LoadedOperations(load_operation_manifest(candidate))
        try:
            return json.loads(source)
        except json.JSONDecodeError as exc:
            raise ManifestError(
                "manifest string must contain JSON or name an existing file"
            ) from exc
    return source
