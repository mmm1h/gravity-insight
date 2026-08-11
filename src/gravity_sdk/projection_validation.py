"""Cross-field validation for response projection contracts."""

from __future__ import annotations

from typing import Any, Sequence

from .errors import ManifestError


def numeric_suffix_schema(projection: Any) -> dict[str, Any]:
    return {
        "numeric_suffix_item_fields": list(projection.numeric_suffix_item_fields),
        "data_numeric_suffix_item_fields": {
            name: list(fields)
            for name, fields in projection.data_numeric_suffix_item_fields.items()
        },
    }


def validate_projection_bindings(projection: Any, names: Sequence[str]) -> None:
    declared_inputs = set(names)
    if projection.data_shape == "list" and (
        projection.data_keys or projection.required_data_keys
    ):
        raise ManifestError("list response projections cannot declare object data keys")
    for field_name, message in (
        (
            "dynamic_item_fields",
            "response_projection.dynamic_item_fields must reference declared inputs",
        ),
        (
            "numeric_suffix_item_fields",
            "response_projection.numeric_suffix_item_fields must reference declared inputs",
        ),
    ):
        if set(getattr(projection, field_name)) - declared_inputs:
            raise ManifestError(message)
    _validate_collection_bindings(projection)
    _validate_data_bindings(projection, declared_inputs)
    _validate_omission_bindings(projection)


def _validate_collection_bindings(projection: Any) -> None:
    nested_parent_keys = set(projection.item_keys)
    for data_item_keys in projection.data_item_keys.values():
        nested_parent_keys.update(data_item_keys)
    for path_item_keys in projection.data_path_item_keys.values():
        nested_parent_keys.update(path_item_keys)
    pending = list(nested_parent_keys)
    while pending:
        parent = pending.pop()
        for child in projection.nested_item_keys.get(parent, ()):
            if child not in nested_parent_keys:
                nested_parent_keys.add(child)
                pending.append(child)
    if set(projection.nested_item_keys) - nested_parent_keys:
        raise ManifestError(
            "response_projection.nested_item_keys must reference declared item_keys "
            "or reachable data container fields"
        )
    if set(projection.data_item_keys) - set(projection.data_keys):
        raise ManifestError(
            "response_projection.data_item_keys must reference declared data_keys"
        )
    if set(projection.scalar_list_item_types) - set(projection.item_keys):
        raise ManifestError(
            "response_projection.scalar_list_item_types must reference declared item_keys"
        )
    if set(projection.data_scalar_list_types) - set(projection.data_keys):
        raise ManifestError(
            "response_projection.data_scalar_list_types must reference declared data_keys"
        )
    if set(projection.data_scalar_list_types) & set(projection.data_item_keys):
        raise ManifestError(
            "response data fields cannot declare both scalar-list and object contracts"
        )


def _validate_data_bindings(projection: Any, declared_inputs: set[str]) -> None:
    roots = {
        path.split(".", 1)[0]
        for path in projection.data_path_item_keys
        if path.split(".", 1)[0] not in projection.data_keys
    }
    invalid_paths = {
        path for path in projection.data_path_item_keys if len(path.split(".")) != 2
    }
    if roots or invalid_paths:
        raise ManifestError(
            "response_projection.data_path_item_keys must use declared two-segment data paths"
        )
    _validate_dynamic_data_bindings(
        projection.data_dynamic_item_fields,
        projection.data_keys,
        declared_inputs,
        "data_dynamic_item_fields",
    )
    _validate_dynamic_data_bindings(
        projection.data_numeric_suffix_item_fields,
        projection.data_keys,
        declared_inputs,
        "data_numeric_suffix_item_fields",
    )


def _validate_omission_bindings(projection: Any) -> None:
    if set(projection.known_omitted_item_keys) & set(projection.item_keys):
        raise ManifestError("known omitted item keys cannot also be projected")
    if set(projection.opaque_json_item_keys) - set(projection.item_keys):
        raise ManifestError(
            "response_projection.opaque_json_item_keys must reference declared item_keys"
        )
    if set(projection.known_omitted_nested_item_keys) - set(
        projection.nested_item_keys
    ):
        raise ManifestError(
            "response_projection.known_omitted_nested_item_keys must reference "
            "declared nested item keys"
        )
    for item_key, omitted_keys in projection.known_omitted_nested_item_keys.items():
        if set(omitted_keys) & set(projection.nested_item_keys.get(item_key, ())):
            raise ManifestError(
                "known omitted nested response item keys cannot also be projected"
            )
    if set(projection.recursive_data_item_keys) - set(projection.data_keys):
        raise ManifestError(
            "response_projection.recursive_data_item_keys must reference declared data keys"
        )
    if set(projection.known_omitted_data_keys) & set(projection.data_keys):
        raise ManifestError("known omitted data keys cannot also be projected")
    if set(projection.known_omitted_data_item_keys) - set(projection.data_keys):
        raise ManifestError(
            "response_projection.known_omitted_data_item_keys must reference "
            "declared data keys"
        )
    for data_key, omitted_keys in projection.known_omitted_data_item_keys.items():
        if set(omitted_keys) & set(projection.data_item_keys.get(data_key, ())):
            raise ManifestError(
                "known omitted response data item keys cannot also be projected"
            )


def _validate_dynamic_data_bindings(
    bindings: Any,
    data_keys: Sequence[str],
    declared_inputs: set[str],
    field_name: str,
) -> None:
    invalid_keys = set(bindings) - set(data_keys)
    invalid_inputs = {
        input_name
        for input_names in bindings.values()
        for input_name in input_names
        if input_name not in declared_inputs
    }
    if invalid_keys or invalid_inputs:
        raise ManifestError(
            f"response_projection.{field_name} must bind declared data keys and inputs"
        )
