"""Parameter-guided, budgeted re-probing for existing Gravity drafts."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .batch import privacy_name_risk, write_semantics_reason
from .core import DRAFT_ROOT, EVIDENCE_ROOT, OPERATION_ROOT, REPO_ROOT, read_json, write_json
from .draft_probe import probe_draft
from .drafts import refresh_structured_blockers
from .parameters import assemble_draft_parameters
from .promotion import evaluate_gate, promote_drafts, save_draft
from .read_semantics import assert_available_probe_items, assert_probe_operation_ids
from .transport import RecordingSession, RequestDiscipline, build_runtime, sdk_parts


REPROBE_ROOT = REPO_ROOT / "tmp" / "codex" / "gi-reprobe"
PREVIOUS_SUMMARY_PATH = REPO_ROOT / "tmp" / "codex" / "gi-batch-probe" / "summary.json"
DEVELOPER_APPLICATION_OPERATION = "developer.application.list"

_FAILURE_LABELS = (
    "参数不明",
    "空数据",
    "需父资源",
    "字段隐私待审",
    "路由或运行时不可用",
    "写语义跳过",
    "无权限",
)


def _stable_ids(operation_root: Path) -> set[str]:
    result: set[str] = set()
    for path in operation_root.glob("*.json"):
        source = read_json(path)
        if source.get("operation", {}).get("stability") == "stable":
            result.add(str(source["operation"]["operation_id"]))
    return result


def _blocker_codes(source: Mapping[str, Any]) -> set[str]:
    return {
        str(item.get("code"))
        for item in source.get("draft", {}).get("blockers", [])
        if isinstance(item, Mapping) and item.get("code")
    }


def _parameterized(source: Mapping[str, Any]) -> bool:
    contract = (
        source.get("draft", {}).get("route_evidence", {}).get("parameter_contract")
    )
    return bool(
        isinstance(contract, Mapping) and contract.get("top_level_parameters")
    )


def _parameter_priority(source: Mapping[str, Any]) -> tuple[int, int, str]:
    contract = (
        source.get("draft", {}).get("route_evidence", {}).get("parameter_contract", {})
    )
    parameters = contract.get("top_level_parameters", []) if isinstance(contract, Mapping) else []
    high = sum(
        isinstance(item, Mapping) and item.get("confidence") == "high"
        for item in parameters
    )
    medium = sum(
        isinstance(item, Mapping) and item.get("confidence") == "medium"
        for item in parameters
    )
    return (-high, medium, str(source["operation"]["operation_id"]))


def select_parameter_reprobes(
    draft_root: Path = DRAFT_ROOT,
) -> tuple[list[str], list[dict[str, Any]]]:
    selected: list[tuple[Mapping[str, Any], dict[str, Any]]] = []
    skipped: list[dict[str, Any]] = []
    for path in sorted(draft_root.glob("*.json")):
        source = read_json(path)
        if "request_parameters_required" not in _blocker_codes(source):
            continue
        if not _parameterized(source):
            continue
        write_reason = write_semantics_reason(source)
        privacy_reason = privacy_name_risk(source)
        row = {
            "operation_id": path.stem,
            "write_semantics_reason": write_reason,
            "privacy_name_risk": privacy_reason,
        }
        if write_reason or privacy_reason:
            skipped.append(row)
        else:
            selected.append((source, row))
    selected.sort(key=lambda item: _parameter_priority(item[0]))
    return [str(item[0]["operation"]["operation_id"]) for item in selected], skipped


def preflight_parameter_reprobes(
    draft_root: Path = DRAFT_ROOT,
) -> tuple[list[str], list[dict[str, Any]]]:
    operation_ids, skipped = select_parameter_reprobes(draft_root)
    if (draft_root / f"{DEVELOPER_APPLICATION_OPERATION}.json").is_file():
        operation_ids.append(DEVELOPER_APPLICATION_OPERATION)
    assert_probe_operation_ids(operation_ids, draft_root=draft_root)
    return operation_ids, skipped


def prune_missing_probe_references(
    operation_id: str, *, draft_root: Path = DRAFT_ROOT,
) -> dict[str, Any]:
    path = draft_root / f"{operation_id}.json"
    if not path.is_file():
        return {"operation_id": operation_id, "removed": [], "remaining": 0}
    source = read_json(path)
    references = source.get("draft", {}).get("probe_evidence", [])
    kept: list[Mapping[str, Any]] = []
    removed: list[str] = []
    for reference in references if isinstance(references, list) else []:
        evidence_path = str(reference.get("path", "")) if isinstance(reference, Mapping) else ""
        if evidence_path and not (REPO_ROOT / evidence_path).is_file():
            removed.append(evidence_path)
        else:
            kept.append(reference)
    source["draft"]["probe_evidence"] = kept
    source = refresh_structured_blockers(
        source, source["draft"].get("route_evidence")
    )
    source["draft"]["promotion_gate"] = evaluate_gate(source)
    save_draft(source, draft_root)
    return {
        "operation_id": operation_id,
        "removed": removed,
        "remaining": len(kept),
    }


def downgrade_auth_contaminated_draft(
    operation_id: str, *, draft_root: Path = DRAFT_ROOT,
    repo_root: Path = REPO_ROOT,
) -> dict[str, Any]:
    """Discard auth-only observations that cannot prove a target response."""

    path = draft_root / f"{operation_id}.json"
    source = read_json(path)
    references = source["draft"].get("probe_evidence", [])
    kept: list[Mapping[str, Any]] = []
    removed: list[str] = []
    for reference in references:
        evidence_path = str(reference.get("path", ""))
        absolute = repo_root / evidence_path
        evidence = read_json(absolute) if absolute.is_file() else {}
        http = evidence.get("http", []) if isinstance(evidence, Mapping) else []
        auth_only = bool(http) and all(
            isinstance(item, Mapping)
            and "/user_login/" in str(item.get("path", ""))
            for item in http
        )
        if auth_only:
            removed.append(evidence_path)
        else:
            kept.append(reference)
    if removed:
        source["draft"]["probe_evidence"] = kept
        source["draft"]["candidate_fields"] = []
        source["draft"]["manual_review_fields"] = []
        source["operation"]["response_projection"] = {
            "data_keys": [],
            "required_data_keys": [],
            "item_keys": [],
            "dynamic_item_fields": [],
        }
        source["operation"]["privacy_policy"]["classification"] = "unverified"
        source["operation"]["pagination"] = {
            "kind": "unverified",
            "page_field": "",
            "page_size_field": "",
            "list_path": "",
            "page_info_path": "",
            "total_page_field": "",
        }
        source = refresh_structured_blockers(
            source, source["draft"].get("route_evidence")
        )
        source["draft"]["promotion_gate"] = evaluate_gate(source)
        save_draft(source, draft_root)
    return {"operation_id": operation_id, "removed": removed}


def _latest_conclusion(source: Mapping[str, Any]) -> str:
    evidence = source.get("draft", {}).get("probe_evidence", [])
    latest = evidence[-1] if isinstance(evidence, list) and evidence else {}
    return str(latest.get("conclusion", "")) if isinstance(latest, Mapping) else ""


def _failure_reason(
    source: Mapping[str, Any], *, write_reason: str | None, privacy_reason: str | None,
) -> str:
    missing = set(evaluate_gate(source)["missing"])
    conclusion = _latest_conclusion(source)
    if write_reason:
        return "写语义跳过"
    if (
        privacy_reason
        or conclusion in {"privacy_review_required", "success"}
        and "field_review_required" in missing
        or "field_review_required" in missing
    ):
        return "字段隐私待审"
    if conclusion == "permission_or_auth_unavailable":
        return "无权限"
    if "parent_resource_required" in missing and conclusion in {
        "local_or_parent_inconclusive", "semantic_error", ""
    }:
        return "需父资源"
    if conclusion == "semantic_error" or "request_parameters_required" in missing:
        return "参数不明"
    if conclusion in {"inconclusive_empty", "available_empty"} or "empty_sample" in missing:
        return "空数据"
    return "路由或运行时不可用"


def _previous_failure_counts(path: Path = PREVIOUS_SUMMARY_PATH) -> dict[str, int]:
    previous = read_json(path)
    raw = previous.get("failure_counts", {}) if isinstance(previous, Mapping) else {}
    normalized = {
        "字段待审": "字段隐私待审",
        "路由不可用": "路由或运行时不可用",
    }
    counts = Counter()
    for name, count in raw.items() if isinstance(raw, Mapping) else []:
        counts[normalized.get(str(name), str(name))] += int(count)
    return {label: counts[label] for label in _FAILURE_LABELS}


def failure_comparison(
    inventory: Sequence[Mapping[str, Any]], *, draft_root: Path = DRAFT_ROOT,
    operation_root: Path = OPERATION_ROOT,
) -> dict[str, Any]:
    stable = _stable_ids(operation_root)
    current = Counter()
    rows: list[dict[str, Any]] = []
    for item in inventory:
        operation_id = str(item["operation_id"])
        if operation_id in stable:
            continue
        path = draft_root / f"{operation_id}.json"
        if not path.is_file():
            continue
        source = read_json(path)
        reason = _failure_reason(
            source,
            write_reason=item.get("write_semantics_reason"),
            privacy_reason=item.get("privacy_name_risk"),
        )
        current[reason] += 1
        rows.append(
            {
                "operation_id": operation_id,
                "failure_reason": reason,
                "latest_conclusion": _latest_conclusion(source) or None,
                "missing": evaluate_gate(source)["missing"],
            }
        )
    previous = _previous_failure_counts()
    comparison = [
        {
            "reason": label,
            "previous": previous[label],
            "current": current[label],
            "delta": current[label] - previous[label],
        }
        for label in _FAILURE_LABELS
    ]
    return {
        "schema_version": "gravity-insight.reprobe-failure-comparison.v1",
        "previous_total": sum(previous.values()),
        "current_total": sum(current.values()),
        "comparison": comparison,
        "results": rows,
    }


def _write_parameter_selection(
    report_root: Path,
    draft_root: Path,
    operation_ids: Sequence[str],
    skipped: Sequence[Mapping[str, Any]],
) -> None:
    assert_probe_operation_ids(operation_ids, draft_root=draft_root)
    write_json(
        report_root / "selection.json",
        {
            "parameter_targets": len(operation_ids)
            - int(DEVELOPER_APPLICATION_OPERATION in operation_ids),
            "operation_ids": operation_ids,
            "skipped": skipped,
        },
    )


@dataclass(frozen=True)
class ProbeContext:
    discipline: RequestDiscipline
    recording: RecordingSession
    runtime: Any
    stable_client: Any


def build_probe_context(
    *, session: Any | None, interval_seconds: float, request_limit: int,
) -> ProbeContext:
    if session is None:
        try:
            import requests
        except ImportError as exc:
            raise RuntimeError("requests is required for online Gravity probing") from exc
        session = requests.Session()
    discipline = RequestDiscipline(
        interval_seconds=interval_seconds, request_limit=request_limit, hard_limit=900
    )
    recording = RecordingSession(session, discipline)
    runtime = build_runtime(recording)
    stable_client = sdk_parts()["GravityInsightClient"].from_env(
        runtime=runtime, timeout=120.0, attempts=1
    )
    return ProbeContext(discipline, recording, runtime, stable_client)


def run_parameter_targets(
    context: ProbeContext, operation_ids: Sequence[str], *, draft_root: Path,
    evidence_root: Path, results_path: Path,
) -> tuple[list[dict[str, Any]], bool]:
    results: list[dict[str, Any]] = []
    stopped = False
    for operation_id in operation_ids:
        if context.discipline.request_limit - context.discipline.total < 8:
            stopped = True
            break
        try:
            result = probe_draft(
                read_json(draft_root / f"{operation_id}.json"),
                stable_client=context.stable_client, runtime=context.runtime,
                recording=context.recording, evidence_root=evidence_root,
                draft_root=draft_root,
            )
        except RuntimeError as exc:
            if "budget exhausted" in str(exc):
                stopped = True
                break
            raise
        results.append(result)
        write_json(results_path, {"results": results})
        if context.discipline.domain_stopped:
            break
    return results, stopped


def run_scoped_targets(
    context: ProbeContext, operation_ids: Sequence[str], *, draft_root: Path,
    evidence_root: Path, results_path: Path,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for operation_id in operation_ids:
        if context.discipline.request_limit - context.discipline.total < 10:
            break
        path = draft_root / f"{operation_id}.json"
        if not path.is_file():
            continue
        results.append(probe_draft(
            read_json(path), stable_client=context.stable_client,
            runtime=context.runtime, recording=context.recording,
            evidence_root=evidence_root, draft_root=draft_root,
        ))
        write_json(results_path, {"results": results})
        if context.discipline.domain_stopped:
            break
    return results


def promote_probe_results(
    results: Sequence[Mapping[str, Any]], *, draft_root: Path,
    operation_root: Path,
) -> list[dict[str, Any]]:
    promoted: list[dict[str, Any]] = []
    for result in results:
        operation_id = str(result["operation_id"])
        if result.get("eligible") and (draft_root / f"{operation_id}.json").is_file():
            promoted.extend(promote_drafts(
                [operation_id], draft_root=draft_root,
                operation_root=operation_root, compile_products=False,
            ))
    if promoted:
        from gravity_sdk.compiler import ContractCompiler

        ContractCompiler().compile()
    return promoted


def parameter_adjustment_stats(
    results: Sequence[Mapping[str, Any]],
) -> tuple[int, int]:
    adjustment_count = adjusted_successes = 0
    for result in results:
        evidence = read_json(REPO_ROOT / str(result["evidence"]))
        semantic = evidence.get("semantic_errors", {})
        adjustments = semantic.get("parameter_adjustments", []) if isinstance(semantic, Mapping) else []
        adjustment_count += len(adjustments) if isinstance(adjustments, list) else 0
        if result.get("conclusion") == "success" and adjustments:
            adjusted_successes += 1
    return adjustment_count, adjusted_successes


def request_summary(discipline: RequestDiscipline) -> dict[str, Any]:
    return {
        "probe_total": discipline.total, "failed_http": discipline.failed,
        "backoff_events": discipline.backoff_events,
        "backoff_terminations": discipline.backoff_terminations,
        "request_limit": discipline.request_limit,
        "minimum_interval_ms": int(discipline.interval_seconds * 1000),
        "concurrency": 1,
    }


def run_parameter_reprobes(
    *, interval_seconds: float = 0.31, request_limit: int = 850,
    draft_root: Path = DRAFT_ROOT, operation_root: Path = OPERATION_ROOT,
    evidence_root: Path = EVIDENCE_ROOT, report_root: Path = REPROBE_ROOT,
    session: Any | None = None,
) -> dict[str, Any]:
    initial_stable = len(_stable_ids(operation_root))
    initial_sources = [read_json(path) for path in sorted(draft_root.glob("*.json"))]
    inventory = [
        {
            "operation_id": str(source["operation"]["operation_id"]),
            "write_semantics_reason": write_semantics_reason(source),
            "privacy_name_risk": privacy_name_risk(source),
        }
        for source in initial_sources
    ]
    assembly = assemble_draft_parameters(draft_root=draft_root)
    write_json(report_root / "parameter-assembly.json", assembly)
    operation_ids, skipped = select_parameter_reprobes(draft_root)
    if (draft_root / f"{DEVELOPER_APPLICATION_OPERATION}.json").is_file():
        operation_ids.append(DEVELOPER_APPLICATION_OPERATION)
    _write_parameter_selection(report_root, draft_root, operation_ids, skipped)

    context = build_probe_context(
        session=session, interval_seconds=interval_seconds,
        request_limit=request_limit,
    )
    results, stopped_for_budget = run_parameter_targets(
        context, operation_ids, draft_root=draft_root,
        evidence_root=evidence_root,
        results_path=report_root / "probe-results.json",
    )

    developer_evidence = prune_missing_probe_references(
        DEVELOPER_APPLICATION_OPERATION, draft_root=draft_root
    )
    promoted = promote_probe_results(
        results, draft_root=draft_root, operation_root=operation_root
    )
    adjustment_count, adjusted_successes = parameter_adjustment_stats(results)

    comparison = failure_comparison(
        inventory, draft_root=draft_root, operation_root=operation_root
    )
    write_json(report_root / "failure-comparison.json", comparison)
    final_stable = len(_stable_ids(operation_root))
    summary = {
        "schema_version": "gravity-insight.parameter-reprobe.v1",
        "initial_drafts": len(initial_sources),
        "initial_stable": initial_stable,
        "final_stable": final_stable,
        "stable_net_increase": final_stable - initial_stable,
        "parameter_targets": len(operation_ids) - int(DEVELOPER_APPLICATION_OPERATION in operation_ids),
        "skipped_parameter_targets": len(skipped),
        "attempted": len(results),
        "successful": sum(result.get("conclusion") == "success" for result in results),
        "promoted": len(promoted),
        "promoted_operation_ids": [item["operation_id"] for item in promoted],
        "parameter_retry_adjustments": adjustment_count,
        "succeeded_after_parameter_adjustment": adjusted_successes,
        "stopped_for_budget": stopped_for_budget,
        "developer_application_evidence": developer_evidence,
        "requests": request_summary(context.discipline),
        "assembly": {
            key: value for key, value in assembly.items() if key != "operations"
        },
        "failure_comparison": comparison["comparison"],
    }
    write_json(report_root / "summary.json", summary)
    return summary


def run_scoped_reprobes(
    operation_ids: Sequence[str], *, interval_seconds: float = 0.31,
    request_limit: int = 500, draft_root: Path = DRAFT_ROOT,
    operation_root: Path = OPERATION_ROOT, evidence_root: Path = EVIDENCE_ROOT,
    report_root: Path = REPROBE_ROOT, report_name: str = "scoped-reprobe",
    session: Any | None = None,
) -> dict[str, Any]:
    """Run a second, explicit subset through the same probe and promotion gates."""

    if not operation_ids:
        raise ValueError("scoped reprobe requires at least one operation")
    assert_available_probe_items(operation_ids, draft_root=draft_root)
    initial_stable = len(_stable_ids(operation_root))
    context = build_probe_context(
        session=session, interval_seconds=interval_seconds,
        request_limit=request_limit,
    )
    results = run_scoped_targets(
        context, operation_ids, draft_root=draft_root,
        evidence_root=evidence_root,
        results_path=report_root / f"{report_name}-results.json",
    )
    promoted = promote_probe_results(
        results, draft_root=draft_root, operation_root=operation_root
    )
    adjustments, adjusted_successes = parameter_adjustment_stats(results)
    final_stable = len(_stable_ids(operation_root))
    summary = {
        "schema_version": "gravity-insight.scoped-reprobe.v1",
        "requested": len(operation_ids),
        "attempted": len(results),
        "successful": sum(item.get("conclusion") == "success" for item in results),
        "promoted": len(promoted),
        "promoted_operation_ids": [item["operation_id"] for item in promoted],
        "initial_stable": initial_stable,
        "final_stable": final_stable,
        "stable_net_increase": final_stable - initial_stable,
        "parameter_retry_adjustments": adjustments,
        "succeeded_after_parameter_adjustment": adjusted_successes,
        "requests": request_summary(context.discipline),
    }
    write_json(report_root / f"{report_name}-summary.json", summary)
    return summary


__all__ = [
    "DEVELOPER_APPLICATION_OPERATION",
    "REPROBE_ROOT",
    "failure_comparison",
    "downgrade_auth_contaminated_draft",
    "prune_missing_probe_references",
    "run_parameter_reprobes",
    "run_scoped_reprobes",
    "preflight_parameter_reprobes",
    "select_parameter_reprobes",
]
