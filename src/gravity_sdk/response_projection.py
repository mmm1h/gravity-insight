"""Contracted response data-container projection."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from .drift import ProjectionDrift
from .models import OperationSpec
from .multidim import projected_keys
from .response_drift import ResponseDriftRecorder


def _project_data_containers(
    operation: OperationSpec,
    projected: Any,
    values: Mapping[str, Any],
    recorder: ResponseDriftRecorder,
) -> tuple[Any, tuple[str, ...], ProjectionDrift]:
    if not isinstance(projected, Mapping):
        return projected, (), ProjectionDrift.NONE
    copied = dict(projected)
    warnings: list[str] = []
    drift = ProjectionDrift.NONE
    copied, path_warnings, path_drift, contracted_roots = _project_data_path_items(
        operation, copied, recorder
    )
    warnings.extend(path_warnings)
    drift = max(drift, path_drift)
    primary_list = operation.pagination.list_path.rsplit(".", 1)[-1]
    if not primary_list and "list" in operation.response_projection.data_keys:
        primary_list = "list"
    page_info_name = operation.pagination.page_info_path.rsplit(".", 1)[-1]
    for name, value in tuple(copied.items()):
        if name in contracted_roots:
            continue
        copied, field_warnings, field_drift = _project_data_container_field(
            operation, copied, name, value, values, recorder, primary_list, page_info_name
        )
        warnings.extend(field_warnings)
        drift = max(drift, field_drift)
    return copied, tuple(warnings), drift


def _project_data_container_field(
    operation: OperationSpec,
    copied: dict[str, Any],
    name: str,
    value: Any,
    values: Mapping[str, Any],
    recorder: ResponseDriftRecorder,
    primary_list: str,
    page_info_name: str,
) -> tuple[dict[str, Any], tuple[str, ...], ProjectionDrift]:
    scalar_list_type = operation.response_projection.data_scalar_list_types.get(name)
    if scalar_list_type is not None:
        return _apply_data_scalar_list(copied, name, value, scalar_list_type)
    if name == primary_list and isinstance(value, list):
        return copied, (), ProjectionDrift.NONE
    if name == page_info_name and isinstance(value, Mapping):
        return _apply_data_page_info(operation, copied, name, value, recorder)
    if _is_json_scalar(value):
        return copied, (), ProjectionDrift.NONE
    if not isinstance(value, (Mapping, list, tuple)):
        copied.pop(name, None)
        return copied, ("non-JSON response data values were omitted (count=1)",), ProjectionDrift.BREAKING
    recursive_allowed = operation.response_projection.recursive_data_item_keys.get(name)
    if recursive_allowed is not None:
        return _apply_recursive_data_collection(
            copied, name, value, recursive_allowed, recorder
        )
    return _apply_nested_data_container(operation, copied, name, value, values, recorder)


def _apply_data_scalar_list(
    copied: dict[str, Any], name: str, value: Any, scalar_list_type: str
) -> tuple[dict[str, Any], tuple[str, ...], ProjectionDrift]:
    scalar_list, valid = _project_scalar_list(value, scalar_list_type)
    if valid:
        copied[name] = scalar_list
        return copied, (), ProjectionDrift.NONE
    copied.pop(name, None)
    return copied, ("invalid contracted response scalar list was omitted",), ProjectionDrift.BREAKING


def _apply_data_page_info(
    operation: OperationSpec,
    copied: dict[str, Any],
    name: str,
    value: Mapping[Any, Any],
    recorder: ResponseDriftRecorder,
) -> tuple[dict[str, Any], tuple[str, ...], ProjectionDrift]:
    copied[name], warning, item_drift = _project_page_info(
        operation, name, value, recorder
    )
    return copied, ((warning,) if warning else ()), item_drift


def _apply_recursive_data_collection(
    copied: dict[str, Any],
    name: str,
    value: Any,
    recursive_allowed: tuple[str, ...],
    recorder: ResponseDriftRecorder,
) -> tuple[dict[str, Any], tuple[str, ...], ProjectionDrift]:
    recursive, recursive_unknown, recursive_breaking, contracted = (
        _project_recursive_collection(
            value, recursive_allowed, recorder, ("data", name)
        )
    )
    if not contracted:
        copied.pop(name, None)
        return copied, ("invalid recursive response collection was omitted",), ProjectionDrift.BREAKING
    copied[name] = recursive
    warnings: list[str] = []
    drift = ProjectionDrift.NONE
    if recursive_unknown:
        warnings.append(
            "unregistered recursive response item keys were omitted "
            f"(count={len(recursive_unknown)})"
        )
        drift = max(drift, ProjectionDrift.ADDITIVE)
    if recursive_breaking:
        drift = ProjectionDrift.BREAKING
    return copied, tuple(warnings), drift


def _apply_nested_data_container(
    operation: OperationSpec,
    copied: dict[str, Any],
    name: str,
    value: Any,
    values: Mapping[str, Any],
    recorder: ResponseDriftRecorder,
) -> tuple[dict[str, Any], tuple[str, ...], ProjectionDrift]:
    static_allowed = operation.response_projection.data_item_keys.get(name)
    dynamic_inputs = operation.response_projection.data_dynamic_item_fields.get(name, ())
    numeric_inputs = operation.response_projection.data_numeric_suffix_item_fields.get(name, ())
    dynamic_allowed = projected_keys((), dynamic_inputs, numeric_inputs, values, value)
    allowed = (
        tuple(dict.fromkeys((*(static_allowed or ()), *sorted(dynamic_allowed))))
        if static_allowed is not None or dynamic_inputs
        else None
    )
    nested, unknown, nested_breaking, contracted = _project_nested_item_value(
        value,
        allowed,
        operation.response_projection.nested_item_keys,
        operation.response_projection.known_omitted_nested_item_keys,
        operation.response_projection.opaque_json_item_keys,
        recorder,
        ("data", name),
        operation.response_projection.known_omitted_data_item_keys.get(name, ()),
    )
    unknown -= set(
        operation.response_projection.known_omitted_data_item_keys.get(name, ())
    )
    if not contracted:
        copied.pop(name, None)
        return (
            copied,
            ("uncontracted response data containers were omitted (count=1)",),
            ProjectionDrift.BREAKING,
        )
    copied[name] = nested
    warnings: list[str] = []
    drift = ProjectionDrift.NONE
    if unknown:
        warnings.append(
            f"unregistered response data item keys were omitted (count={len(unknown)})"
        )
        drift = max(drift, ProjectionDrift.ADDITIVE)
    if nested_breaking:
        drift = ProjectionDrift.BREAKING
    return copied, tuple(warnings), drift


def _project_page_info(
    operation: OperationSpec,
    name: str,
    value: Mapping[Any, Any],
    recorder: ResponseDriftRecorder,
) -> tuple[dict[str, Any], str | None, ProjectionDrift]:
    allowed = {
        operation.pagination.page_field,
        operation.pagination.page_size_field,
        operation.pagination.total_page_field,
        "total",
        "total_number",
    }
    unknown = {str(key) for key in value} - allowed
    invalid = {
        str(key) for key, item in value.items()
        if str(key) in allowed and not _is_json_scalar(item)
    }
    projected = {
        str(key): item for key, item in value.items()
        if str(key) in allowed and _is_json_scalar(item)
    }
    if not unknown and not invalid:
        return projected, None, ProjectionDrift.NONE
    recorder.add_unknown_fields(("data", name), value, unknown)
    warning = (
        "unregistered or non-scalar page_info fields were omitted "
        f"(count={len(unknown | invalid)})"
    )
    drift = ProjectionDrift.BREAKING if invalid else ProjectionDrift.ADDITIVE
    return projected, warning, drift


def _project_recursive_collection(
    value: Any,
    allowed_keys: tuple[str, ...],
    recorder: ResponseDriftRecorder,
    path: tuple[str, ...],
) -> tuple[Any, set[str], bool, bool]:
    allowed = set(allowed_keys)

    def project_row(
        row: Mapping[Any, Any], row_path: tuple[str, ...]
    ) -> tuple[dict[str, Any], set[str], bool]:
        row_keys = {str(key) for key in row}
        unknown = row_keys - allowed
        recorder.add_unknown_fields(row_path, row, unknown)
        result: dict[str, Any] = {}
        breaking = False
        for key, item in row.items():
            name = str(key)
            if name not in allowed:
                continue
            if name == "children":
                nested, nested_unknown, nested_breaking, contracted = (
                    _project_recursive_collection(
                        item, allowed_keys, recorder, (*row_path, name)
                    )
                )
                if contracted:
                    result[name] = nested
                    unknown.update(nested_unknown)
                    breaking = breaking or nested_breaking
                else:
                    breaking = True
            elif isinstance(item, (Mapping, list, tuple)) or not _is_json_scalar(item):
                breaking = True
            else:
                result[name] = item
        return result, unknown, breaking

    if isinstance(value, Mapping):
        projected, unknown, breaking = project_row(value, path)
        return projected, unknown, breaking, True
    if isinstance(value, (list, tuple)):
        if any(not isinstance(item, Mapping) for item in value):
            return None, set(), True, False
        result: list[dict[str, Any]] = []
        unknown: set[str] = set()
        breaking = False
        for item in value:
            projected, item_unknown, item_breaking = project_row(item, (*path, "*"))
            result.append(projected)
            unknown.update(item_unknown)
            breaking = breaking or item_breaking
        return result, unknown, breaking, True
    return None, set(), True, False


def _project_data_path_items(
    operation: OperationSpec,
    projected: Mapping[str, Any],
    recorder: ResponseDriftRecorder,
) -> tuple[dict[str, Any], tuple[str, ...], ProjectionDrift, set[str]]:
    rules_by_root: dict[str, dict[str, tuple[str, ...]]] = {}
    for path, keys in operation.response_projection.data_path_item_keys.items():
        root, child = path.split(".", 1)
        rules_by_root.setdefault(root, {})[child] = keys
    if not rules_by_root:
        return dict(projected), (), ProjectionDrift.NONE, set()

    copied = dict(projected)
    warnings: list[str] = []
    drift = ProjectionDrift.NONE
    for root, child_rules in rules_by_root.items():
        value = projected.get(root)
        if not isinstance(value, Mapping):
            copied.pop(root, None)
            warnings.append("contracted nested response data is absent or invalid")
            drift = ProjectionDrift.BREAKING
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
            recorder.add_unknown_fields(("data", root), value, unknown_children)
            warnings.append(
                f"unregistered nested response paths were omitted (count={len(unknown_children)})"
            )
            drift = max(drift, ProjectionDrift.ADDITIVE)
        for child, allowed in child_rules.items():
            if child not in value:
                continue
            nested, unknown, nested_breaking, contracted = _project_nested_item_value(
                value[child],
                allowed,
                operation.response_projection.nested_item_keys,
                operation.response_projection.known_omitted_nested_item_keys,
                operation.response_projection.opaque_json_item_keys,
                recorder,
                ("data", root, child),
                operation.response_projection.known_omitted_data_item_keys.get(root, ()),
            )
            if not contracted:
                warnings.append("invalid contracted nested response collection was omitted")
                drift = ProjectionDrift.BREAKING
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
                drift = max(drift, ProjectionDrift.ADDITIVE)
            if nested_breaking:
                drift = ProjectionDrift.BREAKING
        copied[root] = safe_root
    return copied, tuple(warnings), drift, set(rules_by_root)


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
    recorder: ResponseDriftRecorder | None = None,
    path: tuple[str, ...] = (),
    known_omitted: Sequence[str] = (),
) -> tuple[Any, set[str], bool, bool]:
    """Project a contracted object or object list; scalar lists need typed contracts."""

    if allowed_keys is None:
        return None, set(), False, False
    allowed = set(allowed_keys)
    nested_contracts = nested_item_keys or {}
    known_omitted_contracts = known_omitted_nested_item_keys or {}
    opaque_contracts = set(opaque_json_item_keys or ())

    def project_mapping(
        item: Mapping[Any, Any], item_path: tuple[str, ...]
    ) -> tuple[dict[str, Any], set[str], bool]:
        unknown = {str(key) for key in item} - allowed - set(known_omitted)
        if recorder is not None:
            recorder.add_unknown_fields(item_path, item, unknown)
        result: dict[str, Any] = {}
        breaking = False
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
                        breaking = True
                    continue
                nested_allowed = nested_contracts.get(name)
                nested, nested_unknown, nested_breaking, contracted = _project_nested_item_value(
                    nested_value,
                    nested_allowed,
                    nested_contracts,
                    known_omitted_contracts,
                    opaque_json_item_keys,
                    recorder,
                    (*item_path, name),
                    known_omitted_contracts.get(name, ()),
                )
                if not contracted:
                    breaking = True
                    continue
                nested_unknown -= set(known_omitted_contracts.get(name, ()))
                unknown.update(nested_unknown)
                breaking = breaking or nested_breaking
                result[name] = nested
                continue
            if not _is_json_scalar(nested_value):
                breaking = True
                continue
            result[name] = nested_value
        return result, unknown, breaking

    if isinstance(value, Mapping):
        projected, unknown, breaking = project_mapping(value, path)
        return projected, unknown, breaking, True
    if isinstance(value, (list, tuple)):
        if not value:
            return [], set(), False, True
        projected_items: list[dict[str, Any]] = []
        unknown: set[str] = set()
        breaking = False
        for item in value:
            if not isinstance(item, Mapping):
                return None, set(), True, False
            projected, item_unknown, item_breaking = project_mapping(
                item, (*path, "*")
            )
            projected_items.append(projected)
            unknown.update(item_unknown)
            breaking = breaking or item_breaking
        return projected_items, unknown, breaking, True
    return None, set(), True, False


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

