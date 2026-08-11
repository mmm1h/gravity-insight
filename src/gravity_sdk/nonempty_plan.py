"""Contract-driven candidate planning for non-empty discovery."""

from __future__ import annotations

import copy
import heapq
import json
import math
import re
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

from .parent_resolution import coerce_parent_value
from .prober.core import REPO_ROOT, canonical_fingerprint


DEFAULT_REQUEST_BUDGET = 12
DEFAULT_CANDIDATE_LIMIT = 5
DEFAULT_INTERVAL_SECONDS = 0.31
DEFAULT_CACHE_ROOT = REPO_ROOT / "tmp" / "codex" / "gi-nonempty" / "cache"
_DATE_TOKEN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass(frozen=True)
class SearchDimension:
    label: str
    source: str
    patches: tuple[Mapping[str, Any], ...]
    weight: int


def _dedupe(values: Sequence[Any]) -> list[Any]:
    seen: set[str] = set()
    result: list[Any] = []
    for value in values:
        marker = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
        if marker not in seen:
            seen.add(marker)
            result.append(value)
    return result


def _dynamic_tokens(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value.startswith("$") else []
    if isinstance(value, Mapping):
        return [token for item in value.values() for token in _dynamic_tokens(item)]
    if isinstance(value, (list, tuple)):
        return [token for item in value for token in _dynamic_tokens(item)]
    return []


def _resolve_dates(value: Any, anchor: date) -> Any:
    if value == "$today":
        return anchor.isoformat()
    if value == "$yesterday":
        return (anchor - timedelta(days=1)).isoformat()
    if isinstance(value, Mapping):
        return {str(key): _resolve_dates(item, anchor) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_resolve_dates(item, anchor) for item in value]
    return copy.deepcopy(value)


def _is_date_value(value: Any) -> bool:
    return isinstance(value, str) and bool(_DATE_TOKEN.fullmatch(value))


def _array_date_values(
    resolved: list[str], tokens: Sequence[str], anchor: date
) -> list[list[str]]:
    end = anchor if tokens else max(date.fromisoformat(item) for item in resolved)
    return [
        (
            [(end - timedelta(days=length - 1)).isoformat(), end.isoformat()]
            if len(resolved) == 2
            else [(end - timedelta(days=length - 1)).isoformat()]
        )
        for length in (30, 7, 1, 90)
    ]


def _scalar_date_values(resolved: str, tokens: Sequence[str], anchor: date) -> list[str]:
    end = anchor if tokens else date.fromisoformat(resolved)
    return [(end - timedelta(days=offset)).isoformat() for offset in (0, 1, 7, 30)]


def _date_dimension(
    field_name: str,
    field: Mapping[str, Any],
    value: Any,
    *,
    anchor: date,
    explicit_seed: bool,
) -> SearchDimension | None:
    tokens = _dynamic_tokens(value)
    resolved = _resolve_dates(value, anchor)
    is_scalar = field.get("type") == "date" and _is_date_value(resolved)
    is_array = (
        isinstance(resolved, list)
        and 1 <= len(resolved) <= 2
        and all(_is_date_value(item) for item in resolved)
        and (bool(tokens) or field.get("item_type") == "date")
    )
    if not is_scalar and not is_array:
        return None
    values: list[Any] = [resolved] if explicit_seed else []
    if is_array:
        values.extend(_array_date_values(resolved, tokens, anchor))
    else:
        values.extend(_scalar_date_values(str(resolved), tokens, anchor))
    patches = tuple({field_name: item} for item in _dedupe(values))
    return SearchDimension(field_name, "date_window", patches, 3)


def _contains_placeholder(value: Any) -> bool:
    return bool(_dynamic_tokens(value))


def _seed_inputs(operation: Mapping[str, Any], overrides: Mapping[str, Any]) -> dict[str, Any]:
    request = operation.get("request", {})
    seed = copy.deepcopy(dict(request.get("defaults", {}))) if isinstance(request, Mapping) else {}
    live_probe = operation.get("live_probe", {})
    live_inputs = live_probe.get("inputs", {}) if isinstance(live_probe, Mapping) else {}
    if isinstance(live_inputs, Mapping):
        seed.update(copy.deepcopy(dict(live_inputs)))
    seed.update(copy.deepcopy(dict(overrides)))
    return seed


def _parent_plan(
    fields: Mapping[str, Any],
    parent_values: Mapping[str, Sequence[Any]],
    parent_failures: Mapping[str, str],
    parent_dimensions: Sequence[SearchDimension] = (),
) -> tuple[list[SearchDimension], list[dict[str, str]], set[str]]:
    dimensions: list[SearchDimension] = []
    unresolved: list[dict[str, str]] = []
    handled: set[str] = set()
    for name, values in parent_values.items():
        field = fields.get(name, {})
        field = field if isinstance(field, Mapping) else {}
        field_type = str(field.get("type", "any"))
        item_type = str(field.get("item_type", "any"))
        candidates = [
            [coerce_parent_value(value, item_type)]
            if field_type == "array"
            else coerce_parent_value(value, field_type)
            for value in values
        ]
        dimensions.append(
            SearchDimension(
                name,
                "required_parent",
                tuple({name: item} for item in _dedupe(candidates)),
                1,
            )
        )
        handled.add(name)
    for name, reason in parent_failures.items():
        unresolved.append({"field": name, "reason": reason})
        handled.add(name)
    for dimension in parent_dimensions:
        grouped_fields = {
            str(name)
            for patch in dimension.patches
            for name in patch
            if str(name) in fields
        }
        if grouped_fields:
            dimensions.append(dimension)
            handled.update(grouped_fields)
    return dimensions, unresolved, handled


def _enum_dimension(
    name: str, source: str, values: Sequence[Any]
) -> SearchDimension:
    return SearchDimension(
        name,
        source,
        tuple({name: item} for item in _dedupe(values)),
        2,
    )


def _field_dimension(
    name: str,
    field: Mapping[str, Any],
    *,
    present: bool,
    value: Any,
    explicit_seed: bool,
    anchor: date,
) -> SearchDimension | None:
    enum = field.get("enum", [])
    if isinstance(enum, list) and enum:
        candidates = ([value] if present and not _contains_placeholder(value) else []) + enum
        return _enum_dimension(name, "enum", candidates)
    item_enum = field.get("item_enum", [])
    if isinstance(item_enum, list) and item_enum:
        candidates = ([value] if present and value else []) + [[item] for item in item_enum]
        return _enum_dimension(name, "item_enum", candidates)
    if present:
        date_dimension = _date_dimension(
            name, field, value, anchor=anchor, explicit_seed=explicit_seed
        )
        if date_dimension is not None:
            return date_dimension
    if field.get("type") == "boolean" and present:
        dimension = _enum_dimension(name, "boolean", [value, not bool(value)])
        return SearchDimension(name, "boolean", dimension.patches, 4)
    return None


def _missing_candidate_reason(field: Mapping[str, Any], present: bool) -> str:
    if field.get("required") is True:
        return "required_input_has_no_candidates"
    return "dynamic_placeholder_unresolved" if present else "optional_input_has_no_candidates"


def _plan_field(
    name: str,
    field: Mapping[str, Any],
    *,
    seed: Mapping[str, Any],
    overrides: Mapping[str, Any],
    anchor: date,
    pagination_controls: set[str],
    base: dict[str, Any],
    dimensions: list[SearchDimension],
    unresolved: list[dict[str, str]],
) -> None:
    present = name in seed
    value = seed.get(name)
    dimension = _field_dimension(
        name,
        field,
        present=present,
        value=value,
        explicit_seed=name in overrides,
        anchor=anchor,
    )
    if dimension is not None:
        dimensions.append(dimension)
        return
    field_type = str(field.get("type", "any"))
    if present and not _dynamic_tokens(value):
        base[name] = copy.deepcopy(value)
        if name in pagination_controls:
            return
        reason = (
            "opaque_candidate_space"
            if field_type in {"array", "object"}
            else "scalar_candidate_space_unbounded"
        )
        unresolved.append({"field": name, "reason": reason})
        return
    unresolved.append({"field": name, "reason": _missing_candidate_reason(field, present)})


def _build_plan(
    source: Mapping[str, Any],
    *,
    overrides: Mapping[str, Any],
    parent_values: Mapping[str, Sequence[Any]],
    parent_failures: Mapping[str, str],
    parent_dimensions: Sequence[SearchDimension] = (),
    anchor: date,
) -> tuple[dict[str, Any], list[SearchDimension], list[dict[str, str]]]:
    operation = source["operation"]
    fields = operation.get("input_fields", {})
    if not isinstance(fields, Mapping):
        raise ValueError("operation input_fields must be an object")
    seed = _seed_inputs(operation, overrides)
    dimensions, unresolved, handled = _parent_plan(
        fields, parent_values, parent_failures, parent_dimensions
    )
    base: dict[str, Any] = {}
    pagination = operation.get("pagination", {})
    pagination_controls = {
        str(pagination.get(key))
        for key in ("page_field", "page_size_field")
        if isinstance(pagination, Mapping) and pagination.get(key)
    }
    for raw_name, raw_field in fields.items():
        name = str(raw_name)
        if name in handled:
            continue
        field = raw_field if isinstance(raw_field, Mapping) else {}
        _plan_field(
            name,
            field,
            seed=seed,
            overrides=overrides,
            anchor=anchor,
            pagination_controls=pagination_controls,
            base=base,
            dimensions=dimensions,
            unresolved=unresolved,
        )
    return base, dimensions, unresolved


def _iter_combinations(
    base: Mapping[str, Any], dimensions: Sequence[SearchDimension]
) -> Iterator[dict[str, Any]]:
    if not dimensions:
        yield copy.deepcopy(dict(base))
        return
    origin = tuple(0 for _ in dimensions)
    heap: list[tuple[int, tuple[int, ...]]] = [(0, origin)]
    queued = {origin}
    emitted: set[str] = set()
    while heap:
        _, coordinates = heapq.heappop(heap)
        candidate = copy.deepcopy(dict(base))
        for dimension, index in zip(dimensions, coordinates):
            candidate.update(copy.deepcopy(dict(dimension.patches[index])))
        marker = canonical_fingerprint(candidate)
        if marker not in emitted:
            emitted.add(marker)
            yield candidate
        for dimension_index, dimension in enumerate(dimensions):
            next_index = coordinates[dimension_index] + 1
            if next_index >= len(dimension.patches):
                continue
            neighbor = list(coordinates)
            neighbor[dimension_index] = next_index
            selected = tuple(neighbor)
            if selected in queued:
                continue
            queued.add(selected)
            score = sum(
                item.weight * selected[index]
                for index, item in enumerate(dimensions)
            )
            heapq.heappush(heap, (score, selected))


def _plan_size(dimensions: Sequence[SearchDimension]) -> int:
    return math.prod(len(item.patches) for item in dimensions) if dimensions else 1


__all__ = [
    "DEFAULT_CACHE_ROOT",
    "DEFAULT_CANDIDATE_LIMIT",
    "DEFAULT_INTERVAL_SECONDS",
    "DEFAULT_REQUEST_BUDGET",
    "SearchDimension",
    "_build_plan",
    "_contains_placeholder",
    "_dynamic_tokens",
    "_iter_combinations",
    "_plan_size",
    "_resolve_dates",
    "_seed_inputs",
]
