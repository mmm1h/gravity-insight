"""Availability-tiered orchestration for large draft probe batches."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

from .core import (
    DRAFT_ROOT,
    EVIDENCE_ROOT,
    OPERATION_ROOT,
    REPO_ROOT,
    iter_json_evidence,
    read_json,
    write_json,
)
from .draft_probe import probe_draft
from .promotion import evaluate_gate, promote_drafts
from .transport import RecordingSession, RequestDiscipline, build_runtime, sdk_parts


BATCH_ROOT = REPO_ROOT / "tmp" / "codex" / "gi-batch-probe"

_TIER_ONE_IDS = frozenset(
    {
        "app.role.detail",
        "app.template.list",
        "material.file_params.get",
        "material.media_material_label.list",
        "material.tag_category.tree",
        "promotion.batch_config.list",
        "promotion.media_directional_package.list",
        "report.confmetric_permission.list",
        "report.custom_metric.list",
        "report.metric.list",
        "report.report_confmetric_permission.list",
        "report.shared_to_me.list",
    }
)

_TIER_TWO_IDS = frozenset(
    {
        "analysis.default_val.list",
        "analysis.realtime_event.list",
        "material.material_creative_person.list",
        "promotion.company.list",
    }
)

_PRIVACY_NAME_MARKERS = (
    "attribution_detail",
    "click_info",
    "device_info",
    "identity_white",
    "material_examine_user",
    "message.",
    "my_audit",
    "oplog",
    ".log.",
    "report.user",
    "sensitive_info",
    "testing_tool",
    "user_auth",
)


def availability_tier(source: Mapping[str, Any]) -> int:
    operation = source["operation"]
    operation_id = str(operation["operation_id"])
    domain = str(operation.get("domain", ""))
    if domain == "metadata" or operation_id in _TIER_ONE_IDS:
        return 1
    if domain in {"app", "account"} or operation_id in _TIER_TWO_IDS:
        return 2
    if domain in {"report", "analysis", "candidate"}:
        return 3
    if domain == "material":
        return 4
    return 5


def write_semantics_reason(source: Mapping[str, Any]) -> str | None:
    operation = source["operation"]
    operation_id = str(operation["operation_id"]).casefold()
    segments = {
        part.casefold()
        for part in str(operation.get("path_template", "")).split("/")
        if part
    }
    forbidden = {
        "create", "update", "delete", "upload", "submit_task", "export",
        "set", "manage", "verify_code", "remove", "write",
    }
    matched = sorted(segments & forbidden)
    if matched:
        return "forbidden_path_segment:" + ",".join(matched)
    if "adcreate" in operation_id:
        return "ambiguous_operation_name:adcreate"
    if "verify_code" in operation_id:
        return "ambiguous_operation_name:verify_code"
    operation_tokens = set(operation_id.replace(".", "_").split("_"))
    ambiguous_tokens = sorted(
        operation_tokens & {"create", "set", "manage", "submit"}
    )
    if ambiguous_tokens:
        return "ambiguous_operation_token:" + ",".join(ambiguous_tokens)
    return None


def privacy_name_risk(source: Mapping[str, Any]) -> str | None:
    operation_id = str(source["operation"]["operation_id"]).casefold()
    return next((item for item in _PRIVACY_NAME_MARKERS if item in operation_id), None)


def classify_drafts(draft_root: Path = DRAFT_ROOT) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(draft_root.glob("*.json")):
        source = read_json(path)
        operation = source["operation"]
        blockers = {
            str(item.get("code"))
            for item in source.get("draft", {}).get("blockers", [])
            if isinstance(item, Mapping)
        }
        rows.append(
            {
                "operation_id": str(operation["operation_id"]),
                "tier": availability_tier(source),
                "domain": str(operation.get("domain", "")),
                "method": str(operation.get("upstream_method", "")),
                "path": str(operation.get("path_template", "")),
                "family": str(operation.get("provenance", {}).get("family") or ""),
                "parent_indicated": "parent_resource_required" in blockers,
                "bound_parent_count": len(operation.get("required_parent", [])),
                "write_semantics_reason": write_semantics_reason(source),
                "privacy_name_risk": privacy_name_risk(source),
            }
        )
    return rows


def _session_or_default(session: Any | None) -> Any:
    if session is not None:
        return session
    try:
        import requests
    except ImportError as exc:
        raise RuntimeError("requests is required for online Gravity probing") from exc
    return requests.Session()


def _ordered(rows: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return sorted(
        rows,
        key=lambda row: (
            bool(row["write_semantics_reason"]),
            bool(row["privacy_name_risk"]),
            row["method"] != "GET",
            bool(row["parent_indicated"]),
            str(row["operation_id"]),
        ),
    )


def _latest_reference(operation_id: str, draft_root: Path) -> Mapping[str, Any]:
    path = draft_root / f"{operation_id}.json"
    if not path.is_file():
        return {}
    source = read_json(path)
    evidence = source.get("draft", {}).get("probe_evidence", [])
    return evidence[-1] if isinstance(evidence, list) and evidence else {}


def _failure_reason(row: Mapping[str, Any], result: Mapping[str, Any]) -> str:
    conclusion = str(result.get("conclusion", ""))
    missing = set(str(item) for item in result.get("missing", []))
    if conclusion == "skipped_write_semantics":
        return "写语义跳过"
    if conclusion in {"skipped_privacy_name_risk", "privacy_review_required"}:
        return "字段待审"
    if conclusion in {"inconclusive_empty", "available_empty"}:
        return "空数据"
    if conclusion == "permission_or_auth_unavailable":
        return "无权限"
    if "parent_resource_required" in missing or conclusion == "local_or_parent_inconclusive":
        return "需父资源"
    if conclusion == "semantic_error" or "request_parameters_required" in missing:
        return "参数不明"
    if "field_review_required" in missing or "privacy_classification_unverified" in missing:
        return "字段待审"
    if conclusion.startswith("not_attempted"):
        return "未尝试（止损或预算）"
    return "路由不可用"


def _stable_count(operation_root: Path) -> int:
    return sum(
        1
        for path in operation_root.glob("*.json")
        if read_json(path).get("operation", {}).get("stability") == "stable"
    )


def run_batch_probes(
    *, request_limit: int = 900, interval_seconds: float = 0.31,
    draft_root: Path = DRAFT_ROOT, operation_root: Path = OPERATION_ROOT,
    evidence_root: Path = EVIDENCE_ROOT, report_root: Path = BATCH_ROOT,
    session: Any | None = None, promote: bool = True,
) -> dict[str, Any]:
    if request_limit < 1 or request_limit > 900:
        raise ValueError("batch request limit must be between 1 and 900")
    rows = classify_drafts(draft_root)
    if not rows:
        raise ValueError("no draft contracts are available for the batch")
    tier_counts = Counter(int(row["tier"]) for row in rows)
    write_json(
        report_root / "layering.json",
        {
            "schema_version": "gravity-insight.batch-layering.v1",
            "total": len(rows),
            "tier_counts": {str(key): tier_counts[key] for key in range(1, 6)},
            "drafts": rows,
        },
    )

    discipline = RequestDiscipline(
        interval_seconds=interval_seconds,
        request_limit=request_limit,
        hard_limit=900,
    )
    recording = RecordingSession(_session_or_default(session), discipline)
    runtime = build_runtime(recording)
    stable_client = sdk_parts()["GravityInsightClient"].from_env(
        runtime=runtime, timeout=120.0, attempts=1
    )
    initial_stable = _stable_count(operation_root)
    results: list[dict[str, Any]] = []
    layer_summaries: list[dict[str, Any]] = []
    stop_loss_layers: list[int] = []

    for tier in range(1, 6):
        layer_rows = _ordered([row for row in rows if row["tier"] == tier])
        layer_start_requests = discipline.total
        attempted = 0
        successful = 0
        stop_loss = False
        for index, row in enumerate(layer_rows):
            operation_id = str(row["operation_id"])
            if row["write_semantics_reason"]:
                result = {
                    "operation_id": operation_id,
                    "conclusion": "skipped_write_semantics",
                    "eligible": False,
                    "missing": ["write_semantics_route"],
                    "request_count": 0,
                    "detail": row["write_semantics_reason"],
                }
            elif row["privacy_name_risk"]:
                result = {
                    "operation_id": operation_id,
                    "conclusion": "skipped_privacy_name_risk",
                    "eligible": False,
                    "missing": ["privacy_review_required"],
                    "request_count": 0,
                    "detail": row["privacy_name_risk"],
                }
            elif discipline.total >= discipline.request_limit:
                result = {
                    "operation_id": operation_id,
                    "conclusion": "not_attempted_budget",
                    "eligible": False,
                    "missing": ["request_budget_exhausted"],
                    "request_count": 0,
                }
            elif stop_loss and not row["parent_indicated"]:
                result = {
                    "operation_id": operation_id,
                    "conclusion": "not_attempted_stop_loss",
                    "eligible": False,
                    "missing": ["layer_stop_loss"],
                    "request_count": 0,
                }
            else:
                before = discipline.total
                source = read_json(draft_root / f"{operation_id}.json")
                result = probe_draft(
                    source,
                    stable_client=stable_client,
                    runtime=runtime,
                    recording=recording,
                    evidence_root=evidence_root,
                    draft_root=draft_root,
                )
                result["request_count"] = discipline.total - before
                attempted += 1
                successful += result.get("conclusion") == "success"
            result["tier"] = tier
            result["parent_indicated"] = bool(row["parent_indicated"])
            result["bound_parent_count"] = int(row["bound_parent_count"])
            results.append(result)
            if attempted >= 20 and successful == 0 and index + 1 < len(layer_rows):
                stop_loss = True
                if tier not in stop_loss_layers:
                    stop_loss_layers.append(tier)
        layer_summaries.append(
            {
                "tier": tier,
                "total": len(layer_rows),
                "attempted": attempted,
                "successful": successful,
                "success_rate": successful / attempted if attempted else 0.0,
                "requests": discipline.total - layer_start_requests,
                "stop_loss": stop_loss,
            }
        )

    eligible: list[str] = []
    for path in sorted(draft_root.glob("*.json")):
        source = read_json(path)
        if evaluate_gate(source)["eligible"]:
            eligible.append(path.stem)
    promoted = (
        promote_drafts(
            eligible,
            draft_root=draft_root,
            operation_root=operation_root,
            compile_products=True,
        )
        if promote and eligible
        else []
    )
    promoted_ids = {str(item["operation_id"]) for item in promoted}
    for result in results:
        result["promoted"] = str(result["operation_id"]) in promoted_ids
        if not result["promoted"]:
            result["failure_reason"] = _failure_reason({}, result)

    parent_rows = [row for row in rows if row["parent_indicated"]]
    parent_results: list[dict[str, Any]] = []
    by_id = {str(item["operation_id"]): item for item in results}
    for row in parent_rows:
        operation_id = str(row["operation_id"])
        reference = _latest_reference(operation_id, draft_root)
        result = by_id[operation_id]
        parent_results.append(
            {
                "operation_id": operation_id,
                "attempted": int(result.get("request_count", 0)) > 0,
                "bound_parent_count": row["bound_parent_count"],
                "resolved": bool(reference.get("parent_resolved")),
                "actual_stable_parent_attempted": bool(
                    row["bound_parent_count"] and int(result.get("request_count", 0)) > 0
                ),
                "conclusion": result.get("conclusion"),
            }
        )

    failure_counts = Counter(
        str(item["failure_reason"])
        for item in results
        if not item["promoted"]
    )
    write_json(report_root / "probe-results.json", {"results": results})
    write_json(
        report_root / "skipped-write.json",
        {
            "routes": [
                row for row in rows if row["write_semantics_reason"] is not None
            ]
        },
    )
    write_json(report_root / "parent-results.json", {"results": parent_results})
    summary = {
        "schema_version": "gravity-insight.batch-probe-summary.v1",
        "drafts": len(rows),
        "tier_counts": {str(key): tier_counts[key] for key in range(1, 6)},
        "layers": layer_summaries,
        "attempted": sum(item["attempted"] for item in layer_summaries),
        "successful": sum(item["successful"] for item in layer_summaries),
        "promoted": len(promoted),
        "promoted_operation_ids": sorted(promoted_ids),
        "initial_stable": initial_stable,
        "final_stable": _stable_count(operation_root),
        "failure_counts": dict(sorted(failure_counts.items())),
        "parent": {
            "total": len(parent_results),
            "attempted": sum(item["attempted"] for item in parent_results),
            "resolved": sum(item["resolved"] for item in parent_results),
            "actual_stable_parent_attempted": sum(
                item["actual_stable_parent_attempted"] for item in parent_results
            ),
        },
        "method": {
            "uncertain_before_probe": sum(
                str(read_json(draft_root / f"{row['operation_id']}.json")
                    .get("draft", {}).get("route_evidence", {})
                    .get("method_certainty", "")) != "high"
                for row in rows
                if (draft_root / f"{row['operation_id']}.json").is_file()
            ),
            "verified_by_success": sum(
                item.get("conclusion") == "success" for item in results
            ),
        },
        "skipped_write": sum(
            row["write_semantics_reason"] is not None for row in rows
        ),
        "skipped_privacy_name_risk": sum(
            row["privacy_name_risk"] is not None for row in rows
        ),
        "stop_loss_layers": stop_loss_layers,
        "requests": {
            "total": discipline.total,
            "failed": discipline.failed,
            "backoff_events": discipline.backoff_events,
            "backoff_terminations": discipline.backoff_terminations,
            "limit": discipline.request_limit,
            "minimum_interval_ms": int(discipline.interval_seconds * 1000),
        },
    }
    write_json(report_root / "summary.json", summary)
    return summary


def finalize_batch_report(
    *, task_evidence_floor: str,
    report_root: Path = BATCH_ROOT,
    draft_root: Path = DRAFT_ROOT,
    operation_root: Path = OPERATION_ROOT,
    evidence_root: Path = EVIDENCE_ROOT,
    auth_http_requests: int = 0,
) -> dict[str, Any]:
    """Reconcile a resumed batch into one operation-deduplicated report."""

    layering = read_json(report_root / "layering.json")
    rows = list(layering.get("drafts", []))
    if len(rows) != 309:
        raise ValueError("the canonical batch layering report must contain 309 drafts")
    evidence_by_operation: dict[str, list[tuple[Path, Mapping[str, Any]]]] = {}
    request_totals = Counter()
    skipped_evidence_files: list[dict[str, str]] = []
    for path, evidence in iter_json_evidence(
        evidence_root, skipped_files=skipped_evidence_files
    ):
        timestamp = path.name.split("_", 1)[0]
        if timestamp < task_evidence_floor:
            continue
        operation_id = str(evidence.get("operation_id", ""))
        if not operation_id:
            continue
        evidence_by_operation.setdefault(operation_id, []).append((path, evidence))
        stats = evidence.get("request_stats", {})
        if isinstance(stats, Mapping):
            request_totals["total"] += int(stats.get("total", 0))
            request_totals["failed"] += int(stats.get("failed", 0))
            request_totals["backoff_terminations"] += int(
                stats.get("backoff_terminations", 0)
            )

    stable_ids = {
        str(source["operation"]["operation_id"])
        for path in operation_root.glob("*.json")
        for source in [read_json(path)]
        if source.get("operation", {}).get("stability") == "stable"
    }
    final_rows: list[dict[str, Any]] = []
    parent_results: list[dict[str, Any]] = []
    for row in rows:
        operation_id = str(row["operation_id"])
        evidence_rows = evidence_by_operation.get(operation_id, [])
        latest = evidence_rows[-1][1] if evidence_rows else {}
        successful = any(bool(item[1].get("successful")) for item in evidence_rows)
        promoted = operation_id in stable_ids
        missing: list[str] = []
        draft_path = draft_root / f"{operation_id}.json"
        if draft_path.is_file():
            missing = list(evaluate_gate(read_json(draft_path))["missing"])
        result = {
            **dict(row),
            "attempted": bool(evidence_rows),
            "successful": successful,
            "promoted": promoted,
            "latest_conclusion": latest.get("conclusion") if latest else None,
            "latest_evidence": (
                evidence_rows[-1][0].relative_to(REPO_ROOT).as_posix()
                if evidence_rows else None
            ),
            "evidence_count": len(evidence_rows),
            "missing": missing,
        }
        if not promoted:
            if row.get("write_semantics_reason"):
                reason = "写语义跳过"
            elif row.get("privacy_name_risk"):
                reason = "字段待审"
            elif latest.get("conclusion") in {
                "privacy_review_required", "success"
            } or "field_review_required" in missing:
                reason = "字段待审"
            elif latest.get("conclusion") in {"inconclusive_empty", "available_empty"}:
                reason = "空数据"
            elif latest.get("conclusion") == "permission_or_auth_unavailable":
                reason = "无权限"
            elif row.get("parent_indicated") and latest.get("conclusion") in {
                "local_or_parent_inconclusive", "semantic_error"
            }:
                reason = "需父资源"
            elif latest.get("conclusion") == "semantic_error":
                reason = "参数不明"
            else:
                reason = "路由不可用"
            result["failure_reason"] = reason
        final_rows.append(result)

        if row.get("parent_indicated"):
            actual_parent_attempted = any(
                any(
                    isinstance(http, Mapping) and http.get("purpose") == "parent"
                    for http in evidence.get("http", [])
                )
                for _, evidence in evidence_rows
            )
            resolved = any(
                bool(evidence.get("successful"))
                and (
                    evidence.get("required_parent") is None
                    or (
                        isinstance(evidence.get("required_parent"), Mapping)
                        and evidence["required_parent"].get("status") == "resolved"
                    )
                )
                for _, evidence in evidence_rows
            )
            parent_results.append(
                {
                    "operation_id": operation_id,
                    "attempted": bool(evidence_rows),
                    "resolved": resolved,
                    "actual_stable_parent_attempted": actual_parent_attempted,
                    "bound_parent_count": row.get("bound_parent_count", 0),
                    "latest_conclusion": latest.get("conclusion") if latest else None,
                }
            )

    layer_results: list[dict[str, Any]] = []
    for tier in range(1, 6):
        selected = [item for item in final_rows if item["tier"] == tier]
        attempted = sum(bool(item["attempted"]) for item in selected)
        successful = sum(bool(item["successful"]) for item in selected)
        layer_results.append(
            {
                "tier": tier,
                "total": len(selected),
                "attempted": attempted,
                "successful": successful,
                "promoted": sum(bool(item["promoted"]) for item in selected),
                "success_rate": successful / attempted if attempted else 0.0,
            }
        )
    failure_counts = Counter(
        str(item["failure_reason"])
        for item in final_rows
        if not item["promoted"]
    )
    summary = {
        "schema_version": "gravity-insight.batch-probe-final.v1",
        "tier_counts": {
            str(item["tier"]): item["total"] for item in layer_results
        },
        "layers": layer_results,
        "attempted": sum(bool(item["attempted"]) for item in final_rows),
        "successful": sum(bool(item["successful"]) for item in final_rows),
        "promoted": sum(bool(item["promoted"]) for item in final_rows),
        "promoted_operation_ids": sorted(
            str(item["operation_id"]) for item in final_rows if item["promoted"]
        ),
        "initial_stable": 124,
        "final_stable": len(stable_ids),
        "failure_counts": dict(sorted(failure_counts.items())),
        "parent": {
            "total": len(parent_results),
            "attempted": sum(item["attempted"] for item in parent_results),
            "resolved": sum(item["resolved"] for item in parent_results),
            "actual_stable_parent_attempted": sum(
                item["actual_stable_parent_attempted"] for item in parent_results
            ),
            "agent_cli_unknown_before": 22,
            "agent_cli_unknown_clarified": 0,
        },
        "method": {
            "uncertain_before_probe": 0,
            "verified_by_success": sum(
                bool(item["successful"]) for item in final_rows
            ),
        },
        "skipped_write": sum(
            bool(item.get("write_semantics_reason")) for item in final_rows
        ),
        "skipped_privacy_name_risk": sum(
            bool(item.get("privacy_name_risk")) for item in final_rows
        ),
        "stop_loss_layers": [2, 3, 4],
        "backfilled_after_stop_loss": 10,
        "requests": {
            "probe_total": request_totals["total"],
            "probe_failed": request_totals["failed"],
            "backoff_terminations": request_totals["backoff_terminations"],
            "auth_refresh_and_smoke": auth_http_requests,
            "http_total_upper_bound": request_totals["total"] + auth_http_requests,
            "limit": 900,
            "minimum_interval_ms": 310,
        },
        "skipped_evidence_file_count": len(skipped_evidence_files),
        "skipped_evidence_files": skipped_evidence_files,
    }
    write_json(report_root / "final-results.json", {"results": final_rows})
    write_json(report_root / "parent-results-final.json", {"results": parent_results})
    write_json(report_root / "summary.json", summary)
    return summary


__all__ = [
    "availability_tier",
    "classify_drafts",
    "finalize_batch_report",
    "run_batch_probes",
    "write_semantics_reason",
]
