"""Contracted response list-row projection."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .drift import ProjectionDrift
from .models import OperationSpec
from .multidim import projected_keys
from .response_drift import ResponseDriftRecorder
from .response_projection import (
    _copy_json_value,
    _is_json_scalar,
    _project_nested_item_value,
    _project_scalar_list,
)


def _project_list_rows(
    operation: OperationSpec,
    projected: Any,
    values: Mapping[str, Any],
    recorder: ResponseDriftRecorder,
) -> tuple[Any, tuple[str, ...], ProjectionDrift]:
    allowed = projected_keys(
        operation.response_projection.item_keys,
        operation.response_projection.dynamic_item_fields,
        (), values, None,
    )
    known_omitted = set(operation.response_projection.known_omitted_item_keys)
    field_name, rows = _list_row_source(operation, projected)
    if not isinstance(rows, list):
        return projected, (), ProjectionDrift.NONE

    allowed.update(projected_keys((), (), operation.response_projection.numeric_suffix_item_fields, values, rows))
    row_path = (
        ("data", field_name, "*")
        if isinstance(projected, Mapping)
        else ("data", "*")
    )
    filtered, unknown, unknown_nested_keys, stats = _collect_projected_list_rows(
        operation, rows, allowed, known_omitted, recorder, row_path
    )
    warnings = _list_row_projection_warnings(
        allowed, unknown, unknown_nested_keys, stats
    )
    drift = _list_row_projection_drift(allowed, unknown, stats, bool(rows))
    if isinstance(projected, Mapping):
        copied = dict(projected)
        copied[field_name] = filtered
        return copied, warnings, drift
    return filtered, warnings, drift


def _list_row_source(
    operation: OperationSpec, projected: Any
) -> tuple[str, Any]:
    field_name = operation.pagination.list_path.rsplit(".", 1)[-1]
    if isinstance(projected, Mapping):
        if not field_name or not isinstance(projected.get(field_name), list):
            field_name = "list" if isinstance(projected.get("list"), list) else ""
        return field_name, projected.get(field_name) if field_name else None
    return field_name, projected if isinstance(projected, list) else None


def _collect_projected_list_rows(
    operation: OperationSpec,
    rows: list[Any],
    allowed: set[str],
    known_omitted: set[str],
    recorder: ResponseDriftRecorder,
    row_path: tuple[str, ...],
) -> tuple[list[Any], set[str], set[str], tuple[int, int, int, int]]:
    unknown: set[str] = set()
    filtered: list[Any] = []
    non_object_items = 0
    uncontracted_containers = 0
    invalid_scalar_items = 0
    unknown_nested_keys: set[str] = set()
    nested_breaking_items = 0
    for row in rows:
        if not isinstance(row, Mapping):
            # List contracts are row/object contracts.  Scalars and nested arrays
            # have no field-level policy surface, so fail closed on schema drift.
            non_object_items += 1
            continue
        row_keys = {str(key) for key in row}
        row_unknown = row_keys - allowed - known_omitted
        unknown.update(row_unknown)
        recorder.add_unknown_fields(row_path, row, row_unknown)
        projected_row, row_stats = _project_list_row(
            operation, row, allowed, recorder, row_path
        )
        row_nested, row_containers, row_scalars, row_breaking = row_stats
        unknown_nested_keys.update(row_nested)
        uncontracted_containers += row_containers
        invalid_scalar_items += row_scalars
        nested_breaking_items += row_breaking
        filtered.append(projected_row)
    return (
        filtered,
        unknown,
        unknown_nested_keys,
        (
            non_object_items,
            uncontracted_containers,
            invalid_scalar_items,
            nested_breaking_items,
        ),
    )


def _list_row_projection_warnings(
    allowed: set[str],
    unknown: set[str],
    unknown_nested_keys: set[str],
    stats: tuple[int, int, int, int],
) -> tuple[str, ...]:
    non_object_items, uncontracted_containers, invalid_scalar_items, nested_breaking_items = stats
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
    if nested_breaking_items:
        warnings.append(
            "invalid contracted nested item values were omitted "
            f"(count={nested_breaking_items})"
        )
    return tuple(warnings)


def _list_row_projection_drift(
    allowed: set[str],
    unknown: set[str],
    stats: tuple[int, int, int, int],
    has_rows: bool,
) -> ProjectionDrift:
    non_object_items, uncontracted_containers, invalid_scalar_items, nested_breaking_items = stats
    breaking = bool(
        non_object_items
        or uncontracted_containers
        or invalid_scalar_items
        or nested_breaking_items
        or (has_rows and not allowed)
    )
    drift = ProjectionDrift.NONE
    if unknown:
        drift = ProjectionDrift.ADDITIVE
    if breaking and drift < ProjectionDrift.BREAKING:
        drift = ProjectionDrift.BREAKING
    return drift


def _project_list_row(
    operation: OperationSpec,
    row: Mapping[Any, Any],
    allowed: set[str],
    recorder: ResponseDriftRecorder,
    row_path: tuple[str, ...],
) -> tuple[dict[str, Any], tuple[set[str], int, int, int]]:
    projected: dict[str, Any] = {}
    unknown: set[str] = set()
    containers = invalid_scalars = breaking = 0
    projection = operation.response_projection
    for key, value in row.items():
        name = str(key)
        if name not in allowed:
            continue
        if not isinstance(value, (Mapping, list, tuple)):
            if _is_json_scalar(value):
                projected[name] = value
            else:
                invalid_scalars += 1
            continue
        if name in projection.opaque_json_item_keys:
            normalized, valid = _copy_json_value(value)
        elif name in projection.scalar_list_item_types:
            normalized, valid = _project_scalar_list(
                value, projection.scalar_list_item_types[name]
            )
        else:
            normalized, nested_unknown, nested_breaking, valid = (
                _project_nested_item_value(
                    value, projection.nested_item_keys.get(name),
                    projection.nested_item_keys,
                    projection.known_omitted_nested_item_keys,
                    projection.opaque_json_item_keys, recorder,
                    (*row_path, name),
                    projection.known_omitted_nested_item_keys.get(name, ()),
                )
            )
            nested_unknown -= set(
                projection.known_omitted_nested_item_keys.get(name, ())
            )
            unknown.update(nested_unknown)
            breaking += int(nested_breaking)
        if valid:
            projected[name] = normalized
        else:
            containers += 1
    return projected, (unknown, containers, invalid_scalars, breaking)


