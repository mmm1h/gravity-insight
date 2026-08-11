"""Bounded HTTP execution and caching for non-empty discovery."""

from __future__ import annotations

import copy
from datetime import date
from pathlib import Path
from typing import Any, Mapping, Sequence

from gravity_sdk import runtime as tool_runtime

from .parent_resolution import extract_parent_values
from .nonempty_plan import (
    DEFAULT_CACHE_ROOT,
    DEFAULT_CANDIDATE_LIMIT,
    DEFAULT_INTERVAL_SECONDS,
    DEFAULT_REQUEST_BUDGET,
    SearchDimension,
    _build_plan,
    _contains_placeholder,
    _dynamic_tokens,
    _iter_combinations,
    _resolve_dates,
    _seed_inputs,
)
from .prober.core import (
    DRAFT_ROOT,
    OPERATION_ROOT,
    canonical_fingerprint,
    read_json,
    write_json,
)
from .prober.parameters import parameter_hints_from_error
from .prober.probe_support import (
    data_nonempty,
    family_id,
    last_primary,
    semantic_success,
)
from .prober.transport import (
    HttpObservation,
    RecordingSession,
    RequestDiscipline,
    build_draft_client,
    build_runtime,
    sdk_parts,
)
from .nonempty_support import (
    _cache_path,
    _cached_result,
    _checked_cache_root,
    _draft_application,
    _parent_evidence,
    _result_document,
)


def _session_or_default(session: Any | None) -> Any:
    if session is not None:
        return session
    try:
        import requests
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("requests is required for non-empty discovery") from exc
    return requests.Session()


def _ensure_auth() -> Mapping[str, Any]:
    status = tool_runtime.credential_status()
    if status.get("auth_state") == "valid_token":
        return status
    if status.get("can_exchange_credentials"):
        tool_runtime.refresh_credentials()
        status = tool_runtime.credential_status()
    if status.get("auth_state") != "valid_token":
        raise RuntimeError("Gravity credentials are unavailable for non-empty discovery")
    return status


def _operation_source(
    operation_id: str, *, draft_root: Path, operation_root: Path
) -> tuple[dict[str, Any], str]:
    choices = (
        (draft_root / f"{operation_id}.json", "draft"),
        (operation_root / f"{operation_id}.json", "stable"),
    )
    selected = next(((path, state) for path, state in choices if path.is_file()), None)
    if selected is None:
        raise ValueError(f"unknown Gravity Insight operation: {operation_id}")
    source = read_json(selected[0])
    operation = source.get("operation") if isinstance(source, Mapping) else None
    if not isinstance(operation, Mapping) or operation.get("effect") != "read":
        raise ValueError("non-empty discovery only accepts read operations")
    return copy.deepcopy(dict(source)), selected[1]


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


def _simple_parent_inputs(source: Mapping[str, Any], anchor: date) -> dict[str, Any] | None:
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
    if inputs is not None:
        pagination = source["operation"].get("pagination", {})
        selected = dict(inputs)
        if isinstance(pagination, Mapping) and pagination.get("page_size_field"):
            size_field = str(pagination["page_size_field"])
            selected[size_field] = min(
                candidate_limit, int(pagination.get("max_page_size") or candidate_limit)
            )
    else:
        selected = None
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


def _fetch_parent_candidates(
    parent: Mapping[str, Any],
    *,
    target_source: Mapping[str, Any],
    stable_client: Any,
    recording: RecordingSession,
    candidate_limit: int,
    operation_root: Path,
    anchor: date,
) -> tuple[list[Any], dict[str, Any]]:
    operation_id = str(parent.get("operation_id", ""))
    output_path = str(parent.get("output_path", ""))
    path = operation_root / f"{operation_id}.json"
    if not operation_id or not output_path or not path.is_file():
        return [], _parent_summary(operation_id, output_path, "metadata_unavailable")
    source = read_json(path)
    envelope, primary, local_error_type = _call_parent(
        operation_id,
        source,
        _simple_parent_inputs(source, anchor),
        stable_client=stable_client,
        recording=recording,
        target_source=target_source,
        candidate_limit=candidate_limit,
    )
    if local_error_type is not None:
        return [], _parent_summary(
            operation_id,
            output_path,
            "local_error",
            primary=primary,
            local_error_type=local_error_type,
        )
    values = (
        extract_parent_values(envelope, output_path)
        if isinstance(envelope, Mapping)
        else []
    )
    if not values and primary is not None and isinstance(primary.payload, Mapping):
        values = extract_parent_values(primary.payload, output_path)
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


