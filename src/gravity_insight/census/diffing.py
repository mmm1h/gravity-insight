from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from enum import Enum
from pathlib import Path
from typing import Any

from .io import read_json, write_json


def _route_key(item: dict[str, Any]) -> tuple[str, str]:
    return str(item.get("method", "UNKNOWN")), str(item.get("path", ""))


def _extract_method_changes(
    removed: set[tuple[str, str]], added: set[tuple[str, str]]
) -> list[dict[str, Any]]:
    method_changes: list[dict[str, Any]] = []
    for path in sorted({path for _, path in removed} & {path for _, path in added}):
        old_methods = sorted(method for method, item_path in removed if item_path == path)
        new_methods = sorted(method for method, item_path in added if item_path == path)
        if old_methods and new_methods:
            method_changes.append({"path": path, "old_methods": old_methods, "new_methods": new_methods})
            removed -= {(method, path) for method in old_methods}
            added -= {(method, path) for method in new_methods}
    return method_changes


def _path_change_candidates(
    removed: set[tuple[str, str]], added: set[tuple[str, str]]
) -> list[tuple[float, tuple[str, str], tuple[str, str]]]:
    candidates: list[tuple[float, tuple[str, str], tuple[str, str]]] = []
    for old_key in removed:
        for new_key in added:
            if old_key[0] != new_key[0]:
                continue
            old_leaf = old_key[1].rstrip("/").rsplit("/", 1)[-1]
            new_leaf = new_key[1].rstrip("/").rsplit("/", 1)[-1]
            if old_leaf != new_leaf:
                continue
            ratio = SequenceMatcher(None, old_key[1], new_key[1]).ratio()
            if ratio >= 0.72:
                candidates.append((ratio, old_key, new_key))
    return sorted(candidates, key=lambda item: (-item[0], item[1], item[2]))


def _extract_path_changes(
    removed: set[tuple[str, str]], added: set[tuple[str, str]]
) -> list[dict[str, Any]]:
    path_changes: list[dict[str, Any]] = []
    used_old: set[tuple[str, str]] = set()
    used_new: set[tuple[str, str]] = set()
    for ratio, old_key, new_key in _path_change_candidates(removed, added):
        if old_key in used_old or new_key in used_new:
            continue
        used_old.add(old_key)
        used_new.add(new_key)
        path_changes.append(
            {
                "method": old_key[0],
                "old_path": old_key[1],
                "new_path": new_key[1],
                "similarity": round(ratio, 4),
                "certainty": "heuristic",
            }
        )
    removed -= used_old
    added -= used_new
    return path_changes


def _route_rows(keys: set[tuple[str, str]]) -> list[dict[str, str]]:
    return [
        {"method": method, "path": path}
        for method, path in sorted(keys, key=lambda item: (item[1], item[0]))
    ]


def _withheld_diff(
    kind: str,
    *,
    old_bundle_id: Any,
    new_bundle_id: Any,
    old_complete: bool,
    new_complete: bool,
) -> dict[str, Any]:
    summary_keys = (
        ("added", "removed", "method_changed", "path_changed")
        if kind == "route_diff"
        else ("added_files", "removed_files", "changed_files")
    )
    result: dict[str, Any] = {
        "schema_version": 1,
        "kind": kind,
        "status": "incomplete",
        "drift_conclusion_available": False,
        "failure_class": "content_incomplete",
        "classification_reason": "both_diff_inputs_must_explicitly_prove_complete",
        "old_bundle_id": old_bundle_id,
        "new_bundle_id": new_bundle_id,
        "old_bundle_complete": old_complete,
        "new_bundle_complete": new_complete,
        "summary": {key: None for key in summary_keys},
        "next_action": (
            "Complete both static graphs before producing route, bundle, impact, "
            "or probe-plan drift conclusions."
        ),
    }
    if kind == "route_diff":
        result.update(
            {
                "added": [],
                "removed": [],
                "method_changes": [],
                "path_changes": [],
            }
        )
    else:
        result.update(
            {"added_files": [], "removed_files": [], "changed_files": []}
        )
    return result


