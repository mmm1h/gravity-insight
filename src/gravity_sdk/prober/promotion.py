"""Probe evidence application, promotion gates, and pipeline status."""

from __future__ import annotations

import copy
import hashlib
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Mapping, Sequence

from .core import (
    DRAFT_ROOT,
    EVIDENCE_ROOT,
    OPERATION_ROOT,
    REPO_ROOT,
    canonical_fingerprint,
    display_path,
    iter_json_evidence,
    now_utc,
    read_json,
    write_json,
)
from .drafts import existing_operations, refresh_structured_blockers, validate_source
from .privacy import (
    build_projection,
    candidate_fields,
    projection_exposes_path,
    response_schema_sketch,
)
from .probe_support import evidence_path, privacy_summary
from .promotion_normalization import complete_privacy_redactions
from .promotion_transaction import compile_contract_products, promote_atomically


def _placeholder_supported(value: Any) -> bool:
    supported = {
        "$today", "$yesterday", "$analysis_query_id", "$first_app_id",
        "$first_event_name", "$first_user_property_name",
        "$first_event_property_name", "$first_segment_id",
        "$first_report_config_id", "$first_dashboard_id",
        "$first_dashboard_space_id", "$first_client_id",
        "$first_bytedance_advertiser_id", "$first_tencent_advertiser_id",
        "$first_kuaishou_advertiser_id", "$first_preset_template_id",
        "$first_preset_template_category",
    }
    if isinstance(value, str):
        return (
            not value.startswith("$")
            or value in supported
            or value.startswith("$first_order_")
            or value.startswith("$parent:")
        )
    if isinstance(value, Mapping):
        return all(_placeholder_supported(item) for item in value.values())
    if isinstance(value, list):
        return all(_placeholder_supported(item) for item in value)
    return True


def evaluate_gate(source: Mapping[str, Any]) -> dict[str, Any]:
    draft = source.get("draft") if isinstance(source, Mapping) else None
    operation = source.get("operation") if isinstance(source, Mapping) else None
    if not isinstance(draft, Mapping) or not isinstance(operation, Mapping):
        return {"eligible": False, "missing": ["draft_metadata"]}
    evidence = draft.get("probe_evidence")
    latest = evidence[-1] if isinstance(evidence, list) and evidence else {}
    missing: list[str] = []
    if not isinstance(latest, Mapping) or not bool(latest.get("successful")):
        missing.append("successful_probe")
    projection = operation.get("response_projection")
    exposed = 0
    if isinstance(projection, Mapping):
        exposed += len(projection.get("item_keys", []))
        exposed += len(set(projection.get("data_keys", [])) - {"list", "page_info"})
        exposed += len(projection.get("data_scalar_list_types", {}))
    if exposed == 0:
        missing.append("response_projection")
    candidates = draft.get("candidate_fields")
    if not isinstance(candidates, list):
        missing.append("privacy_classification")
    else:
        manual_review = [
            str(item.get("path"))
            for item in candidates
            if isinstance(item, Mapping)
            and item.get("privacy_classification") == "manual_review"
        ]
        if manual_review:
            missing.append("field_review_required")
        unsafe_exposed = [
            str(item.get("path")) for item in candidates
            if isinstance(item, Mapping)
            and item.get("privacy_classification") != "non_sensitive"
            and isinstance(projection, Mapping)
            and projection_exposes_path(str(item.get("path", "")), projection)
        ]
        if unsafe_exposed:
            missing.append("unclassified_or_sensitive_field_exposed")
    pagination = operation.get("pagination")
    if (
        isinstance(pagination, Mapping) and pagination.get("kind") != "none"
        and not bool(latest.get("pagination_verified"))
    ):
        missing.append("pagination_unverified")
    live_probe = operation.get("live_probe")
    live_inputs = live_probe.get("inputs") if isinstance(live_probe, Mapping) else None
    if not _placeholder_supported(live_inputs):
        missing.append("runtime_probe_placeholder_unsupported")
    blockers = draft.get("blockers")
    if isinstance(blockers, list):
        missing.extend(
            str(item.get("code"))
            for item in blockers
            if isinstance(item, Mapping) and item.get("code") != "promotion_pending"
        )
    if str(operation.get("path_template", "")).startswith("/openapi/"):
        missing.append("stable_runtime_route_unsupported")
    if operation.get("auth_profile") == "gravity_openapi_signature":
        missing.append("openapi_developer_credentials_unavailable")
    return {"eligible": not missing, "missing": sorted(set(missing))}


