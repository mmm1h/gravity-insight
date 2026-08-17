"""Shape-aware allowlists for nested response containers."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from .schema_sketch import safe_schema_key


NestedFields = dict[str, list[str]]
ContainerContract = tuple[list[str], list[str], NestedFields, NestedFields]


def merge_allowed_fields(
    target: NestedFields, name: str, fields: Sequence[str]
) -> None:
    values = set(fields)
    if name in target:
        values &= set(target[name])
    target[name] = sorted(values)


def merge_omitted_fields(
    target: NestedFields, name: str, fields: Sequence[str]
) -> None:
    target[name] = sorted(set(target.get(name, ())) | set(fields))


def _container_rows(
    values: Sequence[Any], path: str
) -> tuple[list[Mapping[Any, Any]], str] | None:
    if all(isinstance(value, Mapping) for value in values):
        return list(values), path
    if not all(isinstance(value, list) for value in values):
        return None
    rows = [item for value in values for item in value]
    if not rows or any(not isinstance(item, Mapping) for item in rows):
        return None
    return rows, f"{path}[]"


def _field_shapes(
    rows: Sequence[Mapping[Any, Any]],
) -> tuple[set[str], set[str], set[str], dict[str, list[Any]]]:
    all_keys: set[str] = set()
    scalar_keys: set[str] = set()
    mixed_keys: set[str] = set()
    child_values: dict[str, list[Any]] = {}
    for row in rows:
        for raw_name, value in row.items():
            name = safe_schema_key(raw_name)
            all_keys.add(name)
            if isinstance(value, (Mapping, list)):
                mixed_keys.update({name} & scalar_keys)
                child_values.setdefault(name, []).append(value)
            else:
                mixed_keys.update({name} & set(child_values))
                scalar_keys.add(name)
    return all_keys, scalar_keys, mixed_keys, child_values


def _merge_descendants(
    nested: NestedFields,
    nested_omitted: NestedFields,
    descendants: Mapping[str, Sequence[str]],
    descendant_hidden: Mapping[str, Sequence[str]],
) -> None:
    for name, fields in descendants.items():
        merge_allowed_fields(nested, name, fields)
    for name, fields in descendant_hidden.items():
        merge_omitted_fields(nested_omitted, name, fields)


def build_container_contract(
    values: Sequence[Any],
    path: str,
    classify: Callable[[str], str],
    *,
    depth: int = 0,
) -> ContainerContract:
    """Build fail-closed allowlists for an object or list-of-objects."""

    if not values or depth >= 8:
        return [], [], {}, {}
    container = _container_rows(values, path)
    if container is None:
        return [], [], {}, {}
    rows, prefix = container
    all_keys, scalar_keys, mixed_keys, child_values = _field_shapes(rows)
    safe = {
        name
        for name in scalar_keys - mixed_keys
        if classify(f"{prefix}.{name}") == "non_sensitive"
    }
    nested: NestedFields = {}
    nested_omitted: NestedFields = {}
    for name, children in child_values.items():
        if name in mixed_keys:
            continue
        child_safe, child_hidden, descendants, descendant_hidden = (
            build_container_contract(
                children,
                f"{prefix}.{name}",
                classify,
                depth=depth + 1,
            )
        )
        if not child_safe:
            continue
        safe.add(name)
        merge_allowed_fields(nested, name, child_safe)
        if child_hidden:
            merge_omitted_fields(nested_omitted, name, child_hidden)
        _merge_descendants(
            nested, nested_omitted, descendants, descendant_hidden
        )
    nested, nested_omitted = _reachable_nested(safe, nested, nested_omitted)
    return sorted(safe), sorted(all_keys - safe), nested, nested_omitted


def _reachable_nested(
    safe: set[str], nested: NestedFields, nested_omitted: NestedFields
) -> tuple[NestedFields, NestedFields]:
    reachable = set(safe)
    pending = list(safe)
    while pending:
        parent = pending.pop()
        for child in nested.get(parent, ()):
            if child not in reachable:
                reachable.add(child)
                pending.append(child)
    kept = {
        name: fields
        for name, fields in nested.items()
        if name in reachable and fields
    }
    return kept, {
        name: fields for name, fields in nested_omitted.items() if name in kept
    }
