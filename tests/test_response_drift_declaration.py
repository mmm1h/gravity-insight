from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from gravity_insight.governance.stable_privacy import render_registry
from gravity_insight.prober.cli import build_parser
from gravity_insight.prober.drift_declaration import (
    PLAN_SCHEMA_VERSION,
    apply_drift_plan,
    build_drift_plan,
    write_drift_plan,
)


ROOT = Path(__file__).resolve().parents[1]
OPERATIONS = ROOT / "src/gravity_insight/contracts/operations"
ZERO_DIGEST = "0" * 64


def _drift(fields: list[tuple[str, str]]) -> dict[str, object]:
    return {
        "schema_version": "gravity.response-drift.v1",
        "direction": "response",
        "classification": "additive",
        "fields": [
            {"path": path, "observed_type": observed_type}
            for path, observed_type in fields
        ],
    }


def _outcome(selector: str, fields: list[tuple[str, str]]) -> dict[str, object]:
    return {
        "identity_kind": "operation",
        "selector": selector,
        "effect": "read",
        "attempted": True,
        "category": "response_contract_drift",
        "request_count": 1,
        "validation_recorded": False,
        "reason_codes": ["EXECUTION_RESPONSE_DRIFT"],
        "response_drift": _drift(fields),
    }


def _run(outcomes: list[dict[str, object]]) -> dict[str, object]:
    return {
        "schema_version": "gravity.capability-validation-run.v2",
        "status": "complete",
        "started_at": "2026-09-05T00:00:00Z",
        "finished_at": "2026-09-05T00:00:01Z",
        "app_scope_sha256": ZERO_DIGEST,
        "request_budget": 10,
        "prior_requests": 0,
        "production_requests_sent": len(outcomes),
        "production_requests_total": len(outcomes),
        "runtime_request_counter": len(outcomes),
        "attempts": 1,
        "candidate_operations": len(outcomes),
        "validations_recorded": 0,
        "validation_store_count": 0,
        "outcome_counts": {"response_contract_drift": len(outcomes)},
        "trust_counts": {
            "stable": 0,
            "complete": 0,
            "data_quality_pass": 0,
            "provider_matched": 0,
            "total": len(outcomes),
        },
        "outcomes": outcomes,
        "network_called": True,
        "privacy": {
            "credentials_persisted": False,
            "request_values_persisted": False,
            "response_values_persisted": False,
            "raw_rows_persisted": False,
        },
    }


