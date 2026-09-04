"""Contract-aware local output selection for read, batch, and plan surfaces."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any

from .errors import ContractChangedError, InputValidationError
from .actionable_error_values import actual_value


MAX_OUTPUT_FIELDS = 128
_OUTPUT_SHAPE_REPAIR = (
    "Repair owner: undetermined between the upstream operation owner and the "
    "Gravity Runtime contract maintainer, not the caller. Next step: capture "
    "the operation_id and response-shape evidence and hand them to those "
    "maintainers. Stop condition: do not retry the unchanged caller input "
    "until the response contract is re-verified."
)
_PROJECTION_CONTRACT_REPAIR = (
    "Repair owner: Gravity Runtime operation-contract maintainer. Next step: "
    "compile and register a valid response_projection; callers may omit "
    "output_fields as the bounded alternative. Stop condition: do not retry "
    "field selection until that contract is available."
)


def validate_output_fields(
    operation_schema: Mapping[str, Any],
    output_fields: Sequence[str],
    *,
    request_inputs: Mapping[str, Any] | None = None,
) -> tuple[str, ...]:
    """Validate data-relative field paths without reading from the network."""

    fields = _field_list(output_fields)
    projection = _projection(operation_schema)
    allowed = _allowed_paths(projection, request_inputs or {})
    unknown = [
        field
        for field in fields
        if field not in allowed
        and not _allowed_numeric_exact(
            field, projection, request_inputs or {}
        )
    ]
    if unknown:
        rendered = ", ".join(unknown[:5])
        suffix = "" if len(unknown) <= 5 else f" (+{len(unknown) - 5} more)"
        raise InputValidationError(
            f"actual value: {actual_value(unknown)}; " + (f"output_fields contains fields absent from the operation contract: {rendered}{suffix}"),
            field="output_fields",
            next_action="Inspect the operation schema and select only contracted response fields.",
        )
    return fields


def apply_output_fields(
    envelope: Mapping[str, Any],
    operation_schema: Mapping[str, Any],
    output_fields: Sequence[str] | None,
    *,
    request_inputs: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return an isolated envelope whose ``data`` contains only selected fields.

    ``None`` preserves the current response byte-for-byte at the value level.  An
    explicit selection is relative to ``data``: list item fields use ``id`` or
    ``relation.name`` while object containers use ``app.id``. Pagination metadata
    is retained whenever the selected result includes the contracted list.
    """

    if not isinstance(envelope, Mapping):
        raise ContractChangedError(
            "operation output must be an object",
            next_action=_OUTPUT_SHAPE_REPAIR,
        )
    if output_fields is None:
        return deepcopy(dict(envelope))
    selected = validate_output_fields(
        operation_schema, output_fields, request_inputs=request_inputs
    )
    projection = _projection(operation_schema)
    data = envelope.get("data")
    result = deepcopy(dict(envelope))
    result["data"] = _project_data(data, selected, projection, request_inputs or {})
    result["output_fields"] = list(selected)
    return result


