"""Current offline Census evidence without making an upstream request."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from gravity_insight.evidence_common import (
    context_bound_measurement,
    load_object,
    relative,
    resolve_context_bound_measurement,
)
from gravity_insight.paths import PROJECT_ROOT

from .diffing import CensusFailureClass


CURRENT_EVIDENCE_DIRECTORY = Path("tmp/census-current")
CURRENT_MAX_AGE = timedelta(hours=26)
CURRENT_FUTURE_SKEW = timedelta(minutes=5)
_HEX = frozenset("0123456789abcdef")


def _documents(
    paths: Iterable[Path],
) -> tuple[list[tuple[Path, dict[str, Any]]], list[Path]]:
    result: list[tuple[Path, dict[str, Any]]] = []
    invalid = []
    for path in paths:
        if path.is_file():
            try:
                result.append((path, load_object(path)))
            except (OSError, UnicodeError, ValueError):
                invalid.append(path)
    return result, invalid


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _valid_bundle_id(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in _HEX for character in value)
    )


def _fetch_steps(
    documents: list[tuple[Path, dict[str, Any]]],
) -> list[tuple[Path, dict[str, Any]]]:
    return [
        item
        for item in documents
        if item[1].get("schema_version") == "gravity-census.step-output.v1"
        and item[1].get("operation") == "fetch_public_static_graph"
    ]


def _step_identity(
    step_path: Path,
    step: Mapping[str, Any],
    documents: list[tuple[Path, dict[str, Any]]],
) -> tuple[str, datetime, Path] | None:
    for path, snapshot in documents:
        if path.parent != step_path.parent or snapshot.get("schema_version") != 1:
            continue
        summary = snapshot.get("summary")
        observed_at = _parse_time(snapshot.get("fetched_at"))
        bundle_id = snapshot.get("bundle_id")
        if (
            observed_at is not None
            and _valid_bundle_id(bundle_id)
            and isinstance(summary, Mapping)
            and summary.get("complete") is True
            and summary == step.get("summary")
        ):
            receipt_bundle_id = step.get("bundle_id")
            receipt_observed_at = _parse_time(step.get("observed_at"))
            legacy = receipt_bundle_id is None and step.get("observed_at") is None
            if not legacy and (
                receipt_bundle_id != bundle_id or receipt_observed_at != observed_at
            ):
                continue
            return str(bundle_id), observed_at, path
    return None


def _complete_step(step: Mapping[str, Any]) -> bool:
    summary = step.get("summary")
    return bool(
        step.get("status") == "complete"
        and step.get("complete") is True
        and step.get("failure_class") is None
        and isinstance(summary, Mapping)
        and summary.get("complete") is True
    )


def _matching_diffs(
    step_path: Path,
    bundle_id: str,
    documents: list[tuple[Path, dict[str, Any]]],
) -> list[tuple[Path, dict[str, Any]]]:
    result = []
    for path, diff in documents:
        if path.parent != step_path.parent:
            continue
        if (
            diff.get("schema_version") == 1
            and diff.get("kind") in {"route_diff", "bundle_snapshot_diff"}
            and diff.get("status") == "complete"
            and diff.get("drift_conclusion_available") is True
            and diff.get("failure_class") is None
            and diff.get("old_bundle_complete") is True
            and diff.get("new_bundle_complete") is True
            and _valid_bundle_id(diff.get("old_bundle_id"))
            and diff.get("new_bundle_id") == bundle_id
        ):
            result.append((path, diff))
    return result


def _observation_candidates(
    root: Path, documents: list[tuple[Path, dict[str, Any]]]
) -> list[dict[str, Any]]:
    candidates = []
    for step_path, step in _fetch_steps(documents):
        identity = _step_identity(step_path, step, documents)
        if not _complete_step(step) or identity is None:
            continue
        bundle_id, observed_at, snapshot_path = identity
        for diff_path, diff in _matching_diffs(step_path, bundle_id, documents):
            summary = diff.get("summary", {})
            changed = any(
                type(value) is int and value > 0 for value in summary.values()
            )
            paths = [step_path, diff_path, snapshot_path]
            candidates.append(
                {
                    "observed_at": observed_at,
                    "bundle_id": bundle_id,
                    "changed": changed,
                    "paths": paths,
                    "measurement": context_bound_measurement(
                        {
                            "bundle_id": bundle_id,
                            "changed": changed,
                            "drift_conclusion_available": True,
                            "failure_class": None,
                        },
                        coordinate={
                            "kind": "census_drift_observation",
                            "clock": "UTC",
                        },
                        scope={
                            "kind": "census_evidence_chain",
                            "directory": relative(root, step_path.parent),
                        },
                        captured_at=observed_at,
                        binds_to={
                            "baseline_bundle_id": diff["old_bundle_id"],
                            "observed_bundle_id": bundle_id,
                        },
                    ),
                }
            )
    return candidates


def _resolve_candidate(
    root: Path,
    candidate: Mapping[str, Any] | None,
    *,
    baseline_bundle_id: str,
    now: datetime,
) -> dict[str, Any]:
    scope = {"kind": "census_evidence_chain"}
    bindings = {"baseline_bundle_id": baseline_bundle_id}
    if candidate is not None:
        scope["directory"] = relative(root, candidate["paths"][0].parent)
        bindings["observed_bundle_id"] = candidate["bundle_id"]
    return resolve_context_bound_measurement(
        candidate.get("measurement") if candidate is not None else None,
        expected_coordinate={"kind": "census_drift_observation", "clock": "UTC"},
        expected_scope=scope,
        expected_bindings=bindings,
        now=now,
        max_age=CURRENT_MAX_AGE,
        future_skew=CURRENT_FUTURE_SKEW,
    )


def _missing_observation(
    root: Path,
    documents: list[tuple[Path, dict[str, Any]]],
    candidate: Mapping[str, Any] | None,
    resolution: Mapping[str, Any],
    invalid_paths: Iterable[Path] = (),
) -> dict[str, Any]:
    if candidate is not None:
        if resolution["status"] == "expired":
            missing = ["a complete Census observation no older than 26 hours"]
        elif resolution["status"] == "not_applicable":
            missing = [
                "a fetch receipt, snapshot, and complete diff bound to the reviewed baseline"
            ]
        else:
            missing = [
                "a Census observation timestamp no more than 5 minutes in the future"
            ]
        evidence = [relative(root, path) for path in candidate["paths"]]
    else:
        steps = _fetch_steps(documents)
        diffs = [
            value
            for _path, value in documents
            if value.get("kind") in {"route_diff", "bundle_snapshot_diff"}
        ]
        missing = []
        invalid = list(invalid_paths)
        if invalid:
            missing.append("valid JSON Census evidence documents")
        if not steps:
            missing.append("a current gravity-census.step-output.v1 fetch receipt")
        if not diffs:
            missing.append("a complete current route or bundle diff")
        if steps and diffs:
            missing.append(
                "a fetch receipt, snapshot, and complete diff bound to the same current bundle and reviewed baseline"
            )
        evidence = [
            *[relative(root, path) for path, _value in documents],
            *[relative(root, path) for path in invalid],
        ]
    return {
        "measured": False,
        "status": resolution["status"],
        "reason_code": resolution["reason_code"],
        "failure_class": None,
        "drift_conclusion_available": False,
        "changed": None,
        "bundle_id": candidate.get("bundle_id") if candidate else None,
        "freshness": resolution["freshness"],
        "measurement": dict(resolution),
        "missing": missing,
        "evidence": evidence,
    }


def _current_observation(
    root: Path,
    documents: list[tuple[Path, dict[str, Any]]],
    baseline_bundle_id: str,
    now: datetime,
    invalid_paths: Iterable[Path] = (),
) -> dict[str, Any]:
    candidates = _observation_candidates(root, documents)
    resolved = [
        (
            item,
            _resolve_candidate(
                root, item, baseline_bundle_id=baseline_bundle_id, now=now
            ),
        )
        for item in candidates
    ]
    current = [item for item in resolved if item[1]["status"] == "measured"]
    if current:
        candidate, resolution = max(
            current, key=lambda item: item[0]["observed_at"]
        )
        return {
            "measured": True,
            "status": "changed" if candidate["changed"] else "unchanged",
            "reason_code": None,
            "failure_class": None,
            "drift_conclusion_available": True,
            "changed": candidate["changed"],
            "bundle_id": candidate["bundle_id"],
            "freshness": resolution["freshness"],
            "measurement": resolution,
            "missing": [],
            "evidence": [relative(root, path) for path in candidate["paths"]],
        }
    if not candidates:
        invalid = list(invalid_paths)
        resolution = _resolve_candidate(
            root, None, baseline_bundle_id=baseline_bundle_id, now=now
        )
        if invalid:
            resolution = resolve_context_bound_measurement(
                {},
                expected_coordinate={
                    "kind": "census_drift_observation",
                    "clock": "UTC",
                },
                expected_scope={"kind": "census_evidence_chain"},
                expected_bindings={"baseline_bundle_id": baseline_bundle_id},
            )
        return _missing_observation(
            root,
            documents,
            None,
            resolution,
            invalid,
        )
    candidate = max(candidates, key=lambda item: item["observed_at"])
    return _missing_observation(
        root,
        documents,
        candidate,
        _resolve_candidate(
            root, candidate, baseline_bundle_id=baseline_bundle_id, now=now
        ),
    )


def census_status(
    root: Path = PROJECT_ROOT,
    evidence_paths: Iterable[Path] | None = None,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    data = root / "src/gravity_insight/census/data"
    snapshot_path = data / "bundle-snapshot.json"
    routes_path = data / "routes.json"
    coverage_path = data / "coverage.json"
    snapshot = load_object(snapshot_path)
    routes = load_object(routes_path)
    coverage = load_object(coverage_path)
    if evidence_paths is None:
        evidence_root = root / CURRENT_EVIDENCE_DIRECTORY
        supplied = sorted(evidence_root.rglob("*.json")) if evidence_root.is_dir() else []
    else:
        supplied = [path.resolve() for path in evidence_paths]
    selected_now = now or datetime.now(timezone.utc)
    if selected_now.tzinfo is None:
        raise ValueError("Census status now must include a timezone")
    selected_now = selected_now.astimezone(timezone.utc)
    documents, invalid_paths = _documents(supplied)
    current = _current_observation(
        root,
        documents,
        str(snapshot.get("bundle_id")),
        selected_now,
        invalid_paths,
    )
    summary = snapshot.get("summary", {})
    route_source = routes.get("source", {})
    coverage_summary = coverage.get("summary", {})
    return {
        "schema_version": "gravity.census-status.v1",
        "status": current["status"],
        "ok": True,
        "baseline": {
            "bundle_id": snapshot.get("bundle_id"),
            "fetched_at": snapshot.get("fetched_at"),
            "complete": summary.get("complete") is True,
            "bundle_files": summary.get("bundle_files"),
            "routes": coverage_summary.get("total_routes"),
            "accounting_complete": coverage_summary.get("accounting_complete") is True,
            "unaccounted": coverage_summary.get("unaccounted"),
            "platform_complete": route_source.get("platform_complete") is True,
            "known_excluded_origins": route_source.get("known_excluded_origins", []),
        },
        "request_governance": {
            "attempts": summary.get("request_attempts"),
            "limit": summary.get("request_limit"),
            "concurrency": summary.get("concurrency"),
            "elapsed_seconds": summary.get("elapsed_seconds"),
            "pending_js": summary.get("pending_js"),
            "failed_js": summary.get("failed_js"),
        },
        "current_evidence_policy": {
            "directory": CURRENT_EVIDENCE_DIRECTORY.as_posix(),
            "max_age_seconds": int(CURRENT_MAX_AGE.total_seconds()),
            "future_clock_skew_seconds": int(CURRENT_FUTURE_SKEW.total_seconds()),
            "artifact_retention_is_freshness": False,
        },
        "current": current,
        "failure_classes": [item.value for item in CensusFailureClass],
        "evidence": [
            relative(root, snapshot_path),
            relative(root, routes_path),
            relative(root, coverage_path),
        ],
        "network_called": False,
    }


__all__ = [
    "CURRENT_EVIDENCE_DIRECTORY",
    "CURRENT_FUTURE_SKEW",
    "CURRENT_MAX_AGE",
    "census_status",
]