def update_draft_from_probe(
    source: Mapping[str, Any], *, payload: Mapping[str, Any],
    evidence_reference: Mapping[str, Any], pagination: Mapping[str, Any],
) -> dict[str, Any]:
    updated = copy.deepcopy(dict(source))
    sketch = response_schema_sketch(payload)
    fields = candidate_fields(
        sketch, operation_id=str(source["operation"]["operation_id"])
    )
    operation = updated["operation"]
    operation["response_projection"] = build_projection(payload, fields)
    operation["pagination"] = dict(pagination)
    draft = updated["draft"]
    draft["candidate_fields"] = fields
    draft["manual_review_fields"] = sorted(
        str(item["path"]) for item in fields
        if item["privacy_classification"] == "manual_review"
    )
    draft["probe_evidence"] = list(draft.get("probe_evidence", [])) + [dict(evidence_reference)]
    updated = refresh_structured_blockers(updated, draft.get("route_evidence"))
    draft = updated["draft"]
    draft["promotion_gate"] = evaluate_gate(updated)
    validate_source(updated)
    return updated


def save_draft(source: Mapping[str, Any], draft_root: Path = DRAFT_ROOT) -> Path:
    validate_source(source)
    operation_id = str(source["operation"]["operation_id"])
    path = draft_root / f"{operation_id}.json"
    write_json(path, source)
    return path


def _next_manifest_order(target_manifest: str, operation_root: Path) -> int:
    orders: list[int] = []
    for source in existing_operations(operation_root).values():
        if source.get("target_manifest") == target_manifest:
            try:
                orders.append(int(source.get("manifest_order", 0)))
            except (TypeError, ValueError):
                pass
    return max(orders, default=-1) + 1


def _runnable_example_inputs(value: Any) -> Any | None:
    if value == "$today":
        return date.today().isoformat()
    if value == "$yesterday":
        return (date.today() - timedelta(days=1)).isoformat()
    if isinstance(value, str) and value.startswith("$"):
        return None
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            resolved = _runnable_example_inputs(item)
            if resolved is None:
                return None
            result[str(key)] = resolved
        return result
    if isinstance(value, list):
        result = []
        for item in value:
            resolved = _runnable_example_inputs(item)
            if resolved is None:
                return None
            result.append(resolved)
        return result
    return copy.deepcopy(value)


def _stable_source(source: Mapping[str, Any], operation_root: Path) -> dict[str, Any]:
    stable = copy.deepcopy(dict(source))
    stable.pop("draft", None)
    stable["manifest_order"] = _next_manifest_order(stable["target_manifest"], operation_root)
    operation = stable["operation"]
    operation["stability"] = "stable"
    operation["executable"] = True
    operation.pop("block_reason", None)
    if not operation.get("semantic_error_rules"):
        operation["semantic_error_rules"] = ["code", "extra.error"]
    operation["live_probe"]["enabled"] = True
    inputs = operation["live_probe"].get("inputs", {})
    if operation.get("pagination", {}).get("kind") == "page_info":
        pagination = operation["pagination"]
        page_field = str(pagination["page_field"])
        page_size_field = str(pagination["page_size_field"])
        default_page_size = int(pagination["default_page_size"])
        operation["input_fields"].setdefault(page_field, {"type": "integer"})
        operation["input_fields"].setdefault(page_size_field, {"type": "integer"})
        operation["input_fields"][page_field]["default"] = 1
        operation["input_fields"][page_size_field]["default"] = default_page_size
        operation["request"]["defaults"][page_field] = 1
        operation["request"]["defaults"][page_size_field] = default_page_size
        inputs[page_field] = 1
        inputs[page_size_field] = 1
    example_inputs = _runnable_example_inputs(inputs)
    if example_inputs is not None:
        operation["examples"] = [
            {
                "name": "minimum_read",
                "description": "Minimum input verified by the contract probe pipeline.",
                "inputs": example_inputs,
            }
        ]
    operation["provenance"] = {
        "source_files": [f"operations/{operation['operation_id']}.json"],
        "family": None,
        "platform": operation.get("platform"),
        "applied_overrides": [],
    }
    complete_privacy_redactions(operation)
    validate_source(stable)
    return stable