def project_output(
    client_or_schema: Any,
    operation_id: str,
    envelope: Mapping[str, Any],
    output_fields: Sequence[str] | None,
    *,
    request_inputs: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Convenience hook accepting either a schema mapping or a public client."""

    schema = (
        client_or_schema
        if isinstance(client_or_schema, Mapping)
        else client_or_schema.schema(operation_id)
    )
    return apply_output_fields(
        envelope, schema, output_fields, request_inputs=request_inputs
    )


def allowed_output_fields(
    operation_schema: Mapping[str, Any],
    *,
    request_inputs: Mapping[str, Any] | None = None,
) -> list[str]:
    """Expose the exact preflight vocabulary for CLI/SDK schema cards."""

    return sorted(_allowed_paths(_projection(operation_schema), request_inputs or {}))


def _field_list(value: Sequence[str]) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise InputValidationError(f"actual value: {actual_value(value)}; " + ("output_fields must be a list of field paths"), field="output_fields")
    if not value:
        raise InputValidationError(f"actual value: {actual_value(value)}; " + ("output_fields must not be empty"), field="output_fields")
    if len(value) > MAX_OUTPUT_FIELDS:
        raise InputValidationError(
            f"output_fields exceeds the {MAX_OUTPUT_FIELDS}-field safety bound",
            field="output_fields", next_action="Keep only documented dotted output_fields and retry.",
        )
    normalized: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise InputValidationError(f"actual value: {actual_value(item)}; " + ("output_fields must contain only strings"), field="output_fields")
        field = item.strip()
        parts = field.split(".")
        if (
            not field
            or len(field) > 512
            or any(not part or part in {"__proto__", "prototype", "constructor"} for part in parts)
        ):
            raise InputValidationError("output_fields contains an invalid field path", field="output_fields", next_action="Keep only documented dotted output_fields and retry.")
        if field not in normalized:
            normalized.append(field)
    return tuple(normalized)


def _projection(schema: Mapping[str, Any]) -> Mapping[str, Any]:
    if not isinstance(schema, Mapping):
        raise ContractChangedError(
            "operation schema must be an object",
            next_action=_PROJECTION_CONTRACT_REPAIR,
        )
    value = schema.get("response_projection")
    if not isinstance(value, Mapping):
        raise ContractChangedError(
            "operation schema has no response projection",
            next_action=_PROJECTION_CONTRACT_REPAIR,
        )
    return value


def _allowed_paths(
    projection: Mapping[str, Any], request_inputs: Mapping[str, Any]
) -> set[str]:
    nested = _path_mapping(projection.get("nested_item_keys"))
    allowed = _leaf_paths("", _strings(projection.get("item_keys")), nested)
    data_containers = _path_mapping(projection.get("data_item_keys"))
    path_containers = _path_mapping(projection.get("data_path_item_keys"))
    recursive = _path_mapping(projection.get("recursive_data_item_keys"))
    container_roots = _container_roots(
        projection, data_containers, path_containers, recursive
    )
    allowed.update(set(_strings(projection.get("data_keys"))) - container_roots)
    allowed.update(_container_leaf_paths(data_containers, nested))
    allowed.update(_container_leaf_paths(path_containers, nested))
    for parent, children in recursive.items():
        allowed.update(
            f"{parent}.{child}" for child in children if child != "children"
        )

    allowed.update(
        _dynamic_paths(projection, request_inputs)
    )
    allowed.update(_numeric_wildcard_paths(projection, request_inputs))
    return allowed


def _container_roots(
    projection: Mapping[str, Any],
    data_containers: Mapping[str, Sequence[str]],
    path_containers: Mapping[str, Sequence[str]],
    recursive: Mapping[str, Sequence[str]],
) -> set[str]:
    roots = set(data_containers) | {
        path.split(".", 1)[0] for path in path_containers
    } | set(recursive)
    if _has_item_contract(projection):
        roots.update({"list", "items"})
    if "page_info" in _strings(projection.get("data_keys")):
        roots.add("page_info")
    return roots


def _has_item_contract(projection: Mapping[str, Any]) -> bool:
    return bool(
        _strings(projection.get("item_keys"))
        or _strings(projection.get("dynamic_item_fields"))
        or _strings(projection.get("numeric_suffix_item_fields"))
    )


def _container_leaf_paths(
    containers: Mapping[str, Sequence[str]],
    nested: Mapping[str, Sequence[str]],
) -> set[str]:
    result: set[str] = set()
    for parent, children in containers.items():
        result.update(_leaf_paths(parent, children, nested))
    return result


def _dynamic_paths(
    projection: Mapping[str, Any], inputs: Mapping[str, Any]
) -> set[str]:
    result = _dynamic_values(projection.get("dynamic_item_fields"), inputs)
    for parent, input_names in _path_mapping(
        projection.get("data_dynamic_item_fields")
    ).items():
        for name in input_names:
            result.update(
                f"{parent}.{field}"
                for field in _input_field_values(inputs.get(name))
            )
    return result


def _numeric_wildcard_paths(
    projection: Mapping[str, Any], inputs: Mapping[str, Any]
) -> set[str]:
    result = {
        f"{base}_*"
        for base in _requested_values(
            projection.get("numeric_suffix_item_fields"), inputs
        )
    }
    for parent, input_names in _path_mapping(
        projection.get("data_numeric_suffix_item_fields")
    ).items():
        result.update(
            f"{parent}.{base}_*"
            for base in _requested_values(input_names, inputs)
        )
    return result


def _leaf_paths(
    prefix: str, fields: Sequence[str], nested: Mapping[str, Sequence[str]]
) -> set[str]:
    result: set[str] = set()
    for field in fields:
        path = f"{prefix}.{field}" if prefix else field
        children = nested.get(field)
        if children is None:
            result.add(path)
        else:
            result.update(_leaf_paths(path, children, nested))
    return result


def _project_data(
    data: Any,
    selected: Sequence[str],
    projection: Mapping[str, Any],
    request_inputs: Mapping[str, Any],
) -> Any:
    if not isinstance(data, (Mapping, list)):
        return deepcopy(data)
    nested = _path_mapping(projection.get("nested_item_keys"))
    item_roots = set(_strings(projection.get("item_keys")))
    item_roots.update(nested)
    item_roots.update(_dynamic_values(projection.get("dynamic_item_fields"), request_inputs))
    numeric_bases = _requested_values(
        projection.get("numeric_suffix_item_fields"), request_inputs
    )
    item_roots.update(f"{base}_*" for base in numeric_bases)
    item_paths = [
        field
        for field in selected
        if field.split(".", 1)[0] in item_roots
        or ("." not in field and any(_numeric_suffix(field, base) for base in numeric_bases))
    ]
    item_whole = _whole_value_keys(projection, "scalar_list_item_types")
    if isinstance(data, list):
        return _project_rows(data, item_paths, nested, item_whole)
    return _project_object_data(
        data, selected, item_paths, projection, nested, item_whole
    )


def _project_object_data(
    data: Mapping[str, Any],
    selected: Sequence[str],
    item_paths: Sequence[str],
    projection: Mapping[str, Any],
    nested: Mapping[str, Sequence[str]],
    item_whole: set[str],
) -> dict[str, Any]:
    recursive = _path_mapping(projection.get("recursive_data_item_keys"))
    data_paths = [
        field
        for field in selected
        if field not in item_paths
        and field.split(".", 1)[0] not in recursive
    ]
    data_whole = _whole_value_keys(projection, "data_scalar_list_types")
    projected = _project_mapping(data, data_paths, nested, data_whole)
    _add_recursive_data(projected, data, selected, recursive)
    _add_list_data(projected, data, item_paths, nested, item_whole)
    if item_paths and not _has_rows(data):
        projected.update(_project_mapping(data, item_paths, nested, item_whole))
    return projected


def _whole_value_keys(projection: Mapping[str, Any], scalar_key: str) -> set[str]:
    opaque = set(_strings(projection.get("opaque_json_item_keys")))
    scalar_lists = projection.get(scalar_key)
    if isinstance(scalar_lists, Mapping):
        opaque.update(str(name) for name in scalar_lists if isinstance(name, str))
    return opaque


def _add_recursive_data(
    projected: dict[str, Any],
    data: Mapping[str, Any],
    selected: Sequence[str],
    recursive: Mapping[str, Sequence[str]],
) -> None:
    for root, allowed in recursive.items():
        prefix = root + "."
        paths = [field[len(prefix) :] for field in selected if field.startswith(prefix)]
        if paths and root in data:
            projected[root] = _project_recursive(data[root], paths, set(allowed))


def _add_list_data(
    projected: dict[str, Any],
    data: Mapping[str, Any],
    item_paths: Sequence[str],
    nested: Mapping[str, Sequence[str]],
    whole: set[str],
) -> None:
    for list_key in ("list", "items"):
        rows = data.get(list_key)
        if item_paths and isinstance(rows, list):
            projected[list_key] = _project_rows(rows, item_paths, nested, whole)
        if list_key in projected and isinstance(data.get("page_info"), Mapping):
            projected["page_info"] = deepcopy(data["page_info"])


def _project_rows(
    rows: Sequence[Any],
    paths: Sequence[str],
    nested: Mapping[str, Sequence[str]],
    whole: set[str],
) -> list[Any]:
    return [
        _project_mapping(item, paths, nested, whole)
        if isinstance(item, Mapping)
        else deepcopy(item)
        for item in rows
    ]


def _has_rows(data: Mapping[str, Any]) -> bool:
    return any(isinstance(data.get(key), list) for key in ("list", "items"))


def _project_mapping(
    value: Mapping[str, Any],
    paths: Sequence[str],
    nested: Mapping[str, Sequence[str]] | None = None,
    whole: set[str] | None = None,
) -> dict[str, Any]:
    contracts = nested or {}
    whole = whole or set()
    result: dict[str, Any] = {}
    for head, tails in _group_paths(paths).items():
        if head.endswith("_*"):
            _copy_numeric_fields(result, value, head[:-2])
            continue
        if head not in value:
            continue
        child = _project_selected_value(
            value[head], head, tails, contracts, whole
        )
        if child is _NOT_PROJECTED:
            continue
        result[head] = child
    return result


_NOT_PROJECTED = object()


def _group_paths(paths: Sequence[str]) -> dict[str, tuple[str, ...]]:
    grouped: dict[str, list[str]] = {}
    for path in paths:
        head, separator, tail = path.partition(".")
        value = tail if separator else ""
        if value not in grouped.setdefault(head, []):
            grouped[head].append(value)
    return {head: tuple(tails) for head, tails in grouped.items()}


def _copy_numeric_fields(
    target: dict[str, Any], value: Mapping[str, Any], base: str
) -> None:
    target.update(
        {
            key: deepcopy(item)
            for key, item in value.items()
            if _numeric_suffix(key, base)
        }
    )


def _project_selected_value(
    value: Any,
    name: str,
    tails: Sequence[str],
    nested: Mapping[str, Sequence[str]],
    whole: set[str],
) -> Any:
    if "" in tails:
        children = nested.get(name)
        if children is not None and isinstance(value, (Mapping, list)):
            return _project_nested_all(value, children, nested, whole)
        if isinstance(value, (Mapping, list)) and name not in whole:
            return _NOT_PROJECTED
        return deepcopy(value)
    child_paths = [tail for tail in tails if tail]
    if isinstance(value, Mapping):
        return _project_mapping(value, child_paths, nested, whole)
    if isinstance(value, list):
        return [
            _project_mapping(item, child_paths, nested, whole)
            for item in value
            if isinstance(item, Mapping)
        ]
    return _NOT_PROJECTED


def _project_nested_all(
    value: Any,
    fields: Sequence[str],
    nested: Mapping[str, Sequence[str]],
    whole: set[str],
) -> Any:
    if isinstance(value, list):
        return [
            _project_nested_all(item, fields, nested, whole)
            for item in value
            if isinstance(item, Mapping)
        ]
    if not isinstance(value, Mapping):
        return None
    return _project_mapping(
        value, _leaf_paths("", fields, nested), nested, whole
    )


def _project_recursive(value: Any, paths: Sequence[str], allowed: set[str]) -> Any:
    if isinstance(value, list):
        return [
            _project_recursive(item, paths, allowed)
            for item in value
            if isinstance(item, Mapping)
        ]
    if not isinstance(value, Mapping):
        return None
    result = _project_mapping(
        value,
        [path for path in paths if path in allowed and path != "children"],
    )
    children = value.get("children")
    if "children" in allowed and isinstance(children, (list, Mapping)):
        result["children"] = _project_recursive(children, paths, allowed)
    return result


def _requested_values(input_names: Any, inputs: Mapping[str, Any]) -> set[str]:
    result: set[str] = set()
    for name in _strings(input_names):
        value = inputs.get(name)
        if isinstance(value, str) and value:
            result.add(value)
        elif isinstance(value, (list, tuple)):
            result.update(item for item in value if isinstance(item, str) and item)
    return result


def _numeric_suffix(name: Any, base: str) -> bool:
    if not isinstance(name, str) or not name.startswith(base + "_"):
        return False
    suffix = name[len(base) + 1 :]
    return (
        suffix.isascii()
        and suffix.isdecimal()
        and not suffix.startswith("0")
        and int(suffix) <= 365
    )


def _allowed_numeric_exact(
    field: str, projection: Mapping[str, Any], inputs: Mapping[str, Any]
) -> bool:
    parent, separator, name = field.rpartition(".")
    if not separator:
        bases = _requested_values(
            projection.get("numeric_suffix_item_fields"), inputs
        )
        return any(_numeric_suffix(field, base) for base in bases)
    mapping = _path_mapping(projection.get("data_numeric_suffix_item_fields"))
    bases = _requested_values(mapping.get(parent, ()), inputs)
    return any(_numeric_suffix(name, base) for base in bases)


def _dynamic_values(value: Any, inputs: Mapping[str, Any]) -> set[str]:
    result: set[str] = set()
    for input_name in _strings(value):
        result.update(_input_field_values(inputs.get(input_name)))
    return result


def _input_field_values(value: Any) -> set[str]:
    if not isinstance(value, (list, tuple)):
        return set()
    return {
        item.strip()
        for item in value
        if isinstance(item, str) and item.strip() and len(item.strip()) <= 256
    }


def _path_mapping(value: Any) -> dict[str, tuple[str, ...]]:
    if not isinstance(value, Mapping):
        return {}
    return {
        str(parent): _strings(children)
        for parent, children in value.items()
        if isinstance(parent, str) and parent
    }


def _strings(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(item for item in value if isinstance(item, str) and item)


__all__ = [
    "allowed_output_fields",
    "apply_output_fields",
    "project_output",
    "validate_output_fields",
]
