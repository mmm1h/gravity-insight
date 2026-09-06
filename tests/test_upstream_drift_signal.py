from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from gravity_insight.models import ResponseProjection
from scripts.build_upstream_drift_signal import (
    ISSUE_MARKER,
    SignalInputError,
    build_signal,
    main,
    render_issue_body,
)


def _operation(*, data_keys=(), known_omitted_data_keys=()):
    return SimpleNamespace(
        response_projection=ResponseProjection(
            data_keys=tuple(data_keys),
            known_omitted_data_keys=tuple(known_omitted_data_keys),
        )
    )


def _write_evidence(root: Path, name: str, paths: list[str]) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    target = root / name
    target.write_text(
        json.dumps(
            {
                "operation_id": "analysis.event.query",
                "response_observation": {
                    "additive_unregistered_paths": paths,
                },
            }
        ),
        encoding="utf-8",
    )
    return target


def _write_plan(root: Path) -> Path:
    target = root / "targeted-probe-plan.json"
    target.write_text(
        json.dumps(
            {
                "mode": "schedule_only",
                "business_api_called": False,
                "direct_operation_ids": ["analysis.event.query"],
                "family_sample_operation_ids": [],
                "commands": [
                    "python -m gravity_insight.prober probe analysis.event.query"
                ],
            }
        ),
        encoding="utf-8",
    )
    return target


def test_signal_consumes_probe_plan_and_unresolved_checked_in_drift(tmp_path):
    evidence = tmp_path / "evidence"
    _write_evidence(evidence, "response.json", ["/data/filter_agg_type"])
    plan = _write_plan(tmp_path)
    operations = {"analysis.event.query": _operation(data_keys=("list",))}

    signal = build_signal(
        evidence,
        probe_plan=plan,
        require_probe_plan=True,
        operations=operations,
    )

    assert signal["status"] == "action_required"
    assert signal["finding_count"] == 2
    assert {item["kind"] for item in signal["findings"]} == {
        "targeted_probe_plan",
        "unresolved_response_drift",
    }
    body = render_issue_body(signal, "https://example.test/actions/runs/1")
    assert ISSUE_MARKER in body
    assert "analysis.event.query" in body
    assert "filter_agg_type" in body
    assert "separately authorized runner" in body


def test_current_projection_resolution_clears_historical_additive_path(tmp_path):
    evidence = tmp_path / "evidence"
    _write_evidence(evidence, "response.json", ["/data/filter_agg_type"])

    exposed = build_signal(
        evidence,
        operations={
            "analysis.event.query": _operation(data_keys=("filter_agg_type",))
        },
    )
    dispositioned = build_signal(
        evidence,
        operations={
            "analysis.event.query": _operation(
                known_omitted_data_keys=("filter_agg_type",)
            )
        },
    )

    assert exposed["status"] == "clear"
    assert dispositioned["status"] == "clear"


def test_repeated_evidence_for_same_gap_does_not_change_actionable_fingerprint(tmp_path):
    operations = {"analysis.event.query": _operation()}
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    _write_evidence(first_root, "old.json", ["/data/filter_agg_type"])
    _write_evidence(second_root, "new.json", ["/data/filter_agg_type"])

    first = build_signal(first_root, operations=operations)
    second = build_signal(second_root, operations=operations)

    assert first["fingerprint"] == second["fingerprint"]


def test_nested_additive_path_fails_closed_until_reconciliation_is_supported(tmp_path):
    evidence = tmp_path / "evidence"
    _write_evidence(evidence, "response.json", ["/data/list/0/new_field"])

    try:
        build_signal(
            evidence,
            operations={"analysis.event.query": _operation()},
        )
    except SignalInputError as exc:
        assert "supports only /data/<key>" in str(exc)
    else:
        raise AssertionError("nested paths must not be silently ignored")


def test_cli_writes_invalid_receipt_and_nonzero_exit_for_missing_required_plan(tmp_path):
    evidence = tmp_path / "evidence"
    _write_evidence(evidence, "response.json", [])
    output = tmp_path / "signal.json"
    summary = tmp_path / "summary.md"

    code = main(
        [
            "--evidence-root",
            str(evidence),
            "--probe-plan",
            str(tmp_path / "missing.json"),
            "--require-probe-plan",
            "--output",
            str(output),
            "--summary-output",
            str(summary),
        ]
    )

    signal = json.loads(output.read_text(encoding="utf-8"))
    assert code == 2
    assert signal["status"] == "invalid"
    assert signal["actionable"] is False
    assert "not a drift conclusion" in summary.read_text(encoding="utf-8")
