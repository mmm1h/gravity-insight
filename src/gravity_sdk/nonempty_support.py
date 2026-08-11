"""Cache, evidence, and result-envelope helpers for non-empty discovery."""

from __future__ import annotations

import copy
import re
from datetime import date
from pathlib import Path
from typing import Any, Mapping, Sequence

from .nonempty_plan import SearchDimension, _plan_size
from .prober.core import REPO_ROOT, canonical_fingerprint, read_json
from .prober.draft_probe import _evidence_document, _observed_contract, _persist_observed
from .prober.privacy import response_schema_sketch
from .prober.probe_support import evidence_path, family_id
from .prober.transport import HttpObservation, RequestDiscipline


DEFAULT_EVIDENCE_ROOT = REPO_ROOT / "evidence" / "probe"
SCHEMA_VERSION = "gravity-insight.nonempty-discovery.v2"


def _apply_found_draft(
    source: Mapping[str, Any],
    observation: HttpObservation,
    *,
    parent_summary: Mapping[str, Any] | None,
    draft_root: Path,
) -> dict[str, Any]:
    payload = observation.payload if isinstance(observation.payload, Mapping) else {}
    updated, pagination, fields, sketch = _observed_contract(source, payload)
    references = source.get("draft", {}).get("probe_evidence", [])
    latest = references[-1] if isinstance(references, list) and references else {}
    pagination_verified = pagination.get("kind") == "none" or (
        isinstance(latest, Mapping) and latest.get("pagination_verified") is True
    )
    raw_fingerprint = canonical_fingerprint(sketch)
    projected_fingerprint = canonical_fingerprint(
        updated["operation"]["response_projection"]
    )
    evidence = _evidence_document(
        updated,
        [observation],
        selected_family=family_id(source),
        result="success",
        successful=True,
        raw_fingerprint=raw_fingerprint,
        projected_fingerprint=projected_fingerprint,
        pagination={"kind": pagination["kind"]},
        pagination_verified=pagination_verified,
        missing_parameter={"attempted": False, "shape_observed": False},
        parent_summary=parent_summary,
        fields=fields,
    )
    return _persist_observed(
        updated,
        evidence,
        evidence_path(str(source["operation"]["operation_id"]), DEFAULT_EVIDENCE_ROOT),
        fields,
        pagination_verified=pagination_verified,
        raw_fingerprint=raw_fingerprint,
        projected_fingerprint=projected_fingerprint,
        draft_root=draft_root,
    )


def _cache_path(
    operation_id: str,
    source: Mapping[str, Any],
    overrides: Mapping[str, Any],
    *,
    request_budget: int,
    candidate_limit: int,
    anchor: date,
    cache_root: Path,
) -> Path:
    identity = {
        "operation": source,
        "overrides": overrides,
        "request_budget": request_budget,
        "candidate_limit": candidate_limit,
        "search_day": anchor.isoformat(),
    }
    safe_id = re.sub(r"[^A-Za-z0-9_.-]", "_", operation_id)
    return cache_root / f"{safe_id}-{canonical_fingerprint(identity)[:16]}.json"


def _checked_cache_root(cache_root: Path) -> Path:
    resolved = cache_root.resolve()
    if not resolved.is_relative_to((REPO_ROOT / "tmp").resolve()):
        raise ValueError(
            "non-empty discovery cache must stay under the workspace state tmp directory"
        )
    return resolved


def _cached_result(path: Path) -> dict[str, Any] | None:
    cached = read_json(path)
    if not isinstance(cached, Mapping) or cached.get("schema_version") != SCHEMA_VERSION:
        return None
    result = copy.deepcopy(dict(cached))
    prior = int(result.get("request_stats", {}).get("total", 0))
    result["request_stats"] = {
        **dict(result.get("request_stats", {})),
        "total": 0,
        "reused_request_count": prior,
    }
    result["cache"] = {
        "hit": True,
        "path": path.relative_to(REPO_ROOT).as_posix(),
        "contains_business_values": False,
    }
    return result


def _resolution(state: Mapping[str, Any], total: int, unresolved: Sequence[Any]) -> str:
    if state.get("inputs") is not None:
        return "unblocked"
    attempted = int(state.get("attempted", 0))
    evaluated = int(state.get("evaluated", 0))
    only_empty = (
        attempted == evaluated == total
        and state.get("outcomes") == {"empty": attempted}
    )
    if attempted and only_empty and not unresolved:
        return "confirmed_empty"
    return "undetermined"


def _parent_evidence(
    summaries: Sequence[Mapping[str, Any]],
) -> Mapping[str, Any] | None:
    if len(summaries) == 1:
        return summaries[0]
    return {"status": "resolved", "bindings": list(summaries)} if summaries else None