def normalize_promoted_contracts(
    operation_ids: Sequence[str], *, operation_root: Path = OPERATION_ROOT,
    compile_products: bool = True,
) -> list[str]:
    """Apply stable decision-completeness rules to already promoted sources."""

    normalized: list[str] = []
    for operation_id in operation_ids:
        path = operation_root / f"{operation_id}.json"
        source = read_json(path)
        if source.get("target_manifest") == "material.json":
            source["target_manifest"] = "other.json"
            source["manifest_order"] = _next_manifest_order("other.json", operation_root)
        operation = source["operation"]
        if not operation.get("semantic_error_rules"):
            operation["semantic_error_rules"] = ["code", "extra.error"]
        inputs = operation["live_probe"]["inputs"]
        if operation.get("pagination", {}).get("kind") == "page_info":
            pagination = operation["pagination"]
            page_field = str(pagination["page_field"])
            page_size_field = str(pagination["page_size_field"])
            default_page_size = int(pagination["default_page_size"])
            operation["input_fields"].setdefault(page_field, {"type": "integer"})
            operation["input_fields"].setdefault(page_size_field, {"type": "integer"})
            operation["input_fields"][page_field]["default"] = 1
            operation["input_fields"][page_size_field]["default"] = default_page_size
            operation["request"]["defaults"][page_field] = 1
            operation["request"]["defaults"][page_size_field] = default_page_size
            inputs[page_field] = 1
            inputs[page_size_field] = 1
        example_inputs = _runnable_example_inputs(inputs)
        if example_inputs is not None:
            operation["examples"] = [
                {
                    "name": "minimum_read",
                    "description": (
                        "Minimum input verified by the contract probe pipeline."
                    ),
                    "inputs": example_inputs,
                }
            ]
        validate_source(source)
        write_json(path, source)
        normalized.append(operation_id)
    if compile_products and normalized:
        compile_contract_products()
    return normalized


def promote_drafts(
    operation_ids: Sequence[str], *, draft_root: Path = DRAFT_ROOT,
    operation_root: Path = OPERATION_ROOT, compile_products: bool = True,
) -> list[dict[str, Any]]:
    return promote_atomically(
        operation_ids,
        draft_root=draft_root,
        operation_root=operation_root,
        compile_products=compile_products,
        evaluate_gate=evaluate_gate,
        stable_source=_stable_source,
    )


def _resolve_evidence_reference(reference: str, evidence_root: Path) -> Path:
    root = evidence_root.resolve()
    raw = Path(reference)
    candidates = [raw] if raw.is_absolute() else [REPO_ROOT / raw, root / raw.name]
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved.is_file() and resolved.is_relative_to(root):
            return resolved
    raise ValueError(f"probe evidence is outside the configured evidence root: {reference}")


def _display_evidence_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return resolved.as_posix()


def _stable_operation_count(operation_root: Path) -> int:
    return sum(
        source.get("operation", {}).get("stability") == "stable"
        for source in existing_operations(operation_root).values()
    )


