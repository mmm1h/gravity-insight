"""Parent candidate resolution for bounded non-empty discovery."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, Mapping, Sequence

from .nonempty_plan import (
    DEFAULT_CANDIDATE_LIMIT,
    SearchDimension,
    _contains_placeholder,
    _dynamic_tokens,
    _resolve_dates,
    _seed_inputs,
)
from .parent_resolution import (
    coerce_parent_value,
    extract_parent_items,
    extract_parent_values,
)
from .prober.core import canonical_fingerprint, read_json
from .prober.probe_support import family_id, last_primary
from .prober.transport import HttpObservation, RecordingSession


ParentCache = dict[str, tuple[Any, HttpObservation | None, str | None]]
ParentBinding = tuple[str, Mapping[str, Any]]
RowBinding = tuple[str, str, str]


def _target_parent_field(
    parent: Mapping[str, Any], operation: Mapping[str, Any], seed: Mapping[str, Any]
) -> str | None:
    fields = operation.get("input_fields", {})
    declared = parent.get("input_field")
    if declared and isinstance(fields, Mapping) and declared in fields:
        return str(declared)
    candidates = [
        str(name)
        for name, value in seed.items()
        if _contains_placeholder(value)
        and set(_dynamic_tokens(value)) - {"$today", "$yesterday"}
    ]
    return candidates[0] if len(candidates) == 1 else None


def _simple_parent_inputs(
    source: Mapping[str, Any], anchor: date
) -> dict[str, Any] | None:
    operation = source["operation"]
    live_probe = operation.get("live_probe", {})
    raw = live_probe.get("inputs", {}) if isinstance(live_probe, Mapping) else {}
    if not isinstance(raw, Mapping):
        return None
    resolved = _resolve_dates(raw, anchor)
    if _dynamic_tokens(resolved):
        return None
    request = operation.get("request", {})
    inputs = dict(request.get("defaults", {})) if isinstance(request, Mapping) else {}
    inputs.update(resolved)
    pagination = operation.get("pagination", {})
    if isinstance(pagination, Mapping) and pagination.get("kind") == "page_info":
        if pagination.get("page_field"):
            inputs[str(pagination["page_field"])] = 1
        if pagination.get("page_size_field"):
            inputs[str(pagination["page_size_field"])] = min(
                DEFAULT_CANDIDATE_LIMIT,
                int(pagination.get("max_page_size") or DEFAULT_CANDIDATE_LIMIT),
            )
    return inputs


def _call_parent(
    operation_id: str,
    source: Mapping[str, Any],
    inputs: Mapping[str, Any] | None,
    *,
    stable_client: Any,
    recording: RecordingSession,
    target_source: Mapping[str, Any],
    candidate_limit: int,
) -> tuple[Any, HttpObservation | None, str | None]:
    selected = _bounded_parent_inputs(source, inputs, candidate_limit)
    start = len(recording.observations)
    local_error_type = None
    try:
        with recording.observing(
            operation_id, family_id(target_source), "nonempty_parent_candidates"
        ):
            envelope = (
                stable_client.probe(operation_id)
                if selected is None
                else stable_client.read(operation_id, selected)
            )
    except Exception as error:
        envelope = {}
        local_error_type = type(error).__name__
    return (
        envelope,
        last_primary(recording.observations[start:], operation_id),
        local_error_type,
    )


def _bounded_parent_inputs(
    source: Mapping[str, Any],
    inputs: Mapping[str, Any] | None,
    candidate_limit: int,
) -> dict[str, Any] | None:
    if inputs is None:
        return None
    selected = dict(inputs)
    pagination = source["operation"].get("pagination", {})
    if isinstance(pagination, Mapping) and pagination.get("page_size_field"):
        size_field = str(pagination["page_size_field"])
        selected[size_field] = min(
            candidate_limit,
            int(pagination.get("max_page_size") or candidate_limit),
        )
    return selected


def _parent_payload(cached: tuple[Any, HttpObservation | None, str | None]) -> Any:
    envelope, primary, local_error_type = cached
    if local_error_type is not None:
        return None
    if isinstance(envelope, Mapping):
        return envelope
    return primary.payload if primary is not None else None


def _fetch_parent_candidates(
    parent: Mapping[str, Any],
    *,
    target_source: Mapping[str, Any],
    stable_client: Any,
    recording: RecordingSession,
    candidate_limit: int,
    operation_root: Path,
    anchor: date,
    parent_cache: ParentCache,
) -> tuple[list[Any], dict[str, Any]]:
    operation_id = str(parent.get("operation_id", ""))
    output_path = str(parent.get("output_path", ""))
    path = operation_root / f"{operation_id}.json"
    if not operation_id or not output_path or not path.is_file():
        return [], _parent_summary(operation_id, output_path, "metadata_unavailable")
    source = read_json(path)
    if operation_id not in parent_cache:
        parent_cache[operation_id] = _call_parent(
            operation_id,
            source,
            _simple_parent_inputs(source, anchor),
            stable_client=stable_client,
            recording=recording,
            target_source=target_source,
            candidate_limit=candidate_limit,
        )
    cached = parent_cache[operation_id]
    envelope, primary, local_error_type = cached
    if local_error_type is not None:
        return [], _parent_summary(
            operation_id,
            output_path,
            "local_error",
            primary=primary,
            local_error_type=local_error_type,
        )
    payload = _parent_payload(cached)
    values = extract_parent_values(payload, output_path) if payload is not None else []
    selected = _unique_values(values)[:candidate_limit]
    status = "resolved" if selected else "empty_or_unavailable"
    return selected, _parent_summary(
        operation_id, output_path, status, len(selected), primary
    )


def _unique_values(values: Sequence[Any]) -> list[Any]:
    result: list[Any] = []
    markers: set[str] = set()
    for value in values:
        marker = canonical_fingerprint(value)
        if marker not in markers:
            markers.add(marker)
            result.append(value)
    return result


def _parent_summary(
    operation_id: str,
    output_path: str,
    status: str,
    count: int = 0,
    primary: HttpObservation | None = None,
    local_error_type: str | None = None,
) -> dict[str, Any]:
    result = {
        "operation_id": operation_id,
        "output_path": output_path,
        "status": status,
        "candidate_count": count,
        "http_status": primary.status_code if primary else None,
    }
    if local_error_type is not None:
        result["local_error_type"] = local_error_type
    return result


def _row_binding(target: str, parent: Mapping[str, Any]) -> RowBinding | None:
    output_path = str(parent.get("output_path", ""))
    marker = output_path.find("[]")
    if marker < 0 or ".." in output_path:
        return None
    container = output_path[: marker + 2]
    leaf = output_path[marker + 2 :].lstrip(".")
    if not leaf or "[]" in leaf:
        return None
    return target, container, leaf


def _row_bindings(bindings: Sequence[ParentBinding]) -> tuple[RowBinding, ...]:
    parsed = tuple(_row_binding(target, parent) for target, parent in bindings)
    if any(item is None for item in parsed):
        return ()
    rows = tuple(item for item in parsed if item is not None)
    return rows if len({container for _, container, _ in rows}) == 1 else ()


def _coerce_target(
    operation: Mapping[str, Any], target: str, value: Any
) -> Any:
    fields = operation.get("input_fields", {})
    field = fields.get(target, {}) if isinstance(fields, Mapping) else {}
    field = field if isinstance(field, Mapping) else {}
    field_type = str(field.get("type", "any"))
    if field_type == "array":
        return [coerce_parent_value(value, str(field.get("item_type", "any")))]
    return coerce_parent_value(value, field_type)


def _row_patch(
    operation: Mapping[str, Any], row: Any, bindings: Sequence[RowBinding]
) -> dict[str, Any] | None:
    patch: dict[str, Any] = {}
    for target, _, leaf in bindings:
        values = extract_parent_values(row, leaf)
        if len(values) != 1:
            return None
        patch[target] = _coerce_target(operation, target, values[0])
    return patch


def _aligned_parent_dimension(
    operation: Mapping[str, Any],
    bindings: Sequence[ParentBinding],
    parent_cache: ParentCache,
    candidate_limit: int,
) -> SearchDimension | None:
    if len(bindings) < 2:
        return None
    parent_ids = {str(parent.get("operation_id", "")) for _, parent in bindings}
    if len(parent_ids) != 1:
        return None
    cached = parent_cache.get(next(iter(parent_ids)))
    row_bindings = _row_bindings(bindings)
    if cached is None or not row_bindings:
        return None
    payload = _parent_payload(cached)
    if payload is None:
        return None
    rows = extract_parent_items(payload, row_bindings[0][1])
    patches = [
        patch
        for row in rows
        if (patch := _row_patch(operation, row, row_bindings)) is not None
    ]
    selected = _unique_values(patches)[:candidate_limit]
    if not selected:
        return None
    targets = tuple(dict.fromkeys(target for target, _, _ in row_bindings))
    return SearchDimension(
        "+".join(targets), "required_parent_row", tuple(selected), 1
    )


def _correlated_dimensions(
    operation: Mapping[str, Any],
    bindings_by_operation: Mapping[str, Sequence[ParentBinding]],
    parent_cache: ParentCache,
    candidate_limit: int,
) -> tuple[list[SearchDimension], set[str]]:
    dimensions = [
        dimension
        for bindings in bindings_by_operation.values()
        if (
            dimension := _aligned_parent_dimension(
                operation, bindings, parent_cache, candidate_limit
            )
        ) is not None
    ]
    handled = {name for dimension in dimensions for patch in dimension.patches for name in patch}
    return dimensions, handled


def resolve_parents(
    source: Mapping[str, Any],
    *,
    overrides: Mapping[str, Any],
    stable_client: Any,
    recording: RecordingSession,
    candidate_limit: int,
    operation_root: Path,
    anchor: date,
) -> tuple[
    dict[str, Sequence[Any]],
    dict[str, str],
    list[dict[str, Any]],
    list[SearchDimension],
]:
    operation = source["operation"]
    seed = _seed_inputs(operation, overrides)
    values_by_field: dict[str, Sequence[Any]] = {}
    failures: dict[str, str] = {}
    summaries: list[dict[str, Any]] = []
    parent_cache: ParentCache = {}
    bindings_by_operation: dict[str, list[ParentBinding]] = {}
    for parent in operation.get("required_parent", []):
        if not isinstance(parent, Mapping):
            continue
        target = _target_parent_field(parent, operation, seed)
        if target is None:
            failures[f"parent:{parent.get('operation_id', 'unknown')}"] = (
                "parent_target_input_unresolved"
            )
            continue
        if target in overrides and not _contains_placeholder(overrides[target]):
            continue
        parent_id = str(parent.get("operation_id", ""))
        bindings_by_operation.setdefault(parent_id, []).append((target, parent))
        values, summary = _fetch_parent_candidates(
            parent,
            target_source=source,
            stable_client=stable_client,
            recording=recording,
            candidate_limit=candidate_limit,
            operation_root=operation_root,
            anchor=anchor,
            parent_cache=parent_cache,
        )
        summaries.append(summary)
        if values:
            values_by_field[target] = values
        else:
            failures[target] = "parent_candidates_empty_or_unavailable"
    parent_dimensions, handled = _correlated_dimensions(
        operation, bindings_by_operation, parent_cache, candidate_limit
    )
    for name in handled:
        values_by_field.pop(name, None)
        failures.pop(name, None)
    return values_by_field, failures, summaries, parent_dimensions


__all__ = ["resolve_parents"]