def diff_routes(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    old_complete = old.get("source", {}).get("bundle_complete") is True
    new_complete = new.get("source", {}).get("bundle_complete") is True
    if not old_complete or not new_complete:
        return _withheld_diff(
            "route_diff",
            old_bundle_id=old.get("source", {}).get("bundle_id"),
            new_bundle_id=new.get("source", {}).get("bundle_id"),
            old_complete=old_complete,
            new_complete=new_complete,
        )
    old_map = {_route_key(item): item for item in old.get("routes", [])}
    new_map = {_route_key(item): item for item in new.get("routes", [])}
    removed = set(old_map) - set(new_map)
    added = set(new_map) - set(old_map)
    method_changes = _extract_method_changes(removed, added)
    path_changes = _extract_path_changes(removed, added)
    added_rows = _route_rows(added)
    removed_rows = _route_rows(removed)
    return {
        "schema_version": 1,
        "kind": "route_diff",
        "status": "complete",
        "drift_conclusion_available": True,
        "failure_class": None,
        "old_bundle_id": old.get("source", {}).get("bundle_id"),
        "new_bundle_id": new.get("source", {}).get("bundle_id"),
        "old_bundle_complete": bool(old.get("source", {}).get("bundle_complete", False)),
        "new_bundle_complete": bool(new.get("source", {}).get("bundle_complete", False)),
        "summary": {
            "added": len(added_rows),
            "removed": len(removed_rows),
            "method_changed": len(method_changes),
            "path_changed": len(path_changes),
        },
        "added": added_rows,
        "removed": removed_rows,
        "method_changes": method_changes,
        "path_changes": sorted(path_changes, key=lambda item: (item["old_path"], item["method"])),
    }


def diff_snapshots(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    old_complete = old.get("summary", {}).get("complete") is True
    new_complete = new.get("summary", {}).get("complete") is True
    if not old_complete or not new_complete:
        return _withheld_diff(
            "bundle_snapshot_diff",
            old_bundle_id=old.get("bundle_id"),
            new_bundle_id=new.get("bundle_id"),
            old_complete=old_complete,
            new_complete=new_complete,
        )
    old_files = {str(item.get("url")): item for item in old.get("files", [])}
    new_files = {str(item.get("url")): item for item in new.get("files", [])}
    common = set(old_files) & set(new_files)
    changed = [
        {
            "url": url,
            "old_sha256": old_files[url].get("sha256"),
            "new_sha256": new_files[url].get("sha256"),
        }
        for url in sorted(common)
        if old_files[url].get("sha256") != new_files[url].get("sha256")
    ]
    return {
        "schema_version": 1,
        "kind": "bundle_snapshot_diff",
        "status": "complete",
        "drift_conclusion_available": True,
        "failure_class": None,
        "old_bundle_id": old.get("bundle_id"),
        "new_bundle_id": new.get("bundle_id"),
        "old_bundle_complete": bool(old.get("summary", {}).get("complete", False)),
        "new_bundle_complete": bool(new.get("summary", {}).get("complete", False)),
        "summary": {
            "added_files": len(set(new_files) - set(old_files)),
            "removed_files": len(set(old_files) - set(new_files)),
            "changed_files": len(changed),
        },
        "added_files": sorted(set(new_files) - set(old_files)),
        "removed_files": sorted(set(old_files) - set(new_files)),
        "changed_files": changed,
        "note": "Route method/path changes require routes.json inputs; snapshots only contain static asset identities.",
    }


def diff_files(old_path: Path, new_path: Path) -> dict[str, Any]:
    old = read_json(old_path)
    new = read_json(new_path)
    if isinstance(old, dict) and isinstance(new, dict) and "routes" in old and "routes" in new:
        return diff_routes(old, new)
    if isinstance(old, dict) and isinstance(new, dict) and "files" in old and "files" in new:
        return diff_snapshots(old, new)
    raise ValueError("both inputs must be routes.json files or both must be bundle snapshots")


class CensusFailureClass(str, Enum):
    UPSTREAM_CAPACITY = "upstream_capacity"
    LOCAL_GOVERNOR_CAPACITY = "local_governor_capacity"
    REQUEST_BUDGET_EXHAUSTED = "request_budget_exhausted"
    TRANSPORT_FAILURE = "transport_failure"
    HTTP_CLIENT_ERROR = "http_client_error"
    HTTP_SERVER_ERROR = "http_server_error"
    CONTENT_INCOMPLETE = "content_incomplete"
    UNCLASSIFIED = "unclassified"


@dataclass(frozen=True)
class _FailurePolicy:
    code: str
    category: str
    retryable: bool
    next_action: str


_POLICIES = {
    CensusFailureClass.UPSTREAM_CAPACITY: _FailurePolicy("CENSUS_UPSTREAM_CAPACITY", "upstream", True, "Wait for the reported upstream cooldown, then retry within the bounded crawl-attempt limit."),
    CensusFailureClass.LOCAL_GOVERNOR_CAPACITY: _FailurePolicy("CENSUS_LOCAL_GOVERNOR_CAPACITY", "local", True, "Retry only within the configured process-local Governor-capacity limit."),
    CensusFailureClass.REQUEST_BUDGET_EXHAUSTED: _FailurePolicy("CENSUS_REQUEST_BUDGET_EXHAUSTED", "local", False, "Inspect graph size and the request budget; do not continue from the partial graph."),
    CensusFailureClass.TRANSPORT_FAILURE: _FailurePolicy("CENSUS_TRANSPORT_FAILURE", "upstream", True, "The bounded resource attempts are exhausted; inspect network reachability."),
    CensusFailureClass.HTTP_CLIENT_ERROR: _FailurePolicy("CENSUS_HTTP_CLIENT_ERROR", "upstream", False, "Inspect the discovered public resource; do not retry this as capacity."),
    CensusFailureClass.HTTP_SERVER_ERROR: _FailurePolicy("CENSUS_HTTP_SERVER_ERROR", "upstream", True, "The bounded resource attempts are exhausted; inspect upstream service health."),
    CensusFailureClass.CONTENT_INCOMPLETE: _FailurePolicy("CENSUS_CONTENT_INCOMPLETE", "upstream", False, "Withhold drift conclusions until a complete graph is proven."),
    CensusFailureClass.UNCLASSIFIED: _FailurePolicy("CENSUS_UNCLASSIFIED", "local", False, "Inspect classification diagnostics before deciding whether to retry."),
}
_STATUS_FAILURES = {
    "rate_limited": CensusFailureClass.UPSTREAM_CAPACITY,
    "local_governor_capacity": CensusFailureClass.LOCAL_GOVERNOR_CAPACITY,
    "request_budget_exhausted": CensusFailureClass.REQUEST_BUDGET_EXHAUSTED,
    "transport_error": CensusFailureClass.TRANSPORT_FAILURE,
    "client_error": CensusFailureClass.HTTP_CLIENT_ERROR,
    "server_error": CensusFailureClass.HTTP_SERVER_ERROR,
    "content_incomplete": CensusFailureClass.CONTENT_INCOMPLETE,
}


def _normalize_failure(value: object) -> CensusFailureClass | None:
    try:
        return CensusFailureClass(str(value))
    except ValueError:
        return None


def _aggregate_statuses(values: Any) -> tuple[CensusFailureClass, str]:
    source = [str(value) for value in values]
    if not source:
        return CensusFailureClass.CONTENT_INCOMPLETE, "crawl_incomplete_without_resource_failure"
    mapped = [_STATUS_FAILURES.get(value) for value in source]
    unknown = sorted({source[index] for index, item in enumerate(mapped) if item is None})
    if unknown:
        return CensusFailureClass.UNCLASSIFIED, "unmapped_status_classes:" + ",".join(unknown)
    selected = {item for item in mapped if item is not None}
    if CensusFailureClass.REQUEST_BUDGET_EXHAUSTED in selected:
        return CensusFailureClass.REQUEST_BUDGET_EXHAUSTED, "request_budget_is_terminal_for_this_crawl"
    if len(selected) == 1:
        return next(iter(selected)), "all_resource_failures_share_one_class"
    return CensusFailureClass.UNCLASSIFIED, "mixed_failure_classes:" + ",".join(sorted(item.value for item in selected))


def _safe_failures(result: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for failure in result.get("discovery", {}).get("failures", []):
        if not isinstance(failure, dict):
            continue
        status_class = str(failure.get("status_class", "unknown"))
        selected = _STATUS_FAILURES.get(status_class, CensusFailureClass.UNCLASSIFIED)
        status, exception = failure.get("status_code"), failure.get("exception_type")
        rows.append({"host": str(failure.get("host", "unknown")),
                     "status_class": status_class, "failure_class": selected.value,
                     "http_status": status if type(status) is int else None,
                     "exception_type": str(exception) if exception is not None else None})
    return rows


def _failure_payload(
    failure_class: CensusFailureClass, *, error: str, reason: str,
    source_code: str = "", source_status: str = "", exception_type: str = "",
    failures: list[dict[str, Any]] | None = None, cooldown_ms: int = 0,
    used: int = 0, limit: int = 0, local_retries: int = 0,
    summary: dict[str, Any] | None = None, lane: dict[str, Any] | None = None,
    next_action: str | None = None,
) -> dict[str, Any]:
    policy = _POLICIES[failure_class]
    return {"schema_version": "gravity-census.failure.v1", "status": "error",
            "complete": False, "drift_conclusion_available": False, "error": error,
            "code": policy.code, "category": policy.category,
            "retryable": policy.retryable, "failure_class": failure_class.value,
            "classification": {"reason": reason, "source_code": source_code or None,
                "source_status_class": source_status or None,
                "exception_type": exception_type or None},
            "failures": list(failures or []), "cooldown_remaining_ms": max(0, cooldown_ms),
            "request_budget": {"used": max(0, used), "limit": max(0, limit),
                "remaining": max(0, limit - used)},
            "local_capacity_retries_used": max(0, local_retries),
            "summary": dict(summary or {}), "lane": dict(lane or {}),
            "next_action": next_action or policy.next_action}


def incomplete_fetch_failure(result: dict[str, Any]) -> dict[str, Any]:
    failures = _safe_failures(result)
    selected, reason = _aggregate_statuses(item["status_class"] for item in failures)
    summary = result.get("summary", {})
    used, limit = int(summary.get("request_attempts", 0)), int(summary.get("request_limit", 0))
    return _failure_payload(
        selected, error="The public static graph could not be proven complete.",
        reason=reason, source_code="CENSUS_INCOMPLETE_GRAPH", failures=failures,
        cooldown_ms=30_000 if selected is CensusFailureClass.UPSTREAM_CAPACITY else 0,
        used=used, limit=limit,
        local_retries=int(summary.get("local_capacity_retries_used", 0)),
        summary={"complete": bool(summary.get("complete", False)),
                 "request_attempts": used, "request_limit": limit,
                 "pending_js": int(summary.get("pending_js", 0)),
                 "failed_js": int(summary.get("failed_js", 0))})


def _governor_failure(error: BaseException, code: str, diagnostics: dict[str, Any]) -> dict[str, Any]:
    selected = _normalize_failure(diagnostics.get("failure_class"))
    failures = [dict(item) for item in diagnostics.get("failures", []) if isinstance(item, dict)]
    reason = str(diagnostics.get("classification_reason", ""))
    if selected is None and failures:
        selected, reason = _aggregate_statuses(item.get("status_class", "unknown") for item in failures)
    selected = selected or CensusFailureClass.UNCLASSIFIED
    reason = reason or "governor_error_has_no_known_failure_class"
    lane = diagnostics.get("lane")
    return _failure_payload(
        selected, error="The Governor stopped Census HTTP before network execution.",
        reason=reason, source_code=code, exception_type=type(error).__name__,
        failures=failures, cooldown_ms=int(diagnostics.get("cooldown_remaining_ms", 0) or 0),
        used=int(getattr(error, "census_request_attempts", 0) or 0),
        limit=int(getattr(error, "census_request_limit", 0) or 0),
        local_retries=int(getattr(error, "census_local_capacity_retries_used", 0) or 0),
        lane=dict(lane) if isinstance(lane, dict) else {},
        next_action=str(getattr(error, "next_action", "") or "") or None)


def _status_failure(error: BaseException, code: str) -> dict[str, Any]:
    status_class = str(getattr(error, "status_class", "unknown"))
    selected = _STATUS_FAILURES.get(status_class, CensusFailureClass.UNCLASSIFIED)
    reason = ("status_class_has_closed_mapping" if status_class in _STATUS_FAILURES
              else "exception_has_no_known_status_class_mapping")
    status, source_exception = getattr(error, "status_code", None), getattr(error, "exception_type", None)
    failures = [] if not hasattr(error, "status_class") else [{
        "host": str(getattr(error, "host", "unknown")), "status_class": status_class,
        "failure_class": selected.value, "http_status": status if type(status) is int else None,
        "exception_type": str(source_exception) if source_exception is not None else None}]
    return _failure_payload(
        selected, error=str(error) if failures else "Census failed before producing a complete result.",
        reason=reason, source_code=code, source_status=status_class,
        exception_type=type(error).__name__, failures=failures,
        cooldown_ms=30_000 if selected is CensusFailureClass.UPSTREAM_CAPACITY else 0,
        used=int(getattr(error, "request_attempts", 0) or 0),
        limit=int(getattr(error, "request_limit", 0) or 0),
        local_retries=int(getattr(error, "local_capacity_retries_used", 0) or 0))


def exception_failure(error: BaseException) -> dict[str, Any]:
    code, diagnostics = str(getattr(error, "code", "")), getattr(error, "diagnostics", None)
    if code.startswith("GOVERNOR_") and isinstance(diagnostics, dict):
        return _governor_failure(error, code, diagnostics)
    return _status_failure(error, code)


def write_failure(args: Any, payload: dict[str, Any]) -> None:
    if target := getattr(args, "failure_output", None):
        write_json(target, payload)


def write_fetch_step(args: Any, snapshot: dict[str, Any] | None,
                     failure: dict[str, Any] | None) -> None:
    if not (target := getattr(args, "step_output", None)):
        return
    selected_snapshot = dict(snapshot or {})
    selected = dict(selected_snapshot.get("summary", {}))
    complete = selected.get("complete") is True and failure is None
    used, limit = int(selected.get("request_attempts", 0)), int(selected.get("request_limit", 0))
    budget = (dict(failure.get("request_budget", {})) if failure else
              {"used": used, "limit": limit, "remaining": max(0, limit - used)})
    write_json(target, {"schema_version": "gravity-census.step-output.v1",
        "operation": "fetch_public_static_graph", "status": "complete" if complete else "error",
        "complete": complete, "drift_conclusion_available": complete,
        "failure_class": None if failure is None else failure["failure_class"],
        "observed_at": selected_snapshot.get("fetched_at"),
        "bundle_id": selected_snapshot.get("bundle_id"),
        "request_budget": budget, "summary": selected, "failure": failure})
