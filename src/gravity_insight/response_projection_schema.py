"""Serialization helpers for response projection contracts."""

from __future__ import annotations

from types import MappingProxyType
from typing import Any, Mapping

from .errors import ManifestError
from .projection_validation import numeric_suffix_schema
from .response_drift import normalize_dynamic_key_patterns


def dynamic_key_pattern_mapping(value: Any) -> Mapping[str, str]:
    try:
        return MappingProxyType(normalize_dynamic_key_patterns(value))
    except ValueError as exc:
        raise ManifestError(str(exc)) from exc


def response_projection_schema(projection: Any) -> dict[str, Any]:
    result = {"leaf_contract": "json_scalar"}
    for name in "data_shape empty_object_as_empty_page empty_object_as_empty_result".split():
        result[name] = getattr(projection, name)
    for name in "data_keys required_data_keys item_keys dynamic_item_fields known_omitted_item_keys known_omitted_data_keys numeric_paths opaque_json_item_keys".split():
        result[name] = list(getattr(projection, name))
    result.update(numeric_suffix_schema(projection))
    for name in ("scalar_list_item_types", "data_scalar_list_types"):
        result[name] = dict(getattr(projection, name))
    mappings = "nested_item_keys known_omitted_nested_item_keys data_item_keys data_path_item_keys data_dynamic_item_fields recursive_data_item_keys known_omitted_data_item_keys".split()
    for name in mappings:
        result[name] = {key: list(value) for key, value in getattr(projection, name).items()}
    if projection.dynamic_key_patterns:
        result["dynamic_key_patterns"] = dict(projection.dynamic_key_patterns)
    return result


__all__ = ["dynamic_key_pattern_mapping", "response_projection_schema"]
