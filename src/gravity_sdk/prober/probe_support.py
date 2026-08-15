"""Shared parent, pagination, and evidence helpers for online probes."""

from __future__ import annotations

import copy
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..parent_resolution import coerce_parent_value, extract_parent_values
from ..semantic_status import (
    SEMANTIC_EXPLICIT_EMPTY,
    SEMANTIC_SUCCESS,
    classify_semantic_status,
    protocol_status_evidence,
    response_data_nonempty,
)
from .core import REPO_ROOT, canonical_fingerprint
from .privacy import response_schema_sketch
from .transport import HttpObservation, RecordingSession


def assert_read_only_source(source: Mapping[str, Any]) -> None:
    operation = source.get("operation")
    if not isinstance(operation, Mapping) or operation.get("effect") != "read":
        raise ValueError("online probe only accepts operations declared as read")
    method = str(operation.get("upstream_method", "")).upper()
    if method not in {"GET", "POST"}:
        raise ValueError("online probe only accepts GET or read-only POST")
    path_segments = {
        segment.casefold()
        for segment in str(operation.get("path_template", "")).split("/")
        if segment
    }
    forbidden = {
        "create", "update", "delete", "export", "upload", "remove", "write",
        "set", "verify_code", "submit_task",
    }
    if path_segments & forbidden:
        raise ValueError("online probe refused a mutation, export, or upload route")
    operation_id = str(operation.get("operation_id", "")).casefold()
    if "adcreate" in operation_id or "verify_code" in operation_id:
        raise ValueError("online probe refused a route with ambiguous write semantics")


def family_id(source: Mapping[str, Any]) -> str:
    provenance = source.get("operation", {}).get("provenance", {})
    family = provenance.get("family") if isinstance(provenance, Mapping) else None
    return str(family or source.get("operation", {}).get("operation_id", "unassigned"))


def _parent_target_type(
    source: Mapping[str, Any], parent: Mapping[str, Any], input_field: str | None
) -> str:
    target_field = str(input_field or parent.get("input_field") or "")
    fields = source.get("operation", {}).get("input_fields", {})
    if not isinstance(fields, Mapping):
        return "any"
    field = fields.get(target_field, {})
    if not isinstance(field, Mapping):
        return "any"
    return str(
        field.get("item_type", "any")
        if field.get("type") == "array"
        else field.get("type", "any")
    )


def resolve_parent(
    source: Mapping[str, Any], stable_client: Any, recording: RecordingSession,
    input_field: str | None = None,
) -> tuple[Any, dict[str, Any]]:
    parents = source.get("operation", {}).get("required_parent", [])
    if not parents:
        raise ValueError("draft contains $parent without required_parent provenance")
    parent = next(
        (
            item for item in parents
            if input_field and item.get("input_field") == input_field
        ),
        parents[0],
    )
    operation_id = str(parent["operation_id"])
    output_path = str(parent["output_path"])
    with recording.observing(operation_id, family_id(source), "parent"):
        envelope = stable_client.probe(operation_id)
    status = str(envelope.get("status", "error")) if isinstance(envelope, Mapping) else "error"
    values = (
        extract_parent_values(envelope, output_path)
        if isinstance(envelope, Mapping)
        else []
    )
    field_type = _parent_target_type(source, parent, input_field)
    values = [coerce_parent_value(value, field_type) for value in values]
    if status not in {"success", "empty"} or not values:
        raise ValueError(f"required parent did not yield a selectable value: {operation_id}")
    selection = str(parent.get("selection") or "first")
    selected: Any = values if selection == "all" else values[0]
    return selected, {
        "operation_id": operation_id, "output_path": output_path,
        "selection": selection,
        "probe_selection": "all" if selection == "all" else "first",
        "candidate_count": len(values), "status": "resolved",
    }


