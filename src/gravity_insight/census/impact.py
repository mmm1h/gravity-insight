from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping

try:
    from gravity_insight.drift import HealthOverlay
except ModuleNotFoundError:  # source checkout before editable installation
    from gravity_insight.drift import HealthOverlay

from .io import read_json
from .normalize import comparison_path


def _route_key(method: Any, path: Any) -> tuple[str, str]:
    return str(method or "UNKNOWN").upper(), comparison_path(str(path or ""))


def _operation_document(path: Path, operation_id: str) -> Mapping[str, Any]:
    document = read_json(path)
    if not isinstance(document, Mapping):
        raise ValueError(f"contract source is not an object: {path}")
    operation = document.get("operation", document)
    if not isinstance(operation, Mapping):
        raise ValueError(f"contract source has no operation object: {path}")
    if str(operation.get("operation_id", "")) != operation_id:
        raise ValueError(f"provenance source does not define {operation_id}: {path}")
    return operation


def build_provenance_route_index(
    provenance: Mapping[str, Any], contracts_root: Path
) -> dict[str, Any]:
    """Resolve provenance source files into a route-to-operation reverse index."""

    operations = provenance.get("operations")
    if not isinstance(operations, Mapping):
        raise ValueError("provenance must contain an operations object")
    declared_count = provenance.get("operation_count")
    if isinstance(declared_count, int) and declared_count != len(operations):
        raise ValueError(
            f"provenance operation_count={declared_count} does not match {len(operations)} entries"
        )
    resolved_root = contracts_root.resolve()
    rows: list[dict[str, Any]] = []
    by_route: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)

    for operation_id, raw_metadata in sorted(operations.items()):
        metadata = raw_metadata if isinstance(raw_metadata, Mapping) else {}
        source_files = metadata.get("source_files")
        if not isinstance(source_files, list) or not source_files:
            raise ValueError(f"provenance for {operation_id} has no source_files")
        source_path = (resolved_root / str(source_files[0])).resolve()
        if not source_path.is_relative_to(resolved_root):
            raise ValueError(f"provenance source escapes contracts root: {source_files[0]}")
        operation = _operation_document(source_path, str(operation_id))
        method = str(operation.get("upstream_method", "UNKNOWN")).upper()
        path = str(operation.get("path_template", ""))
        if not path:
            raise ValueError(f"operation {operation_id} has no path_template")
        row = {
            "operation_id": str(operation_id),
            "method": method,
            "path": path,
            "domain": operation.get("domain"),
            "resource": operation.get("resource"),
            "level": operation.get("level", operation.get("resource")),
            "action": operation.get("action"),
            "stability": operation.get("stability"),
            "executable": bool(operation.get("executable", True)),
            "family": metadata.get("family"),
            "platform": metadata.get("platform"),
            "applied_overrides": sorted(
                str(item) for item in metadata.get("applied_overrides", ())
            ),
            "source_files": [str(item) for item in source_files],
        }
        rows.append(row)
        by_route[_route_key(method, path)].append(row)
    return {
        "operations": rows,
        "by_route": {
            key: sorted(value, key=lambda item: item["operation_id"])
            for key, value in by_route.items()
        },
    }


def _change(
    *,
    change_id: str,
    impact_type: str,
    old_method: str | None,
    old_path: str | None,
    new_method: str | None,
    new_path: str | None,
    certainty: str,
) -> dict[str, Any]:
    return {
        "change_id": change_id,
        "impact_type": impact_type,
        "old_method": old_method,
        "old_path": old_path,
        "new_method": new_method,
        "new_path": new_path,
        "certainty": certainty,
    }


def _actions(impact_types: set[str], complete: bool) -> tuple[str, list[str]]:
    destructive = bool(impact_types & {"route_removed", "method_changed", "path_changed"})
    if destructive and complete:
        return (
            "P0",
            [
                "fail closed through the health overlay",
                "run the targeted probe to distinguish frontend removal from backend removal",
                "open a reviewed contract diff; never rewrite the source contract automatically",
            ],
        )
    if destructive:
        return (
            "P1",
            [
                "keep the operation callable as suspect",
                "complete the static census and run the targeted probe",
            ],
        )
    return (
        "P2",
        [
            "keep existing operations callable",
            "reconcile coverage and probe before proposing a new contract",
        ],
    )


def _removed_changes(route_diff: Mapping[str, Any], complete: bool) -> list[dict[str, Any]]:
    return [
        _change(
            change_id=f"removed:{str(row.get('method', 'UNKNOWN')).upper()}:{str(row.get('path', ''))}",
            impact_type="route_removed",
            old_method=str(row.get("method", "UNKNOWN")).upper(),
            old_path=str(row.get("path", "")),
            new_method=None,
            new_path=None,
            certainty="confirmed_static_graph" if complete else "incomplete_static_graph",
        )
        for row in route_diff.get("removed", ())
    ]