def _observed_pagination(evidence: Mapping[str, Any]) -> bool:
    observations = evidence.get("http", [])
    if not isinstance(observations, list):
        return False
    for observation in observations:
        if not isinstance(observation, Mapping):
            continue
        sketch = observation.get("response_schema_sketch")
        paths = sketch.get("paths", []) if isinstance(sketch, Mapping) else []
        path_names = {
            str(item.get("path")) for item in paths if isinstance(item, Mapping)
        } if isinstance(paths, list) else set()
        if {
            "$.data.list",
            "$.data.page_info",
            "$.data.page_info.page",
            "$.data.page_info.page_size",
        }.issubset(path_names):
            return True
    return False


def _legacy_privacy_evidence_reusable(
    source: Mapping[str, Any], evidence: Mapping[str, Any]
) -> tuple[bool, list[str]]:
    operation = source.get("operation", {})
    draft = source.get("draft", {})
    operation_id = str(operation.get("operation_id", ""))
    reasons: list[str] = []
    if evidence.get("conclusion") != "privacy_review_required":
        reasons.append("not_legacy_privacy_short_circuit")
    if str(evidence.get("operation_id", "")) != operation_id:
        reasons.append("operation_id_mismatch")

    fields = draft.get("candidate_fields", [])
    if not isinstance(fields, list):
        reasons.append("candidate_fields_missing")
        fields = []
    sensitive = [
        item for item in fields
        if isinstance(item, Mapping)
        and item.get("privacy_classification") == "sensitive"
    ]
    manual = [
        item for item in fields
        if isinstance(item, Mapping)
        and item.get("privacy_classification") == "manual_review"
    ]
    if not sensitive:
        reasons.append("no_sensitive_fields")
    if manual:
        reasons.append("manual_review_required")
    projection = operation.get("response_projection", {})
    if not isinstance(projection, Mapping) or any(
        projection_exposes_path(str(item.get("path", "")), projection)
        for item in sensitive
    ):
        reasons.append("sensitive_field_exposed")

    observations = evidence.get("http", [])
    discovery = [
        item for item in observations
        if isinstance(item, Mapping)
        and item.get("operation_id") == operation_id
        and item.get("purpose") == "discovery"
    ] if isinstance(observations, list) else []
    primary = discovery[-1] if discovery else None
    status = primary.get("http_status") if isinstance(primary, Mapping) else None
    if not isinstance(status, int) or not 200 <= status < 300:
        reasons.append("successful_http_discovery_unproven")
    sketch = primary.get("response_schema_sketch") if isinstance(primary, Mapping) else None
    paths = sketch.get("paths", []) if isinstance(sketch, Mapping) else []
    path_names = {
        str(item.get("path")) for item in paths if isinstance(item, Mapping)
    } if isinstance(paths, list) else set()
    if not any(
        path.startswith("$.data.") or path.startswith("$.data[]")
        for path in path_names
    ):
        reasons.append("nonempty_data_shape_unproven")
    fingerprint = evidence.get("raw_schema_fingerprint")
    if not isinstance(sketch, Mapping) or fingerprint != canonical_fingerprint(sketch):
        reasons.append("raw_schema_fingerprint_mismatch")
    request_stats = evidence.get("request_stats", {})
    if not isinstance(request_stats, Mapping) or int(request_stats.get("failed", 0)) != 0:
        reasons.append("failed_request_observed")
    return not reasons, sorted(set(reasons))