def _draft_application(
    *,
    requested: bool,
    contract_state: str,
    source: Mapping[str, Any],
    state: Mapping[str, Any],
    parent_summary: Mapping[str, Any] | None,
    draft_root: Path,
) -> tuple[dict[str, Any], bool]:
    if not requested:
        return {"requested": False, "applied": False}, False
    if contract_state != "draft":
        return {
            "requested": True,
            "applied": False,
            "reason": "operation_is_already_stable",
        }, False
    observation = state.get("observation")
    if not isinstance(observation, HttpObservation):
        return {
            "requested": True,
            "applied": False,
            "reason": "nonempty_combination_not_found",
        }, False
    try:
        applied = _apply_found_draft(
            source,
            observation,
            parent_summary=parent_summary,
            draft_root=draft_root,
        )
        return {"requested": True, "applied": True, **applied}, False
    except (OSError, RuntimeError, ValueError, TypeError) as exc:
        return {
            "requested": True,
            "applied": False,
            "reason": f"apply_failed:{type(exc).__name__}",
        }, True


def _search_summary(
    dimensions: Sequence[SearchDimension],
    unresolved: Sequence[Mapping[str, str]],
    state: Mapping[str, Any],
    discipline: RequestDiscipline,
    total: int,
    request_budget: int,
    candidate_limit: int,
) -> dict[str, Any]:
    evaluated = int(state.get("evaluated", 0))
    return {
        "strategy": "weighted_best_first",
        "request_budget": request_budget,
        "candidate_limit_per_parent": candidate_limit,
        "planned_combinations": total,
        "attempted_combinations": state.get("attempted", 0),
        "evaluated_combinations": evaluated,
        "exhausted_planned_combinations": evaluated >= total,
        "budget_exhausted": discipline.total >= request_budget and evaluated < total,
        "dimensions": [
            {
                "field": item.label,
                "source": item.source,
                "candidate_count": len(item.patches),
                "priority_weight": item.weight,
            }
            for item in dimensions
        ],
        "unresolved_dimensions": list(unresolved),
        "outcomes": dict(state.get("outcomes", {})),
        "diagnostics": {
            "local_error_types": dict(state.get("local_error_types", {})),
            "semantic_parameter_hints": list(
                state.get("semantic_hints", {}).values()
            ),
        },
        "stopped_early_on_nonempty": state.get("inputs") is not None,
    }


def _result_document(
    *,
    operation_id: str,
    contract_state: str,
    dimensions: Sequence[SearchDimension],
    unresolved: Sequence[Mapping[str, str]],
    summaries: Sequence[Mapping[str, Any]],
    state: Mapping[str, Any],
    discipline: RequestDiscipline,
    request_budget: int,
    candidate_limit: int,
    application: Mapping[str, Any],
    apply_failed: bool,
    auth: Mapping[str, Any],
    cache_path: Path,
) -> dict[str, Any]:
    total = _plan_size(dimensions)
    found = state.get("inputs") is not None
    resolution = "undetermined" if apply_failed else _resolution(state, total, unresolved)
    observation = state.get("observation")
    nonempty = None
    if found:
        nonempty = {
            "item_count": state.get("count", 0),
            "count_semantics": state.get("count_semantics", "unavailable"),
            "raw_schema_fingerprint": canonical_fingerprint(
                response_schema_sketch(observation.payload if observation else {})
            ),
        }
    return {
        "schema_version": SCHEMA_VERSION,
        "ok": True,
        "operation_id": operation_id,
        "contract_state": contract_state,
        "resolution": resolution,
        "found": found,
        "successful_input": (
            {
                "field_names": sorted(str(name) for name in state["inputs"]),
                "values_redacted": True,
            }
            if isinstance(state.get("inputs"), Mapping)
            else None
        ),
        "nonempty": nonempty,
        "search": _search_summary(
            dimensions,
            unresolved,
            state,
            discipline,
            total,
            request_budget,
            candidate_limit,
        ),
        "parents": list(summaries),
        "request_stats": {
            "total": discipline.total,
            "target": state.get("target_requests", 0),
            "parent": discipline.total - int(state.get("target_requests", 0)),
            "failed": discipline.failed,
            "backoff_terminations": discipline.backoff_terminations,
            "request_limit": discipline.request_limit,
            "minimum_interval_ms": int(discipline.interval_seconds * 1000),
        },
        "draft_application": dict(application),
        "auth": {
            "auth_state": auth.get("auth_state"),
            "can_exchange_credentials": bool(auth.get("can_exchange_credentials")),
        },
        "cache": {
            "hit": False,
            "path": cache_path.relative_to(REPO_ROOT).as_posix(),
            "contains_business_values": False,
        },
    }


__all__ = [
    "DEFAULT_EVIDENCE_ROOT",
    "SCHEMA_VERSION",
    "_apply_found_draft",
    "_cache_path",
    "_cached_result",
    "_checked_cache_root",
    "_draft_application",
    "_parent_evidence",
    "_result_document",
]
