"""Contracted response row and nested-item projection."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .drift import ProjectionDrift
from .models import OperationSpec
from .multidim import projected_keys
from .response_drift import ResponseDriftRecorder


@dataclass(frozen=True)
class _NestedProjectionRules:
    allowed: frozenset[str]
    nested: Mapping[str, tuple[str, ...]]
    known_omitted: Mapping[str, tuple[str, ...]]
    opaque: frozenset[str]


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
            recorder.add_breaking_field(row_path, "object", row)
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
                recorder.add_breaking_field(
                    (*row_path, name), "json_scalar", value
                )
            continue
        if name in projection.opaque_json_item_keys:
            normalized, valid = _copy_json_value(value)
            if not valid:
                recorder.add_breaking_field(
                    (*row_path, name), "json", value
                )
        elif name in projection.scalar_list_item_types:
            normalized, valid = _project_scalar_list(
                value, projection.scalar_list_item_types[name]
            )
            if not valid:
                _record_scalar_list_drift(
                    value,
                    projection.scalar_list_item_types[name],
                    recorder,
                    (*row_path, name),
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


def _project_scalar_list(value: Any, item_type: str) -> tuple[list[Any] | None, bool]:
    if not isinstance(value, (list, tuple)):
        return None, False
    check = _scalar_list_check(item_type)
    if any(not check(item) for item in value):
        return None, False
    return list(value), True


def _scalar_list_check(item_type: str) -> Any:
    checks = {
        "string": lambda item: isinstance(item, str),
        "integer": lambda item: isinstance(item, int) and not isinstance(item, bool),
        "number": lambda item: _is_finite_number(item),
        "boolean": lambda item: isinstance(item, bool),
    }
    return checks[item_type]


def _record_scalar_list_drift(
    value: Any,
    item_type: str,
    recorder: ResponseDriftRecorder,
    path: tuple[str, ...],
) -> None:
    if not isinstance(value, (list, tuple)):
        recorder.add_breaking_field(path, "array", value)
        return
    check = _scalar_list_check(item_type)
    for item in value:
        if not check(item):
            recorder.add_breaking_field((*path, "*"), item_type, item)


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
    recorder: ResponseDriftRecorder | None = None,
    path: tuple[str, ...] = (),
    known_omitted: Sequence[str] = (),
    uncontracted_expected_type: str = "json_scalar",
) -> tuple[Any, set[str], bool, bool]:
    """Project a contracted object or object list; scalar lists need typed contracts."""

    if allowed_keys is None:
        if recorder is not None:
            recorder.add_breaking_field(path, uncontracted_expected_type, value)
        return None, set(), False, False
    rules = _NestedProjectionRules(
        allowed=frozenset(allowed_keys),
        nested=nested_item_keys or {},
        known_omitted=known_omitted_nested_item_keys or {},
        opaque=frozenset(opaque_json_item_keys or ()),
    )
    if isinstance(value, Mapping):
        projected, unknown, breaking = _project_nested_mapping(
            value, path, rules, opaque_json_item_keys, recorder, known_omitted
        )
        return projected, unknown, breaking, True
    if isinstance(value, (list, tuple)):
        return _project_nested_sequence(
            value, path, rules, opaque_json_item_keys, recorder, known_omitted
        )
    if recorder is not None:
        recorder.add_breaking_field(path, "object_or_array", value)
    return None, set(), True, False


def _project_nested_mapping(
    item: Mapping[Any, Any],
    item_path: tuple[str, ...],
    rules: _NestedProjectionRules,
    opaque_json_item_keys: tuple[str, ...] | None,
    recorder: ResponseDriftRecorder | None,
    known_omitted: Sequence[str],
) -> tuple[dict[str, Any], set[str], bool]:
    unknown = {str(key) for key in item} - rules.allowed - set(known_omitted)
    if recorder is not None:
        recorder.add_unknown_fields(item_path, item, unknown)
    result: dict[str, Any] = {}
    breaking = False
    for key, nested_value in item.items():
        name = str(key)
        if name not in rules.allowed:
            continue
        if isinstance(nested_value, (Mapping, list, tuple)):
            if name in rules.opaque:
                opaque_json, valid = _copy_json_value(nested_value)
                if valid:
                    result[name] = opaque_json
                else:
                    breaking = True
                    if recorder is not None:
                        recorder.add_breaking_field(
                            (*item_path, name), "json", nested_value
                        )
                continue
            nested, nested_unknown, nested_breaking, contracted = (
                _project_nested_item_value(
                    nested_value,
                    rules.nested.get(name),
                    rules.nested,
                    rules.known_omitted,
                    opaque_json_item_keys,
                    recorder,
                    (*item_path, name),
                    rules.known_omitted.get(name, ()),
                )
            )
            if not contracted:
                breaking = True
                continue
            nested_unknown -= set(rules.known_omitted.get(name, ()))
            unknown.update(nested_unknown)
            breaking = breaking or nested_breaking
            result[name] = nested
            continue
        if not _is_json_scalar(nested_value):
            breaking = True
            if recorder is not None:
                recorder.add_breaking_field(
                    (*item_path, name), "json_scalar", nested_value
                )
            continue
        result[name] = nested_value
    return result, unknown, breaking


def _project_nested_sequence(
    value: Sequence[Any],
    path: tuple[str, ...],
    rules: _NestedProjectionRules,
    opaque_json_item_keys: tuple[str, ...] | None,
    recorder: ResponseDriftRecorder | None,
    known_omitted: Sequence[str],
) -> tuple[Any, set[str], bool, bool]:
    if not value:
        return [], set(), False, True
    projected_items: list[dict[str, Any]] = []
    unknown: set[str] = set()
    breaking = False
    for item in value:
        if not isinstance(item, Mapping):
            if recorder is not None:
                recorder.add_breaking_field((*path, "*"), "object", item)
            return None, set(), True, False
        projected, item_unknown, item_breaking = _project_nested_mapping(
            item, (*path, "*"), rules, opaque_json_item_keys,
            recorder, known_omitted,
        )
        projected_items.append(projected)
        unknown.update(item_unknown)
        breaking = breaking or item_breaking
    return projected_items, unknown, breaking, True


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
