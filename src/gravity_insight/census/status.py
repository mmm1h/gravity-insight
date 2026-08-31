"""Current offline Census evidence without making an upstream request."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Mapping

from gravity_insight.evidence_common import load_object, relative
from gravity_insight.paths import PROJECT_ROOT

from .diffing import CensusFailureClass


def _documents(paths: Iterable[Path]) -> list[tuple[Path, dict[str, Any]]]:
    result: list[tuple[Path, dict[str, Any]]] = []
    for path in paths:
        if path.is_file():
            result.append((path, load_object(path)))
    return result


def _current_observation(
    root: Path, documents: list[tuple[Path, dict[str, Any]]]
) -> dict[str, Any]:
    steps, diffs = _observation_receipts(documents)
    if not steps or not diffs:
        return _missing_observation(root, documents, steps=steps, diffs=diffs)
    step_path, step = steps[-1]
    diff_path, diff = diffs[-1]
    return _measured_observation(root, step_path, step, diff_path, diff)


def _observation_receipts(
    documents: list[tuple[Path, dict[str, Any]]],
) -> tuple[list[tuple[Path, dict[str, Any]]], list[tuple[Path, dict[str, Any]]]]:
    steps = [
        item
        for item in documents
        if item[1].get("schema_version") == "gravity-census.step-output.v1"
    ]
    diffs = [
        item
        for item in documents
        if "drift_conclusion_available" in item[1]
        and item[1].get("kind") in {"route_diff", "bundle_snapshot_diff"}
    ]
    return steps, diffs


def _missing_observation(
    root: Path,
    documents: list[tuple[Path, dict[str, Any]]],
    *,
    steps: list[tuple[Path, dict[str, Any]]],
    diffs: list[tuple[Path, dict[str, Any]]],
) -> dict[str, Any]:
    missing = []
    if not steps:
        missing.append("a current gravity-census.step-output.v1 fetch receipt")
    if not diffs:
        missing.append("a complete current route or bundle diff")
    return {
        "measured": False,
        "status": "unmeasured",
        "failure_class": None,
        "drift_conclusion_available": False,
        "changed": None,
        "missing": missing,
        "evidence": [relative(root, path) for path, _value in documents],
    }


def _measured_observation(
    root: Path,
    step_path: Path,
    step: Mapping[str, Any],
    diff_path: Path,
    diff: Mapping[str, Any],
) -> dict[str, Any]:
    complete = step.get("complete") is True
    conclusion = diff.get("drift_conclusion_available") is True
    summary = diff.get("summary") if isinstance(diff.get("summary"), Mapping) else {}
    changed = any(type(value) is int and value > 0 for value in summary.values())
    failure = step.get("failure_class")
    if failure is not None and failure not in {item.value for item in CensusFailureClass}:
        failure = CensusFailureClass.UNCLASSIFIED.value
    measured = complete and conclusion
    status = "changed" if changed else "unchanged"
    if not measured:
        status = "blocked"
    return {
        "measured": measured,
        "status": status,
        "failure_class": failure,
        "drift_conclusion_available": conclusion,
        "changed": changed if conclusion else None,
        "missing": [] if measured else ["complete fetch and diff evidence"],
        "evidence": [relative(root, step_path), relative(root, diff_path)],
    }


def census_status(
    root: Path = PROJECT_ROOT, evidence_paths: Iterable[Path] = ()
) -> dict[str, Any]:
    root = root.resolve()
    data = root / "src/gravity_insight/census/data"
    snapshot_path = data / "bundle-snapshot.json"
    routes_path = data / "routes.json"
    coverage_path = data / "coverage.json"
    snapshot = load_object(snapshot_path)
    routes = load_object(routes_path)
    coverage = load_object(coverage_path)
    supplied = [path.resolve() for path in evidence_paths]
    if not supplied:
        supplied = sorted(data.glob("*.json"))
    current = _current_observation(root, _documents(supplied))
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
        "current": current,
        "failure_classes": [item.value for item in CensusFailureClass],
        "evidence": [
            relative(root, snapshot_path),
            relative(root, routes_path),
            relative(root, coverage_path),
        ],
        "network_called": False,
    }


__all__ = ["census_status"]