def _resolve_parents(
    source: Mapping[str, Any],
    *,
    overrides: Mapping[str, Any],
    stable_client: Any,
    recording: RecordingSession,
    candidate_limit: int,
    operation_root: Path,
    anchor: date,
) -> tuple[dict[str, Sequence[Any]], dict[str, str], list[dict[str, Any]]]:
    operation = source["operation"]
    seed = _seed_inputs(operation, overrides)
    values_by_field: dict[str, Sequence[Any]] = {}
    failures: dict[str, str] = {}
    summaries: list[dict[str, Any]] = []
    for parent in operation.get("required_parent", []):
        if not isinstance(parent, Mapping):
            continue
        target = _target_parent_field(parent, operation, seed)
        if target is None:
            failures[f"parent:{parent.get('operation_id', 'unknown')}"] = "parent_target_input_unresolved"
            continue
        if target in overrides and not _contains_placeholder(overrides[target]):
            continue
        values, summary = _fetch_parent_candidates(
            parent,
            target_source=source,
            stable_client=stable_client,
            recording=recording,
            candidate_limit=candidate_limit,
            operation_root=operation_root,
            anchor=anchor,
        )
        summaries.append(summary)
        if values:
            values_by_field[target] = values
        else:
            failures[target] = "parent_candidates_empty_or_unavailable"
    return values_by_field, failures, summaries


def _response_count(payload: Any) -> tuple[int, str]:
    if not isinstance(payload, Mapping):
        return 0, "unavailable"
    data = payload.get("data")
    if isinstance(data, list):
        return len(data), "data_list"
    if isinstance(data, Mapping):
        for key in ("list", "items", "rows"):
            if isinstance(data.get(key), list):
                return len(data[key]), f"data.{key}"
        return (1, "data_object") if data else (0, "data_object")
    return (1, "data_scalar") if data not in (None, "", False) else (0, "data_scalar")


def _trial_outcome(observation: HttpObservation | None) -> tuple[str, int, str]:
    if observation is None:
        return "local_error", 0, "unavailable"
    if not 200 <= observation.status_code < 300:
        status = "rate_limited" if observation.status_code == 429 else "upstream_error"
        return (status if observation.status_code >= 500 or status == "rate_limited" else "http_error"), 0, "unavailable"
    if not semantic_success(observation.payload):
        return "semantic_error", 0, "unavailable"
    count, semantics = _response_count(observation.payload)
    return ("nonempty" if data_nonempty(observation.payload) else "empty"), count, semantics


def _safe_semantic_code(payload: Any) -> str:
    """Classify an upstream semantic error without retaining response text."""

    if not isinstance(payload, Mapping):
        return "unknown"
    code = payload.get("code")
    if isinstance(code, int) and not isinstance(code, bool) and abs(code) <= 999_999_999:
        return str(code)
    if isinstance(code, str):
        normalized = code.strip()
        if normalized.lstrip("-").isdigit() and 1 <= len(normalized.lstrip("-")) <= 9:
            return str(int(normalized))
    extra = payload.get("extra")
    if code in (None, 0, 200, "0", "200") and isinstance(extra, Mapping) and extra.get("error"):
        return "extra_error"
    return "other"


def _required_unresolved(
    operation: Mapping[str, Any], unresolved: Sequence[Mapping[str, str]]
) -> bool:
    fields = operation.get("input_fields", {})
    parents = operation.get("required_parent", [])
    parent_fields = {
        str(item.get("input_field"))
        for item in parents
        if isinstance(item, Mapping) and item.get("input_field")
    }
    return any(
        (
            str(item.get("field")) in parent_fields
            and str(item.get("reason", "")).startswith("parent_")
        )
        or (
            isinstance(fields, Mapping)
            and isinstance(fields.get(str(item.get("field"))), Mapping)
            and fields[str(item.get("field"))].get("required") is True
        )
        for item in unresolved
    )


def _search_candidates(
    source: Mapping[str, Any],
    *,
    base: Mapping[str, Any],
    dimensions: Sequence[SearchDimension],
    unresolved: Sequence[Mapping[str, str]],
    client: Any,
    recording: RecordingSession,
    discipline: RequestDiscipline,
) -> dict[str, Any]:
    operation = source["operation"]
    operation_id = str(operation["operation_id"])
    input_fields = operation.get("input_fields", {})
    state: dict[str, Any] = {
        "evaluated": 0, "attempted": 0, "target_requests": 0, "outcomes": {},
        "inputs": None, "observation": None, "count": 0, "count_semantics": "unavailable",
        "local_error_types": {}, "semantic_hints": {}, "semantic_error_codes": {},
    }
    candidates = () if _required_unresolved(operation, unresolved) else _iter_combinations(base, dimensions)
    for candidate in candidates:
        if discipline.total >= discipline.request_limit:
            break
        state["evaluated"] += 1
        before = discipline.total
        start = len(recording.observations)
        error_type = None
        try:
            with recording.observing(operation_id, family_id(source), "nonempty_search"):
                client.read(operation_id, candidate)
        except Exception as exc:
            error_type = type(exc).__name__
        delta = discipline.total - before
        state["attempted"] += delta
        state["target_requests"] += delta
        observation = last_primary(recording.observations[start:], operation_id)
        outcome, count, semantics = _trial_outcome(observation)
        state["outcomes"][outcome] = state["outcomes"].get(outcome, 0) + 1
        _record_diagnostic(state, outcome, error_type, observation, input_fields)
        if outcome == "nonempty":
            state.update(inputs=candidate, observation=observation, count=count, count_semantics=semantics)
            break
        if discipline.domain_stopped:
            break
    return state