def _write_json(path: Path, value: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    return path


def _decisions(plan: dict[str, object]) -> dict[tuple[str, str], dict[str, object]]:
    return {
        (operation["operation_id"], decision["path"]): decision
        for operation in plan["operations"]
        for decision in operation["decisions"]
    }


def _temporary_operation_root(
    tmp_path: Path,
    *operation_ids: str,
    remove_fields: dict[str, dict[str, set[str]]] | None = None,
) -> Path:
    operation_root = tmp_path / "src/gravity_insight/contracts/operations"
    operation_root.mkdir(parents=True)
    for operation_id in operation_ids:
        source = OPERATIONS / f"{operation_id}.json"
        document = json.loads(source.read_text(encoding="utf-8"))
        projection = document["operation"]["response_projection"]
        for field, removed in (remove_fields or {}).get(operation_id, {}).items():
            projection[field] = [
                value for value in projection[field] if value not in removed
            ]
        _write_json(operation_root / source.name, document)
    registry = tmp_path / "src/gravity_insight/governance/stable_privacy_registry.json"
    registry.parent.mkdir(parents=True)
    registry.write_text(render_registry(tmp_path), encoding="utf-8")
    return operation_root


def test_recovered_map_rejects_all_three_real_counterexamples(tmp_path: Path) -> None:
    operation_root = _temporary_operation_root(
        tmp_path,
        "promotion.kuaishou.account.list",
        "material.local.list",
        "analysis.segment.evaluate_percent",
        remove_fields={
            "material.local.list": {"item_keys": {"video_cover_list"}},
            "analysis.segment.evaluate_percent": {"data_keys": {"zone_offset"}},
        },
    )
    evidence = _write_json(
        tmp_path / "recovered.json",
        {
            "promotion.kuaishou.account.list": {
                "/data/list/*/access_token": "string",
            },
            "material.local.list": {
                "/data/list/*/video_cover_list": "null",
            },
            "analysis.segment.evaluate_percent": {
                "/data/zone_offset": "string",
            },
        },
    )

    plan = build_drift_plan([evidence], operation_root=operation_root)
    decisions = _decisions(plan)

    assert plan["summary"]["automatic"] == 0
    assert decisions[(
        "promotion.kuaishou.account.list", "/data/list/*/access_token"
    )]["reason"] == "credential_requires_omission"
    assert decisions[(
        "material.local.list", "/data/list/*/video_cover_list"
    )]["reason"] == "null_type_unproven"
    zone = decisions[("analysis.segment.evaluate_percent", "/data/zone_offset")]
    assert zone["reason"] == "pagination_evidence_context_changed"
    assert zone["governance_before"]["response_scalar_only"] is True
    assert zone["governance_after"]["response_scalar_only"] is False


def test_v2_runs_merge_types_and_are_order_independent(tmp_path: Path) -> None:
    first = _write_json(
        tmp_path / "first.json",
        _run([_outcome("promotion.kuaishou.account.list", [
            ("/data/list/*/create_time", "string"),
        ])]),
    )
    second = _write_json(
        tmp_path / "second.json",
        _run([_outcome("promotion.kuaishou.account.list", [
            ("/data/list/*/create_time", "integer"),
        ])]),
    )

    forward = build_drift_plan([first, second])
    reverse = build_drift_plan([second, first])
    decision = _decisions(forward)[(
        "promotion.kuaishou.account.list", "/data/list/*/create_time"
    )]

    assert forward == reverse
    assert decision["observed_types"] == ["integer", "string"]
    assert decision["reason"] == "conflicting_observed_types"


def test_v2_run_declaration_consumes_only_additive_drift_fields(
    tmp_path: Path,
) -> None:
    operation_id = "promotion.kuaishou.account.list"
    operation_root = _temporary_operation_root(
        tmp_path,
        operation_id,
        remove_fields={operation_id: {"item_keys": {"create_time"}}},
    )
    outcome = _outcome(operation_id, [])
    outcome["response_drift"] = {
        "schema_version": "gravity.response-drift.v2",
        "direction": "response",
        "classification": "breaking",
        "fields": [
            {
                "classification": "breaking",
                "path": "/data/list",
                "expected_type": "array",
                "observed_type": "object",
            },
            {
                "classification": "additive",
                "path": "/data/list/*/create_time",
                "observed_type": "string",
            },
        ],
    }
    evidence = _write_json(tmp_path / "run.json", _run([outcome]))

    plan = build_drift_plan([evidence], operation_root=operation_root)
    decisions = _decisions(plan)

    assert set(decisions) == {(operation_id, "/data/list/*/create_time")}
    assert plan["summary"]["automatic"] == 1
    persisted = json.loads(evidence.read_text(encoding="utf-8"))
    assert persisted["outcomes"][0]["response_drift"]["fields"][0][
        "classification"
    ] == "breaking"


def test_safe_scalar_uses_existing_projection_slot(tmp_path: Path) -> None:
    operation_root = _temporary_operation_root(
        tmp_path,
        "promotion.kuaishou.account.list",
        remove_fields={
            "promotion.kuaishou.account.list": {"item_keys": {"create_time"}}
        },
    )
    evidence = _write_json(
        tmp_path / "run.json",
        _run([_outcome("promotion.kuaishou.account.list", [
            ("/data/list/*/create_time", "string"),
        ])]),
    )

    plan = build_drift_plan([evidence], operation_root=operation_root)
    decision = _decisions(plan)[(
        "promotion.kuaishou.account.list", "/data/list/*/create_time"
    )]

    assert plan["schema_version"] == PLAN_SCHEMA_VERSION
    assert plan["summary"]["automatic"] == 1
    assert decision["proposed_edit"] == {
        "projection_field": "item_keys",
        "projection_key": None,
        "value": "create_time",
    }
    assert decision["exposure_path"] == "data.list[].create_time"


def test_manual_reasons_cover_dynamic_privacy_and_topology(tmp_path: Path) -> None:
    operation_root = _temporary_operation_root(
        tmp_path,
        "analysis.funnel.query",
        "promotion.kuaishou.account.list",
        remove_fields={
            "promotion.kuaishou.account.list": {"item_keys": {"operator_name"}}
        },
    )
    evidence = _write_json(
        tmp_path / "recovered.json",
        {
            "analysis.funnel.query": {
                "/data/aggregate_date/group/2026-09-04": "object",
                "/data/aggregate_date/group/2026-09-05": "object",
                "/data/aggregate_date/group/2026-02-30": "object",
            },
            "promotion.kuaishou.account.list": {
                "/data/list/*/operator_name": "string",
                "/data/list/*/unreviewed_business_value": "string",
                "/data/list/*/known/new_leaf": "string",
            },
        },
    )

    decisions = _decisions(
        build_drift_plan([evidence], operation_root=operation_root)
    )

    assert decisions[(
        "analysis.funnel.query", "/data/aggregate_date/group/2026-09-04"
    )]["reason"] == "declared_dynamic_key"
    assert decisions[(
        "analysis.funnel.query", "/data/aggregate_date/group/2026-09-05"
    )]["reason"] == "declared_dynamic_key"
    mismatch = decisions[(
        "analysis.funnel.query", "/data/aggregate_date/group/2026-02-30"
    )]
    assert mismatch["reason"] == "dynamic_key_shape_mismatch"
    assert mismatch["expected_key_shape"] == "iso_date"
    assert decisions[(
        "promotion.kuaishou.account.list", "/data/list/*/operator_name"
    )]["reason"] == "personal_or_privilege_field_requires_review"
    assert decisions[(
        "promotion.kuaishou.account.list", "/data/list/*/unreviewed_business_value"
    )]["reason"] == "privacy_classification_required"
    assert decisions[(
        "promotion.kuaishou.account.list", "/data/list/*/known/new_leaf"
    )]["reason"] == "projection_topology_requires_review"


def test_plan_apply_is_exact_and_rolls_back_failed_gate(tmp_path: Path) -> None:
    operation_id = "promotion.kuaishou.account.list"
    operation_root = _temporary_operation_root(
        tmp_path,
        operation_id,
        remove_fields={operation_id: {"item_keys": {"create_time"}}},
    )
    evidence = _write_json(
        tmp_path / "run.json",
        _run([_outcome(operation_id, [
            ("/data/list/*/create_time", "string"),
        ])]),
    )
    plan_path = tmp_path / "plan.json"
    write_drift_plan(
        plan_path,
        build_drift_plan([evidence], operation_root=operation_root),
    )
    source_path = operation_root / f"{operation_id}.json"
    before = source_path.read_bytes()

    def failed_gate(_root: Path) -> list[dict[str, object]]:
        raise RuntimeError("forced gate failure")

    with pytest.raises(RuntimeError, match="rolled back"):
        apply_drift_plan(
            plan_path,
            root=tmp_path,
            refresh_products=lambda _root, _operations: [],
            gate_runner=failed_gate,
            require_clean=False,
        )

    assert source_path.read_bytes() == before


def test_plan_apply_writes_only_automatic_entries(tmp_path: Path) -> None:
    operation_id = "promotion.kuaishou.account.list"
    operation_root = _temporary_operation_root(
        tmp_path,
        operation_id,
        remove_fields={operation_id: {"item_keys": {"create_time"}}},
    )
    evidence = _write_json(
        tmp_path / "run.json",
        _run([_outcome(operation_id, [
            ("/data/list/*/access_token", "string"),
            ("/data/list/*/create_time", "string"),
        ])]),
    )
    plan_path = tmp_path / "plan.json"
    write_drift_plan(
        plan_path,
        build_drift_plan([evidence], operation_root=operation_root),
    )

    result = apply_drift_plan(
        plan_path,
        root=tmp_path,
        refresh_products=lambda _root, _operations: [],
        gate_runner=lambda _root: [{"exit_code": 0}],
        require_clean=False,
    )
    operation = json.loads(
        (operation_root / f"{operation_id}.json").read_text(encoding="utf-8")
    )["operation"]

    assert result["automatic"] == 1
    assert "create_time" in operation["response_projection"]["item_keys"]
    assert "access_token" not in operation["response_projection"]["item_keys"]


def test_apply_rejects_tampered_or_stale_plan(tmp_path: Path) -> None:
    operation_id = "promotion.kuaishou.account.list"
    operation_root = _temporary_operation_root(
        tmp_path,
        operation_id,
        remove_fields={operation_id: {"item_keys": {"create_time"}}},
    )
    evidence = _write_json(
        tmp_path / "run.json",
        _run([_outcome(operation_id, [
            ("/data/list/*/create_time", "string"),
        ])]),
    )
    plan = build_drift_plan([evidence], operation_root=operation_root)
    tampered = deepcopy(plan)
    tampered["summary"]["automatic"] = 99
    tampered_path = _write_json(tmp_path / "tampered.json", tampered)
    with pytest.raises(ValueError, match="digest changed"):
        apply_drift_plan(tampered_path, root=tmp_path, require_clean=False)

    plan_path = tmp_path / "plan.json"
    write_drift_plan(plan_path, plan)
    source_path = operation_root / f"{operation_id}.json"
    source = json.loads(source_path.read_text(encoding="utf-8"))
    source["operation"]["description"] += " changed"
    _write_json(source_path, source)
    with pytest.raises(ValueError, match="plan is stale"):
        apply_drift_plan(plan_path, root=tmp_path, require_clean=False)


def test_cli_exposes_two_phase_commands() -> None:
    plan = build_parser().parse_args([
        "drift-plan", "--evidence", "run.json", "--selector", "app.list"
    ])
    apply = build_parser().parse_args(["drift-apply", "--plan", "plan.json"])

    assert plan.command == "drift-plan"
    assert plan.selector == ["app.list"]
    assert apply.command == "drift-apply"