def _method_changes(route_diff: Mapping[str, Any], complete: bool) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    for row in route_diff.get("method_changes", ()):
        path = str(row.get("path", ""))
        new_methods = sorted(str(item).upper() for item in row.get("new_methods", ()))
        new_method = ",".join(new_methods) or None
        for old_method in sorted(str(item).upper() for item in row.get("old_methods", ())):
            changes.append(
                _change(
                    change_id=f"method:{path}:{old_method}->{new_method or 'NONE'}",
                    impact_type="method_changed",
                    old_method=old_method,
                    old_path=path,
                    new_method=new_method,
                    new_path=path,
                    certainty="confirmed_static_graph" if complete else "incomplete_static_graph",
                )
            )
    return changes


def _path_changes(route_diff: Mapping[str, Any], complete: bool) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    for row in route_diff.get("path_changes", ()):
        method = str(row.get("method", "UNKNOWN")).upper()
        old_path = str(row.get("old_path", ""))
        new_path = str(row.get("new_path", ""))
        changes.append(
            _change(
                change_id=f"path:{method}:{old_path}->{new_path}",
                impact_type="path_changed",
                old_method=method,
                old_path=old_path,
                new_method=method,
                new_path=new_path,
                certainty=(
                    "old_route_absence_confirmed_new_path_heuristic"
                    if complete
                    else "incomplete_static_graph_and_heuristic"
                ),
            )
        )
    return changes


def _added_changes(route_diff: Mapping[str, Any], complete: bool) -> list[dict[str, Any]]:
    return [
        _change(
            change_id=f"added:{str(row.get('method', 'UNKNOWN')).upper()}:{str(row.get('path', ''))}",
            impact_type="route_added",
            old_method=None,
            old_path=None,
            new_method=str(row.get("method", "UNKNOWN")).upper(),
            new_path=str(row.get("path", "")),
            certainty="confirmed_static_graph" if complete else "incomplete_static_graph",
        )
        for row in route_diff.get("added", ())
    ]


def _route_changes(route_diff: Mapping[str, Any], complete: bool) -> list[dict[str, Any]]:
    return [
        *_removed_changes(route_diff, complete),
        *_method_changes(route_diff, complete),
        *_path_changes(route_diff, complete),
        *_added_changes(route_diff, complete),
    ]


def _unmapped_change(change: dict[str, Any]) -> dict[str, Any]:
    return {
        **change,
        "priority": "P2",
        "suggested_actions": [
            "reconcile the new route with coverage",
            "collect an authorized probe before proposing a reviewed contract",
        ],
    }