def _record_diagnostic(
    state: dict[str, Any],
    outcome: str,
    error_type: str | None,
    observation: HttpObservation | None,
    input_fields: Any,
) -> None:
    if outcome == "local_error" and error_type:
        values = state["local_error_types"]
        values[error_type] = values.get(error_type, 0) + 1
    if outcome != "semantic_error" or observation is None:
        return
    semantic_codes = state["semantic_error_codes"]
    code = _safe_semantic_code(observation.payload)
    semantic_codes[code] = semantic_codes.get(code, 0) + 1
    names = tuple(str(name) for name in input_fields) if isinstance(input_fields, Mapping) else ()
    for hint in parameter_hints_from_error(observation.payload, known_parameters=names):
        key = (str(hint["field"]), str(hint["basis"]))
        state["semantic_hints"][key] = {"field": key[0], "basis": key[1]}


def discover_nonempty(
    operation_id: str,
    *,
    input_overrides: Mapping[str, Any] | None = None,
    request_budget: int = DEFAULT_REQUEST_BUDGET,
    candidate_limit: int = DEFAULT_CANDIDATE_LIMIT,
    interval_seconds: float = DEFAULT_INTERVAL_SECONDS,
    refresh_cache: bool = False,
    apply_draft: bool = False,
    cache_root: Path = DEFAULT_CACHE_ROOT,
    draft_root: Path = DRAFT_ROOT,
    operation_root: Path = OPERATION_ROOT,
    session: Any | None = None,
    anchor: date | None = None,
) -> dict[str, Any]:
    _validate_limits(request_budget, candidate_limit, interval_seconds)
    overrides = dict(input_overrides or {})
    source, contract_state = _operation_source(
        operation_id, draft_root=draft_root, operation_root=operation_root
    )
    _validate_overrides(source, overrides)
    selected_anchor = anchor or date.today()
    cache_path = _cache_path(
        operation_id, source, overrides, request_budget=request_budget,
        candidate_limit=candidate_limit, anchor=selected_anchor,
        cache_root=_checked_cache_root(cache_root),
    )
    if cache_path.is_file() and not refresh_cache and not apply_draft:
        cached = _cached_result(cache_path)
        if cached is not None:
            return cached
    auth = _ensure_auth()
    discipline, recording, runtime, stable_client = _runtime_components(
        request_budget, interval_seconds, session
    )
    parent_values, parent_failures, summaries = _resolve_parents(
        source, overrides=overrides, stable_client=stable_client, recording=recording,
        candidate_limit=candidate_limit, operation_root=operation_root, anchor=selected_anchor,
    )
    base, dimensions, unresolved = _build_plan(
        source, overrides=overrides, parent_values=parent_values,
        parent_failures=parent_failures, anchor=selected_anchor,
    )
    runtime_source = copy.deepcopy(source)
    runtime_source["operation"]["required_parent"] = []
    state = _search_candidates(
        source, base=base, dimensions=dimensions, unresolved=unresolved,
        client=build_draft_client(runtime_source, runtime),
        recording=recording, discipline=discipline,
    )
    parent_summary = _parent_evidence(summaries)
    application, apply_failed = _draft_application(
        requested=apply_draft, contract_state=contract_state, source=source,
        state=state, parent_summary=parent_summary, draft_root=draft_root,
    )
    result = _result_document(
        operation_id=operation_id, contract_state=contract_state,
        dimensions=dimensions, unresolved=unresolved, summaries=summaries,
        state=state, discipline=discipline, request_budget=request_budget,
        candidate_limit=candidate_limit, application=application,
        apply_failed=apply_failed, auth=auth, cache_path=cache_path,
    )
    write_json(cache_path, result)
    return result


def _runtime_components(
    request_budget: int, interval_seconds: float, session: Any | None
) -> tuple[RequestDiscipline, RecordingSession, Any, Any]:
    discipline = RequestDiscipline(
        interval_seconds=interval_seconds, request_limit=request_budget, hard_limit=200
    )
    recording = RecordingSession(_session_or_default(session), discipline)
    runtime = build_runtime(recording)
    client_class = sdk_parts()["GravityInsightClient"]
    stable_client = client_class.from_env(runtime=runtime, timeout=120.0, attempts=1)
    return discipline, recording, runtime, stable_client


def _validate_limits(request_budget: int, candidate_limit: int, interval_seconds: float) -> None:
    if not 1 <= request_budget <= 200:
        raise ValueError("non-empty request budget must be between 1 and 200")
    if not 1 <= candidate_limit <= 20:
        raise ValueError("candidate limit must be between 1 and 20")
    if interval_seconds < 0.3:
        raise ValueError("non-empty request interval must be at least 300ms")


def _validate_overrides(source: Mapping[str, Any], overrides: Mapping[str, Any]) -> None:
    fields = source["operation"].get("input_fields", {})
    unknown = sorted(set(overrides) - set(fields)) if isinstance(fields, Mapping) else []
    if unknown:
        raise ValueError("input overrides contain undeclared fields: " + ", ".join(unknown))


__all__ = ["discover_nonempty"]
