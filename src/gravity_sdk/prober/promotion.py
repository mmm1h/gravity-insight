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
from .promotion_normalization import (
    complete_privacy_redactions,
    evaluate_gate as _evaluate_gate,
    legacy_privacy_evidence_reusable as _legacy_privacy_evidence_reusable_impl,
)
from .promotion_transaction import compile_contract_products, promote_atomically


def evaluate_gate(source: Mapping[str, Any]) -> dict[str, Any]:
    return _evaluate_gate(source, projection_exposes_path)


def _legacy_privacy_evidence_reusable(
    source: Mapping[str, Any], evidence: Mapping[str, Any]
) -> tuple[bool, list[str]]:
    return _legacy_privacy_evidence_reusable_impl(
        source, evidence, projection_exposes_path, canonical_fingerprint
    )


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


def _manual_review_present(fields: Any) -> bool:
    return isinstance(fields, list) and any(
        isinstance(item, Mapping)
        and item.get("privacy_classification") == "manual_review"
        for item in fields
    )


def _legacy_reference(draft: Mapping[str, Any]) -> Mapping[str, Any] | None:
    references = draft.get("probe_evidence", [])
    latest = references[-1] if isinstance(references, list) and references else None
    if isinstance(latest, Mapping) and latest.get("conclusion") == "privacy_review_required":
        return latest
    return None


def _reevaluate_draft(
    draft_path: Path, *, draft_root: Path, evidence_root: Path,
) -> tuple[bool, dict[str, Any] | None, dict[str, Any] | None]:
    source = read_json(draft_path)
    draft = source.get("draft", {})
    fields = draft.get("candidate_fields", []) if isinstance(draft, Mapping) else []
    manual_review = _manual_review_present(fields)
    latest = _legacy_reference(draft) if isinstance(draft, Mapping) else None
    if latest is None:
        return manual_review, None, None
    source_path = _resolve_evidence_reference(str(latest.get("path", "")), evidence_root)
    source_evidence = read_json(source_path)
    reusable, reasons = _legacy_privacy_evidence_reusable(source, source_evidence)
    operation_id = str(source["operation"]["operation_id"])
    if not reusable:
        return manual_review, None, {"operation_id": operation_id, "reasons": reasons}

    reevaluated_at = now_utc()
    if _observed_pagination(source_evidence):
        source["operation"]["pagination"] = {
            "kind": "unverified", "page_field": "", "page_size_field": "",
            "list_path": "", "page_info_path": "", "total_page_field": "",
        }
    derived_path = evidence_path(operation_id, evidence_root)
    document = _reevaluation_document(
        source, source_evidence, source_path=source_path, fields=fields,
        reevaluated_at=reevaluated_at,
    )
    write_json(derived_path, document)
    reference = {
        "path": _display_evidence_path(derived_path),
        "probed_at": str(source_evidence.get("probed_at") or reevaluated_at),
        "conclusion": "success", "successful": True,
        "pagination_verified": bool(document["pagination"]["verified"]),
        "parent_resolved": not bool(source["operation"].get("required_parent")),
        "method_verified": True,
        "raw_schema_fingerprint": source_evidence.get("raw_schema_fingerprint"),
        "projected_schema_fingerprint": document["projected_schema_fingerprint"],
    }
    references = draft.get("probe_evidence", [])
    source["draft"]["probe_evidence"] = [*references, reference]
    source = refresh_structured_blockers(source, source["draft"].get("route_evidence"))
    source["draft"]["promotion_gate"] = evaluate_gate(source)
    save_draft(source, draft_root)
    gate = source["draft"]["promotion_gate"]
    return manual_review, {
        "operation_id": operation_id,
        "eligible": bool(gate["eligible"]),
        "missing": list(gate["missing"]),
        "source_evidence": _display_evidence_path(source_path),
        "derived_evidence": _display_evidence_path(derived_path),
    }, None


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
        manual_review, accepted, rejection = _reevaluate_draft(
            draft_path, draft_root=draft_root, evidence_root=evidence_root
        )
        manual_review_blocked += int(manual_review)
        if accepted is not None:
            reevaluated.append(accepted)
        if rejection is not None:
            rejected.append(rejection)

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