def _map_changes(
    changes: list[dict[str, Any]],
    by_route: Mapping[tuple[str, str], list[dict[str, Any]]],
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    impacted: dict[str, dict[str, Any]] = {}
    unmapped: list[dict[str, Any]] = []
    for change in sorted(changes, key=lambda item: item["change_id"]):
        method = change["old_method"] or change["new_method"] or "UNKNOWN"
        path = change["old_path"] or change["new_path"] or ""
        matched = by_route.get(_route_key(method, path), [])
        if not matched:
            unmapped.append(_unmapped_change(change))
            continue
        for operation in matched:
            item = impacted.setdefault(
                operation["operation_id"],
                {
                    **operation,
                    "impact_types": set(),
                    "route_changes": [],
                    "evidence_refs": [],
                },
            )
            item["impact_types"].add(change["impact_type"])
            item["route_changes"].append(change)
            item["evidence_refs"].append(change["change_id"])
    return impacted, unmapped


def _operation_rows(
    impacted: Mapping[str, dict[str, Any]], complete: bool
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for _, item in sorted(impacted.items()):
        impact_types = set(item.pop("impact_types"))
        priority, actions = _actions(impact_types, complete)
        item["impact_types"] = sorted(impact_types)
        item["route_changes"] = sorted(
            item["route_changes"], key=lambda value: value["change_id"]
        )
        item["evidence_refs"] = sorted(set(item["evidence_refs"]))
        item["priority"] = priority
        item["suggested_actions"] = actions
        rows.append(item)
    return rows


def _family_samples(
    operation_rows: list[dict[str, Any]], index_operations: list[dict[str, Any]]
) -> list[str]:
    direct_ids = {item["operation_id"] for item in operation_rows}
    families = {
        str(item["family"])
        for item in operation_rows
        if item.get("family") not in {None, ""}
    }
    samples: list[str] = []
    for family in sorted(families):
        peers = sorted(
            item["operation_id"]
            for item in index_operations
            if item.get("family") == family and item["operation_id"] not in direct_ids
        )
        samples.extend(peers[:3])
    return sorted(set(samples))


def _withheld_impact(route_diff: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "gravity-census.route-impact.v1",
        "status": "incomplete",
        "candidate_diff_only": True,
        "source_contracts_modified": False,
        "impact_conclusion_available": False,
        "failure_class": "content_incomplete",
        "classification_reason": "route_diff_conclusion_was_withheld",
        "old_bundle_id": route_diff.get("old_bundle_id"),
        "new_bundle_id": route_diff.get("new_bundle_id"),
        "census_complete": False,
        "summary": {
            "route_changes": None,
            "affected_operations": None,
            "unmapped_changes": None,
            "direct_probes": None,
            "family_sample_probes": None,
        },
        "operations": [],
        "unmapped_changes": [],
        "probe_plan": {
            "status": "withheld",
            "mode": "none",
            "business_api_called": False,
            "direct_operation_ids": [],
            "family_sample_operation_ids": [],
            "commands": [],
            "reason": "A complete route diff is required before scheduling probes.",
        },
        "scope_note": (
            "No drift or impact conclusion was made because static-graph "
            "completeness was not proven."
        ),
    }


def locate_route_impacts(
    route_diff: Mapping[str, Any],
    provenance: Mapping[str, Any],
    contracts_root: Path,
    *,
    census_complete: bool | None = None,
) -> dict[str, Any]:
    evidence_complete = (
        route_diff.get("drift_conclusion_available") is True
        and route_diff.get("old_bundle_complete") is True
        and route_diff.get("new_bundle_complete") is True
    )
    complete = evidence_complete and census_complete is not False
    if not complete:
        return _withheld_impact(route_diff)
    index = build_provenance_route_index(provenance, contracts_root)
    by_route: Mapping[tuple[str, str], list[dict[str, Any]]] = index["by_route"]
    changes = _route_changes(route_diff, complete)
    impacted, unmapped = _map_changes(changes, by_route)
    operation_rows = _operation_rows(impacted, complete)
    direct_probe_ids = sorted(item["operation_id"] for item in operation_rows)
    family_samples = _family_samples(operation_rows, index["operations"])

    return {
        "schema_version": "gravity-census.route-impact.v1",
        "status": "complete",
        "candidate_diff_only": True,
        "source_contracts_modified": False,
        "old_bundle_id": route_diff.get("old_bundle_id"),
        "new_bundle_id": route_diff.get("new_bundle_id"),
        "census_complete": complete,
        "impact_conclusion_available": True,
        "failure_class": None,
        "summary": {
            "route_changes": len(changes),
            "affected_operations": len(operation_rows),
            "unmapped_changes": len(unmapped),
            "direct_probes": len(direct_probe_ids),
            "family_sample_probes": len(family_samples),
        },
        "operations": operation_rows,
        "unmapped_changes": unmapped,
        "probe_plan": {
            "mode": "schedule_only",
            "business_api_called": False,
            "direct_operation_ids": direct_probe_ids,
            "family_sample_operation_ids": family_samples,
            "commands": [
                f"python -m gravity_insight.prober probe {operation_id}"
                for operation_id in direct_probe_ids + family_samples
            ],
        },
        "scope_note": (
            "Completeness covers only the public-entry static graph; authenticated, tenant, "
            "role, feature-flag, and runtime-composed routes remain outside this evidence."
        ),
    }


def assess_route_impacts(
    route_diff: Mapping[str, Any],
    provenance: Mapping[str, Any],
    contracts_root: Path,
    *,
    census_complete: bool | None = None,
    overlay: HealthOverlay | None = None,
) -> dict[str, Any]:
    report = locate_route_impacts(
        route_diff,
        provenance,
        contracts_root,
        census_complete=census_complete,
    )
    active_overlay = overlay or HealthOverlay()
    if report.get("impact_conclusion_available") is not True:
        report["health_overlay"] = active_overlay.snapshot()
        return report
    health = active_overlay.apply_impact_report(report)
    for operation in report["operations"]:
        operation_id = operation["operation_id"]
        operation["health"] = health[operation_id]
        operation["call_decision"] = active_overlay.call_decision(operation_id)
    report["health_overlay"] = active_overlay.snapshot()
    return report


def impact_files(
    diff_path: Path,
    provenance_path: Path,
    contracts_root: Path,
    *,
    census_complete: bool | None = None,
    overlay: HealthOverlay | None = None,
) -> dict[str, Any]:
    route_diff = read_json(diff_path)
    provenance = read_json(provenance_path)
    if not isinstance(route_diff, Mapping) or route_diff.get("kind") != "route_diff":
        raise ValueError("impact input must be a route_diff document")
    if not isinstance(provenance, Mapping):
        raise ValueError("provenance input must be an object")
    return assess_route_impacts(
        route_diff,
        provenance,
        contracts_root,
        census_complete=census_complete,
        overlay=overlay,
    )
