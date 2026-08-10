"""Canonical Gravity Insight contract fingerprints and state migration."""

from __future__ import annotations

import hashlib
import json
import os
import threading
from pathlib import Path
from typing import Any, Mapping

from .models import _MISSING


def contract_fingerprint(operation: Any) -> str:
    """Hash semantic contract material while excluding documentation fields."""

    payload_builder = getattr(operation, "contract_fingerprint_payload", None)
    if callable(payload_builder):
        payload = payload_builder()
    elif all(
        hasattr(operation, name)
        for name in ("input_fields", "request", "response_projection", "pagination")
    ):
        payload = _runtime_contract_payload(operation)
    else:
        payload = _strip_documentation(_operation_payload(operation))
    return _canonical_fingerprint(payload)


def value_shape(value: Any) -> Any:
    """Return a value-free structural sketch suitable for aggregation."""

    if isinstance(value, Mapping):
        return {
            str(key): value_shape(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        encoded = {
            json.dumps(
                value_shape(item),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            )
            for item in value
        }
        return {
            "type": "array",
            "items": [json.loads(item) for item in sorted(encoded)],
        }
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    return "string"


def shape_fingerprint(value: Any) -> str:
    """Hash only object keys, container layout, and JSON scalar types."""

    return _canonical_fingerprint(value_shape(value))


def legacy_contract_fingerprint(operation: Any) -> str:
    """Reproduce the pre-migration schema hash for exact evidence upgrades."""

    return _canonical_fingerprint(_operation_payload(operation))


def migrate_catalog_fingerprints(
    state_path: Path | None,
    raw: Mapping[str, Any],
    replacements: Mapping[str, str],
) -> None:
    """Atomically upgrade only exact legacy matches and preserve other evidence."""

    if state_path is None:
        return
    payload = _plain(raw)
    probes = payload.get("probes") if isinstance(payload, dict) else None
    if not isinstance(probes, dict):
        return
    for operation_id, fingerprint in replacements.items():
        value = probes.get(operation_id)
        if isinstance(value, dict):
            value["contract_fingerprint"] = fingerprint
    write_json_atomic(state_path, payload)


def write_json_atomic(path: Path | None, payload: Mapping[str, Any]) -> None:
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(
            f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
        )
        temporary.write_text(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )
        os.replace(temporary, path)
    except OSError:
        # Probe history is advisory and must never break a read.
        return


def _runtime_contract_payload(operation: Any) -> dict[str, Any]:
    return {
        "operation_id": operation.operation_id,
        "domain": operation.domain,
        "resource": operation.resource,
        "action": operation.action,
        "contract_version": operation.contract_version,
        "upstream_method": operation.upstream_method,
        "path_template": operation.path_template,
        "auth_profile": operation.auth_profile,
        "stability": operation.stability,
        "platform": operation.platform,
        "effect": operation.effect,
        "executable": operation.executable,
        "block_reason": operation.block_reason,
        "input_fields": {
            field.name: _input_field_payload(field)
            for field in operation.input_fields
        },
        "request": _request_payload(operation.request),
        "response_projection": _projection_payload(operation.response_projection),
        "pagination": _pagination_payload(operation.pagination),
        "semantic_error_rules": _semantic_error_payload(operation.semantic_error_rules),
        "privacy_policy": {
            "classification": operation.privacy_policy.classification,
            "redact_fields": list(operation.privacy_policy.redact_fields),
        },
        "required_parent": [
            {"operation_id": parent.operation_id, "input_field": parent.input_field}
            for parent in operation.required_parent
        ],
        "live_probe": {
            "enabled": operation.live_probe.enabled,
            "inputs": _plain(operation.live_probe.inputs),
        },
    }


def _input_field_payload(field: Any) -> dict[str, Any]:
    payload = {
        "type": field.type,
        "required": field.required,
        "nullable": field.nullable,
        "sensitive": field.sensitive,
        "item_type": field.item_type,
        "min_items": field.min_items,
        "max_items": field.max_items,
        "max_length": field.max_length,
        "max_depth": field.max_depth,
    }
    if field.enum:
        payload["enum"] = _plain(field.enum)
    if field.default is not _MISSING:
        payload["default"] = _plain(field.default)
    if field.item_enum:
        payload["item_enum"] = _plain(field.item_enum)
    return payload


def _request_payload(request: Any) -> dict[str, Any]:
    return {
        "location": request.location,
        "path_fields": list(request.path_fields),
        "query_fields": list(request.query_fields),
        "body_fields": list(request.body_fields),
        "defaults": _plain(request.defaults),
        "fixed_query": _plain(request.fixed_query),
        "fixed_body": _plain(request.fixed_body),
    }


def _projection_payload(projection: Any) -> dict[str, Any]:
    return {
        "leaf_contract": "json_scalar",
        "data_shape": projection.data_shape,
        "data_keys": list(projection.data_keys),
        "required_data_keys": list(projection.required_data_keys),
        "item_keys": list(projection.item_keys),
        "dynamic_item_fields": list(projection.dynamic_item_fields),
        "numeric_suffix_item_fields": list(projection.numeric_suffix_item_fields),
        "nested_item_keys": _list_mapping(projection.nested_item_keys),
        "known_omitted_nested_item_keys": _list_mapping(
            projection.known_omitted_nested_item_keys
        ),
        "data_item_keys": _list_mapping(projection.data_item_keys),
        "scalar_list_item_types": dict(projection.scalar_list_item_types),
        "data_scalar_list_types": dict(projection.data_scalar_list_types),
        "data_path_item_keys": _list_mapping(projection.data_path_item_keys),
        "data_dynamic_item_fields": _list_mapping(
            projection.data_dynamic_item_fields
        ),
        "data_numeric_suffix_item_fields": _list_mapping(
            projection.data_numeric_suffix_item_fields
        ),
        "known_omitted_item_keys": list(projection.known_omitted_item_keys),
        "recursive_data_item_keys": _list_mapping(
            projection.recursive_data_item_keys
        ),
        "known_omitted_data_keys": list(projection.known_omitted_data_keys),
        "known_omitted_data_item_keys": _list_mapping(
            projection.known_omitted_data_item_keys
        ),
        "numeric_paths": list(projection.numeric_paths),
        "empty_object_as_empty_page": projection.empty_object_as_empty_page,
        "empty_object_as_empty_result": projection.empty_object_as_empty_result,
        "opaque_json_item_keys": list(projection.opaque_json_item_keys),
    }


def _pagination_payload(pagination: Any) -> dict[str, Any]:
    return {
        "kind": pagination.kind,
        "page_field": pagination.page_field,
        "page_size_field": pagination.page_size_field,
        "items_field": pagination.items_field,
        "page_info_field": pagination.page_info_field,
        "total_page_field": pagination.total_page_field,
        "list_path": pagination.list_path,
        "page_info_path": pagination.page_info_path,
        "default_page_size": pagination.default_page_size,
        "max_page_size": pagination.max_page_size,
    }


def _semantic_error_payload(rules: Any) -> list[dict[str, Any]]:
    return [
        {
            "path": rule.path,
            "operator": rule.operator,
            "value": _plain(rule.value),
            "values": _plain(rule.values),
            "message": rule.message,
        }
        for rule in rules
    ]


def _list_mapping(value: Mapping[str, Any]) -> dict[str, list[Any]]:
    return {str(name): list(items) for name, items in value.items()}


def _operation_payload(operation: Any) -> Any:
    schema = getattr(operation, "schema", None)
    return schema() if callable(schema) else operation.capability()


def _strip_documentation(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(name): _strip_documentation(item)
            for name, item in value.items()
            if name not in {"description", "examples", "provenance"}
        }
    if isinstance(value, (list, tuple)):
        return [_strip_documentation(item) for item in value]
    return value


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(name): _plain(item) for name, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def _canonical_fingerprint(value: Any) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