def _reevaluation_document(
    source: Mapping[str, Any], source_evidence: Mapping[str, Any], *,
    source_path: Path, fields: Sequence[Mapping[str, Any]], reevaluated_at: str,
) -> dict[str, Any]:
    operation = source["operation"]
    projection = operation["response_projection"]
    pagination_observed = _observed_pagination(source_evidence)
    return {
        "schema_version": "gravity-insight.probe-semantic-reevaluation.v1",
        "operation_id": operation["operation_id"],
        "route": {
            "method": operation["upstream_method"],
            "path": operation["path_template"],
            "family": source_evidence.get("route", {}).get("family"),
        },
        "probed_at": source_evidence.get("probed_at"),
        "reevaluated_at": reevaluated_at,
        "conclusion": "success",
        "successful": True,
        "offline_reevaluation": True,
        "source_evidence": {
            "path": _display_evidence_path(source_path),
            "sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
            "conclusion": source_evidence.get("conclusion"),
        },
        "semantic_basis": {
            "legacy_branch": "sensitive_field_short_circuit",
            "http_discovery_2xx": True,
            "nonempty_data_shape_observed": True,
            "manual_review_fields": 0,
            "sensitive_fields_hidden_by_projection": True,
            "pagination_observed_but_unverified": pagination_observed,
        },
        "http": [],
        "raw_schema_fingerprint": source_evidence.get("raw_schema_fingerprint"),
        "projected_schema_fingerprint": canonical_fingerprint(projection),
        "pagination": {
            "kind": "unverified" if pagination_observed else "none",
            "verified": not pagination_observed,
        },
        "semantic_errors": source_evidence.get("semantic_errors", {}),
        "required_parent": source_evidence.get("required_parent"),
        "privacy": privacy_summary(fields),
        "request_stats": {
            "total": 0,
            "failed": 0,
            "backoff_terminations": 0,
        },
    }


def reevaluate_drafts(
    *, draft_root: Path = DRAFT_ROOT, operation_root: Path = OPERATION_ROOT,
    evidence_root: Path = EVIDENCE_ROOT, promote: bool = True,
    compile_products: bool = True,
) -> dict[str, Any]:
    """Re-evaluate legacy privacy-short-circuit evidence without network access."""

    draft_paths = sorted(draft_root.glob("*.json")) if draft_root.is_dir() else []
    stable_before = _stable_operation_count(operation_root)
    reevaluated: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    manual_review_blocked = 0
    for draft_path in draft_paths:
        source = read_json(draft_path)
        draft = source.get("draft", {})
        fields = draft.get("candidate_fields", []) if isinstance(draft, Mapping) else []
        if isinstance(fields, list) and any(
            isinstance(item, Mapping)
            and item.get("privacy_classification") == "manual_review"
            for item in fields
        ):
            manual_review_blocked += 1
        references = draft.get("probe_evidence", []) if isinstance(draft, Mapping) else []
        latest = references[-1] if isinstance(references, list) and references else None
        if not isinstance(latest, Mapping) or latest.get("conclusion") != "privacy_review_required":
            continue
        source_path = _resolve_evidence_reference(str(latest.get("path", "")), evidence_root)
        source_evidence = read_json(source_path)
        reusable, reasons = _legacy_privacy_evidence_reusable(source, source_evidence)
        operation_id = str(source["operation"]["operation_id"])
        if not reusable:
            rejected.append({"operation_id": operation_id, "reasons": reasons})
            continue

        reevaluated_at = now_utc()
        if _observed_pagination(source_evidence):
            source["operation"]["pagination"] = {
                "kind": "unverified",
                "page_field": "",
                "page_size_field": "",
                "list_path": "",
                "page_info_path": "",
                "total_page_field": "",
            }
        derived_path = evidence_path(operation_id, evidence_root)
        document = _reevaluation_document(
            source,
            source_evidence,
            source_path=source_path,
            fields=fields,
            reevaluated_at=reevaluated_at,
        )
        write_json(derived_path, document)
        reference = {
            "path": _display_evidence_path(derived_path),
            "probed_at": str(source_evidence.get("probed_at") or reevaluated_at),
            "conclusion": "success",
            "successful": True,
            "pagination_verified": bool(document["pagination"]["verified"]),
            "parent_resolved": not bool(source["operation"].get("required_parent")),
            "method_verified": True,
            "raw_schema_fingerprint": source_evidence.get("raw_schema_fingerprint"),
            "projected_schema_fingerprint": document["projected_schema_fingerprint"],
        }
        source["draft"]["probe_evidence"] = [*references, reference]
        source = refresh_structured_blockers(source, source["draft"].get("route_evidence"))
        source["draft"]["promotion_gate"] = evaluate_gate(source)
        save_draft(source, draft_root)
        reevaluated.append(
            {
                "operation_id": operation_id,
                "eligible": bool(source["draft"]["promotion_gate"]["eligible"]),
                "missing": list(source["draft"]["promotion_gate"]["missing"]),
                "source_evidence": _display_evidence_path(source_path),
                "derived_evidence": _display_evidence_path(derived_path),
            }
        )

    eligible_ids = [item["operation_id"] for item in reevaluated if item["eligible"]]
    promoted = promote_drafts(
        eligible_ids,
        draft_root=draft_root,
        operation_root=operation_root,
        compile_products=False,
    ) if promote and eligible_ids else []
    if compile_products and promoted:
        from gravity_sdk.compiler import ContractCompiler

        ContractCompiler().compile()
    stable_after = _stable_operation_count(operation_root)
    return {
        "schema_version": "gravity-insight.probe-semantic-reevaluation.v1",
        "ok": True,
        "status": "success",
        "network_called": False,
        "drafts_examined": len(draft_paths),
        "legacy_privacy_evidence": len(reevaluated) + len(rejected),
        "reevaluated": reevaluated,
        "rejected": rejected,
        "manual_review_blocked": manual_review_blocked,
        "promoted": promoted,
        "promoted_operation_ids": [item["operation_id"] for item in promoted],
        "stable_before": stable_before,
        "stable_after": stable_after,
    }