def resolve_inputs(
    value: Any, *, source: Mapping[str, Any], stable_client: Any,
    recording: RecordingSession,
    parent_cache: dict[str, tuple[Any, dict[str, Any]]],
    input_field: str | None = None,
) -> Any:
    if value == "$today":
        return date.today().isoformat()
    if value == "$yesterday":
        return (date.today() - timedelta(days=1)).isoformat()
    parent_placeholders = {
        "$parent", "$first_bytedance_advertiser_id",
        "$first_tencent_advertiser_id", "$first_kuaishou_advertiser_id",
    }
    named_parent = (
        value.split(":", 1)[1]
        if isinstance(value, str) and value.startswith("$parent:")
        else None
    )
    if isinstance(value, str) and (value in parent_placeholders or named_parent):
        selected_field = named_parent or input_field
        cache_key = f"{source['operation']['operation_id']}:{selected_field or ''}"
        if cache_key not in parent_cache:
            parent_cache[cache_key] = resolve_parent(
                source, stable_client, recording, selected_field
            )
        return parent_cache[cache_key][0]
    if isinstance(value, Mapping):
        return {
            str(key): resolve_inputs(
                item, source=source, stable_client=stable_client,
                recording=recording, parent_cache=parent_cache,
                input_field=str(key),
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [
            resolve_inputs(
                item, source=source, stable_client=stable_client,
                recording=recording, parent_cache=parent_cache,
                input_field=input_field,
            )
            for item in value
        ]
    return value


def semantic_success(payload: Any) -> bool:
    return classify_semantic_status(payload) in {
        SEMANTIC_SUCCESS, SEMANTIC_EXPLICIT_EMPTY,
    }


def data_nonempty(payload: Any) -> bool:
    return response_data_nonempty(payload)


def last_primary(
    observations: Sequence[HttpObservation], operation_id: str
) -> HttpObservation | None:
    for item in reversed(observations):
        if item.operation_id == operation_id:
            return item
    return None


def pagination_from_payload(
    payload: Mapping[str, Any], operation: Mapping[str, Any]
) -> dict[str, Any]:
    data = payload.get("data")
    inputs = operation.get("input_fields", {})
    is_paginated = (
        isinstance(data, Mapping) and isinstance(data.get("list"), list)
        and isinstance(data.get("page_info"), Mapping) and isinstance(inputs, Mapping)
        and "page" in inputs and "page_size" in inputs
    )
    if not is_paginated:
        return {
            "kind": "none", "page_field": "", "page_size_field": "",
            "list_path": "", "page_info_path": "", "total_page_field": "",
        }
    page_info = data["page_info"]
    total_field = next(
        (name for name in ("total_page", "total_pages", "page_count") if name in page_info),
        "total_page",
    )
    observed_default_size = operation.get("request", {}).get("defaults", {}).get(
        "page_size", 20
    )
    default_size = min(int(observed_default_size), 100)
    return {
        "kind": "page_info", "page_field": "page", "page_size_field": "page_size",
        "list_path": "data.list", "page_info_path": "data.page_info",
        "total_page_field": total_field, "default_page_size": int(default_size),
        "max_page_size": 100,
    }


def _page_observation(payload: Any) -> tuple[Any, Any, int | None]:
    if not isinstance(payload, Mapping) or not isinstance(payload.get("data"), Mapping):
        return None, None, None
    data = payload["data"]
    page_info, rows = data.get("page_info"), data.get("list")
    page = page_info.get("page") if isinstance(page_info, Mapping) else None
    size = page_info.get("page_size") if isinstance(page_info, Mapping) else None
    return page, size, len(rows) if isinstance(rows, list) else None


def probe_pagination(
    source: Mapping[str, Any], inputs: Mapping[str, Any], client: Any,
    recording: RecordingSession, selected_family: str,
) -> tuple[bool, dict[str, Any]]:
    operation_id = str(source["operation"]["operation_id"])
    page_two_inputs = {**inputs, "page": 2, "page_size": 2}
    with recording.observing(operation_id, selected_family, "pagination_page_2"):
        client.read(operation_id, page_two_inputs)
    page_two = last_primary(recording.observations, operation_id)
    cap_inputs = {**inputs, "page": 1, "page_size": 100}
    with recording.observing(operation_id, selected_family, "pagination_safe_max"):
        client.read(operation_id, cap_inputs)
    cap = last_primary(recording.observations, operation_id)
    page_value, _, page_rows = _page_observation(page_two.payload if page_two else None)
    _, cap_value, cap_rows = _page_observation(cap.payload if cap else None)
    page_effective = bool(page_two and page_two.status_code < 400 and page_value in (2, "2"))
    cap_accepted = bool(cap and cap.status_code < 400 and cap_value in (100, "100"))
    return page_effective and cap_accepted, {
        "page_parameter_observed": page_effective, "page_2_row_count": page_rows,
        "verified_safe_max_page_size": 100 if cap_accepted else None,
        "safe_max_row_count": cap_rows, "upstream_hard_max": None,
    }


def contract_with_optional_required(
    source: Mapping[str, Any], field_name: str
) -> dict[str, Any]:
    updated = copy.deepcopy(dict(source))
    field = updated["operation"]["input_fields"].get(field_name)
    if isinstance(field, Mapping):
        field = dict(field)
        field.pop("required", None)
        field.pop("default", None)
        updated["operation"]["input_fields"][field_name] = field
    return updated


def observation_summary(item: HttpObservation) -> dict[str, Any]:
    sketch = response_schema_sketch(item.payload)
    return {
        "operation_id": item.operation_id, "purpose": item.purpose,
        "method": item.method, "path": item.path, "http_status": item.status_code,
        "request_fingerprint": canonical_fingerprint(item.request_shape),
        "request_shape": item.request_shape, "response_schema_sketch": sketch,
        "raw_schema_fingerprint": canonical_fingerprint(sketch),
        "protocol_status": protocol_status_evidence(
            item.payload, http_status=item.status_code
        ),
    }


def evidence_path(operation_id: str, evidence_root: Path) -> Path:
    timestamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    base = evidence_root / f"{timestamp}_{operation_id}.yaml"
    if not base.exists():
        return base
    for suffix in range(1, 1000):
        candidate = evidence_root / f"{timestamp}_{operation_id}_{suffix}.yaml"
        if not candidate.exists():
            return candidate
    raise RuntimeError("could not allocate an immutable probe evidence path")


def relative(path: Path) -> str:
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def conclusion(status_code: int | None, payload: Any, confirmed_status: str | None) -> str:
    if status_code == 404:
        return "upstream_removed"
    if status_code in {401, 403}:
        return "permission_or_auth_unavailable"
    if status_code == 429:
        return "rate_limited"
    if status_code is not None and status_code >= 500:
        return "upstream_server_error"
    if status_code is None:
        return "local_or_parent_inconclusive"
    if not 200 <= status_code < 300:
        return "http_error"
    if status_code == 204:
        return "available_empty"
    semantic_status = classify_semantic_status(payload)
    if semantic_status == SEMANTIC_EXPLICIT_EMPTY:
        return "available_empty"
    if semantic_status != SEMANTIC_SUCCESS:
        return "semantic_error"
    if not data_nonempty(payload):
        return "inconclusive_empty"
    if confirmed_status in {"success", "contract_changed_additive"}:
        return "success"
    if confirmed_status == "contract_changed":
        return "contract_mismatch"
    return "inconclusive"


def privacy_summary(fields: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "candidate_fields": list(fields),
        "classified_non_sensitive": sum(
            1 for item in fields if item["privacy_classification"] == "non_sensitive"
        ),
        "classified_sensitive": sum(
            1 for item in fields if item["privacy_classification"] == "sensitive"
        ),
        "manual_review": sum(
            1 for item in fields if item["privacy_classification"] == "manual_review"
        ),
        "values_persisted": False,
    }


def request_stats(observations: Sequence[HttpObservation]) -> dict[str, int]:
    return {
        "total": len(observations),
        "failed": sum(1 for item in observations if item.status_code >= 400),
        "backoff_terminations": sum(
            1 for item in observations if item.status_code == 429 or item.status_code >= 500
        ),
    }
