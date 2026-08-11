"""Resolve declared parent-resource candidates without persisting their values."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any


_PERMISSION_STATUSES = {"permission_unavailable", "permission_error"}


def _recursive_values(value: Any, field: str) -> list[Any]:
    found: list[Any] = []
    if isinstance(value, Mapping):
        if field in value:
            found.append(value[field])
        for child in value.values():
            found.extend(_recursive_values(child, field))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for child in value:
            found.extend(_recursive_values(child, field))
    return found


def _path_children(items: Sequence[Any], raw_part: str) -> list[Any]:
    recursive = raw_part.startswith("@recursive:")
    part = raw_part.removeprefix("@recursive:")
    is_array = part.endswith("[]")
    part = part[:-2] if is_array else part
    result: list[Any] = []
    for item in items:
        children = _recursive_values(item, part) if recursive else (
            [item[part]] if isinstance(item, Mapping) and part in item else []
        )
        for child in children:
            if is_array and isinstance(child, Sequence) and not isinstance(
                child, (str, bytes)
            ):
                result.extend(child)
            else:
                result.append(child)
    return result


def extract_parent_values(value: Any, output_path: str) -> list[Any]:
    """Extract scalar values from the operation-v2 parent output-path syntax."""

    current: list[Any] = [value]
    normalized_path = output_path.replace("..", ".@recursive:")
    for raw_part in normalized_path.split("."):
        if raw_part:
            current = _path_children(current, raw_part)
    result: list[Any] = []
    for item in current:
        if item is None or isinstance(item, (Mapping, list, tuple)):
            continue
        if item not in result:
            result.append(item)
    return result


def coerce_parent_value(value: Any, field_type: str) -> Any:
    """Coerce one scalar parent candidate to its declared target field type."""

    scalar = isinstance(value, (str, int, float)) and not isinstance(value, bool)
    if field_type == "string" and scalar:
        return str(value)
    if field_type not in {"integer", "number"} or not scalar:
        return value
    try:
        return int(value) if field_type == "integer" else float(value)
    except (TypeError, ValueError, OverflowError):
        return value


def _target_cardinality(description: Mapping[str, Any], target: str | None) -> str:
    schema = description.get("input_schema", {})
    field = schema.get(target) if target and isinstance(schema, Mapping) else None
    return "many" if isinstance(field, Mapping) and field.get("type") == "array" else "one"


def _selected(values: list[Any], selection: str | None) -> Any:
    if selection == "first":
        return values[0] if values else None
    if selection == "unique":
        return values[0] if len(values) == 1 else None
    if selection == "all":
        return values
    return None


def _exception_status(exc: Exception) -> str:
    code = getattr(exc, "code", None)
    if code is None:
        detail = getattr(exc, "detail", None)
        code = getattr(detail, "code", None)
    normalized = str(code or type(exc).__name__).casefold()
    if "permission" in normalized or "forbidden" in normalized:
        return "permission_unavailable"
    if "auth" in normalized:
        return "auth_unavailable"
    return "undetermined"


def _probe_once(
    parent_id: str,
    probe_parent: Callable[[str], Mapping[str, Any]],
    cache: dict[str, Mapping[str, Any]],
    errors: dict[str, Exception],
) -> Mapping[str, Any]:
    if parent_id in errors:
        raise errors[parent_id]
    if parent_id not in cache:
        try:
            cache[parent_id] = probe_parent(parent_id)
        except Exception as exc:
            errors[parent_id] = exc
            raise
    return cache[parent_id]


def _binding_status(parent_status: str, values: Sequence[Any]) -> str:
    if values:
        return "resolved"
    if parent_status in _PERMISSION_STATUSES:
        return "permission_unavailable"
    return "empty" if parent_status == "empty" else "undetermined"


def _resolve_binding(
    description: Mapping[str, Any],
    parent: Mapping[str, Any],
    probe_parent: Callable[[str], Mapping[str, Any]],
    cache: dict[str, Mapping[str, Any]],
    errors: dict[str, Exception],
) -> dict[str, Any]:
    parent_id = str(parent.get("operation_id") or "")
    output_path = str(parent.get("output_path") or "")
    target = str(parent.get("target_input") or "") or None
    selection = str(parent.get("selection") or "caller_select")
    row: dict[str, Any] = {
        "parent_operation_id": parent_id,
        "output_path": output_path or None,
        "target_input": target,
        "target_cardinality": _target_cardinality(description, target),
        "selection": selection,
    }
    if not parent_id or not output_path:
        return {**row, "status": "undetermined", "candidate_count": 0, "candidates": []}
    try:
        envelope = _probe_once(parent_id, probe_parent, cache, errors)
    except Exception as exc:  # public clients expose structured exception codes
        return {
            **row,
            "status": _exception_status(exc),
            "candidate_count": 0,
            "candidates": [],
        }
    values = extract_parent_values(envelope, output_path)
    return {
        **row,
        "status": _binding_status(str(envelope.get("status", "error")), values),
        "candidate_count": len(values),
        "candidate_types": sorted({type(item).__name__ for item in values}),
        "candidates": values,
        "selected": _selected(values, selection),
    }


def _overall_status(bindings: Sequence[Mapping[str, Any]]) -> str:
    statuses = {str(item.get("status", "undetermined")) for item in bindings}
    if statuses - {"resolved", "empty", "permission_unavailable"}:
        return "undetermined"
    if "permission_unavailable" in statuses:
        return "permission_unavailable"
    return "empty" if "empty" in statuses else "resolved"


def resolve_declared_parents(
    description: Mapping[str, Any],
    probe_parent: Callable[[str], Mapping[str, Any]],
) -> dict[str, Any]:
    """Resolve every declared parent and return candidates plus safe selection state."""

    operation_id = str(description.get("operation_id", ""))
    parents = description.get("required_parent", [])
    if not isinstance(parents, list) or not parents:
        return {
            "schema_version": "gravity-insight.parent-resolution.v1",
            "ok": True,
            "operation_id": operation_id,
            "status": "not_required",
            "bindings": [],
            "values_persisted": False,
        }

    bindings: list[dict[str, Any]] = []
    cache: dict[str, Mapping[str, Any]] = {}
    errors: dict[str, Exception] = {}
    for parent in parents:
        if not isinstance(parent, Mapping):
            bindings.append({"status": "undetermined", "reason": "invalid_binding"})
        else:
            bindings.append(
                _resolve_binding(description, parent, probe_parent, cache, errors)
            )
    return {
        "schema_version": "gravity-insight.parent-resolution.v1",
        "ok": True,
        "operation_id": operation_id,
        "status": _overall_status(bindings),
        "bindings": bindings,
        "values_persisted": False,
    }


__all__ = [
    "coerce_parent_value",
    "extract_parent_values",
    "resolve_declared_parents",
]