def _evidence_stats(evidence_root: Path) -> dict[str, Any]:
    skipped_files: list[dict[str, str]] = []
    evidence_documents = list(
        iter_json_evidence(evidence_root, skipped_files=skipped_files)
    )
    totals: dict[str, Any] = {
        "files": len(evidence_documents),
        "skipped_file_count": len(skipped_files),
        "skipped_files": skipped_files,
        "request_total": 0,
        "failed_total": 0,
        "backoff_terminations": 0,
    }
    for _, evidence in evidence_documents:
        stats = evidence.get("request_stats") if isinstance(evidence, Mapping) else None
        if isinstance(stats, Mapping):
            totals["request_total"] += int(stats.get("total", 0))
            totals["failed_total"] += int(stats.get("failed", 0))
            totals["backoff_terminations"] += int(stats.get("backoff_terminations", 0))
    return totals


def status_report(
    operation_ids: Sequence[str] = (), *, draft_root: Path = DRAFT_ROOT,
    operation_root: Path = OPERATION_ROOT, evidence_root: Path = EVIDENCE_ROOT,
) -> dict[str, Any]:
    requested = set(operation_ids)
    rows: list[dict[str, Any]] = []
    for path in sorted(draft_root.glob("*.json")) if draft_root.is_dir() else []:
        if requested and path.stem not in requested:
            continue
        source = read_json(path)
        gate = evaluate_gate(source)
        rows.append(
            {
                "operation_id": path.stem, "status": "draft", "eligible": gate["eligible"],
                "missing": gate["missing"],
                "probe_count": len(source.get("draft", {}).get("probe_evidence", [])),
            }
        )
    stable = existing_operations(operation_root)
    for operation_id in sorted(requested):
        if operation_id in stable and not any(row["operation_id"] == operation_id for row in rows):
            rows.append(
                {"operation_id": operation_id, "status": "stable", "eligible": True,
                 "missing": [], "probe_count": 0}
            )
    return {
        "schema_version": "gravity-insight.prober-status.v1", "ok": True,
        "status": "success", "count": len(rows),
        "operations": sorted(rows, key=lambda item: item["operation_id"]),
        "evidence": _evidence_stats(evidence_root),
    }
