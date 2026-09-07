from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import MappingProxyType
import unittest
from unittest import mock

from gravity_insight.capability_contract import capability_contract
from gravity_insight.capability_contract import _operations
from gravity_insight.capability_validation import CapabilityValidationStore
from gravity_insight.errors import UpstreamError
from gravity_insight.read_result_support import result_warnings
from gravity_insight.workspace import Workspace, WorkspaceDefaults
import scripts.capability_validation_evidence_support as evidence_support
from scripts.capability_validation_evidence_support import (
    BudgetedSession,
    RequestBudgetExceeded,
    bind_probe_app,
    error_outcome,
    inventory,
    result_outcome,
    validation_from_execution,
)


NOW = datetime(2026, 9, 3, 8, 0, tzinfo=timezone.utc)


class Session:
    def __init__(self):
        self.calls = 0

    def request(self, *args, **kwargs):
        self.calls += 1
        return args, kwargs


def result(**overrides):
    artifact = capability_contract("operation", "analysis.event.list")
    contract = artifact["contract"]
    value = {
        "ok": True,
        "status": "success",
        "operation_id": "analysis.event.list",
        "contract_version": contract["contract_version"],
        "source": {"contract_fingerprint": contract["provider"]["fingerprint"]},
        "schema_fingerprint": "a" * 64,
        "fetched_at": "2026-09-03T08:00:00Z",
        "data": {"list": [{"name": "value-not-persisted"}]},
        "warnings": list(result_warnings(_operations()["analysis.event.list"], ())),
        "error": None,
        "result_audit": {
            "schema_version": "gravity.result-audit.v1",
            "fact_paths": {"operation_id": "/operation_id"},
            "http_receipts": [
                {"receipt_id": "b" * 32, "storage_status": "stored"}
            ],
        },
    }
    value.update(overrides)
    return value


def receipt(**overrides):
    value = {
        "receipt_id": "b" * 32,
        "operation_id": "analysis.event.list",
        "http_status": 200,
        "completed_at": "2026-09-03T08:00:00.100000Z",
    }
    value.update(overrides)
    return value


class CapabilityEvidenceCollectorTests(unittest.TestCase):
    def test_inventory_separates_reads_writes_and_unproven_upper_layers(self):
        value = inventory()

        self.assertEqual(231, value["capabilities"])
        self.assertEqual(190, value["counts"]["read_probe_candidate"])
        self.assertEqual(38, value["counts"]["requires_production_write"])
        self.assertEqual(3, value["counts"]["execution_path_unproven"])
        self.assertFalse(value["network_called"])

    def test_app_binding_replaces_only_exact_declared_placeholders(self):
        value = bind_probe_app(
            MappingProxyType({
                "app_id": "$first_app_id",
                "nested": ("$parent:app_id", "$first_event_name"),
            }),
            "29034827",
        )

        self.assertEqual("29034827", value["app_id"])
        self.assertEqual("29034827", value["nested"][0])
        self.assertEqual("$first_event_name", value["nested"][1])

    def test_budgeted_session_blocks_before_the_excess_request(self):
        delegate = Session()
        session = BudgetedSession(delegate, 1)

        session.request("GET", "https://example.invalid")
        with self.assertRaises(RequestBudgetExceeded):
            session.request("GET", "https://example.invalid")

        self.assertEqual(1, session.sent)
        self.assertEqual(1, delegate.calls)

    def test_real_execution_shape_builds_nonempty_quality_checks(self):
        artifact = capability_contract("operation", "analysis.event.list")

        validation, reasons = validation_from_execution(
            artifact,
            result(),
            [receipt()],
            started_at=NOW,
            observed_at=NOW + timedelta(seconds=1),
        )

        self.assertEqual([], reasons)
        self.assertEqual("stable", validation["trust_status"])
        self.assertEqual("pass", validation["data_quality"]["status"])
        self.assertTrue(validation["data_quality"]["checks"])
        self.assertEqual(
            [{"kind": "receipt", "reference": "receipt:" + "b" * 32}],
            validation["evidence_references"],
        )

    def test_empty_drifted_or_receiptless_result_never_qualifies(self):
        artifact = capability_contract("operation", "analysis.event.list")
        cases = (
            (result(status="empty", data={"list": []}), [receipt()]),
            (
                result(
                    result_audit={
                        **result()["result_audit"],
                        "response_drift": {
                            "schema_version": "gravity.response-drift.v1",
                            "direction": "response",
                            "classification": "additive",
                            "fields": [{"path": "/data/new", "observed_type": "string"}],
                        },
                    }
                ),
                [receipt()],
            ),
            (result(), []),
        )

        for value, receipts in cases:
            with self.subTest(status=value["status"], receipts=bool(receipts)):
                validation, reasons = validation_from_execution(
                    artifact,
                    value,
                    receipts,
                    started_at=NOW,
                    observed_at=NOW + timedelta(seconds=1),
                )
                self.assertIsNone(validation)
                self.assertTrue(reasons)

    def test_unexpected_runtime_warning_never_qualifies(self):
        artifact = capability_contract("operation", "analysis.event.list")

        validation, reasons = validation_from_execution(
            artifact,
            result(warnings=["new response warning"]),
            [receipt()],
            started_at=NOW,
            observed_at=NOW + timedelta(seconds=1),
        )

        self.assertIsNone(validation)
        self.assertIn("EXECUTION_WARNINGS_PRESENT", reasons)

    def test_outcomes_persist_only_value_free_diagnostics(self):
        response_value = "RESPONSE_VALUE_MUST_NOT_PERSIST"
        error_message = "ERROR_MESSAGE_MUST_NOT_PERSIST"
        exception_message = "EXCEPTION_MESSAGE_MUST_NOT_PERSIST"
        drift = {
            "schema_version": "gravity.response-drift.v2",
            "direction": "response",
            "classification": "breaking",
            "fields": [
                {
                    "classification": "breaking",
                    "path": "/data/config",
                    "expected_type": "json_scalar",
                    "observed_type": "object",
                },
                {
                    "classification": "additive",
                    "path": "/data/new_field",
                    "observed_type": "string",
                },
            ],
        }
        failed = result(
            ok=False,
            status="contract_changed",
            data={"list": [{"new_field": response_value}]},
            error={
                "code": "CONTRACT_CHANGED",
                "category": "upstream",
                "message": error_message,
                "field": response_value,
            },
            result_audit={
                **result()["result_audit"],
                "response_drift": drift,
            },
        )

        result_evidence = result_outcome(
            "analysis.event.list",
            failed,
            1,
            [receipt()],
            False,
            ["EXECUTION_RESPONSE_DRIFT", "EXECUTION_ERROR_PRESENT"],
        )
        exception_evidence = error_outcome(
            "analysis.event.list",
            UpstreamError(exception_message, field=response_value),
            1,
            [],
        )

        self.assertEqual(drift, result_evidence["response_drift"])
        self.assertEqual(
            {"code": "CONTRACT_CHANGED", "category": "upstream"},
            result_evidence["error_detail"],
        )
        self.assertEqual(
            {"code": "UPSTREAM_UNAVAILABLE", "category": "upstream"},
            exception_evidence["error_detail"],
        )
        encoded = json.dumps([result_evidence, exception_evidence])
        for forbidden in (response_value, error_message, exception_message):
            self.assertNotIn(forbidden, encoded)

    def test_malformed_error_detail_is_reduced_to_unknown_identity(self):
        business_value = "BUSINESS_VALUE_MUST_NOT_PERSIST"
        failed = result(
            error={"code": business_value, "category": [business_value]}
        )

        outcome = result_outcome(
            "analysis.event.list",
            failed,
            1,
            [receipt()],
            False,
            ["EXECUTION_ERROR_PRESENT"],
        )

        self.assertEqual(
            {"code": "UNKNOWN", "category": "unknown"},
            outcome["error_detail"],
        )
        self.assertNotIn(business_value, json.dumps(outcome))

    def test_run_and_summary_v2_write_additive_and_breaking_drift(self):
        additive_drift = {
            "schema_version": "gravity.response-drift.v1",
            "direction": "response",
            "classification": "additive",
            "fields": [{"path": "/data/new", "observed_type": "integer"}],
        }
        breaking_drift = {
            "schema_version": "gravity.response-drift.v2",
            "direction": "response",
            "classification": "breaking",
            "fields": [
                {
                    "classification": "breaking",
                    "path": "/data/list",
                    "expected_type": "array",
                    "observed_type": "object",
                    "expectation_provenance": {
                        "operation_contract": {
                            "digest": "1" * 64,
                            "version": "gravity.operation-contract.v1",
                        },
                        "runtime_version": "0.3.11",
                        "request_shape_fingerprint": "2" * 64,
                        "accepted_upstream_baseline": {
                            "observed_type": "array",
                            "response_shape_fingerprint": "3" * 64,
                            "observed_at": "2026-09-01T08:00:00Z",
                            "app_environment_fingerprint": "4" * 64,
                        },
                        "current_observation": {
                            "response_shape_fingerprint": "5" * 64,
                            "observed_at": "2026-09-03T08:00:00.100000Z",
                            "app_environment_fingerprint": "4" * 64,
                        },
                    },
                }
            ],
        }
        additive = result_outcome(
            "analysis.event.list",
            result(
                result_audit={
                    **result()["result_audit"],
                    "response_drift": additive_drift,
                }
            ),
            1,
            [receipt()],
            False,
            ["EXECUTION_RESPONSE_DRIFT"],
        )
        breaking = result_outcome(
            "analysis.event_property.list",
            result(
                status="contract_changed",
                result_audit={
                    **result()["result_audit"],
                    "response_drift": breaking_drift,
                },
            ),
            1,
            [receipt(operation_id="analysis.event_property.list")],
            False,
            ["EXECUTION_RESPONSE_DRIFT"],
        )
        historical = result_outcome(
            "historical.operation",
            result(status="empty", data={"list": []}),
            1,
            [],
            False,
            ["EXECUTION_DATA_EMPTY"],
        )
        legacy_fingerprint_value = "LEGACY_FINGERPRINT_VALUE_MUST_NOT_PERSIST"
        historical["schema_fingerprint"] = {
            "unexpected": legacy_fingerprint_value
        }
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            run_root = root / "agent-runtime" / "capability-validation-runs"
            run_root.mkdir(parents=True)
            (run_root / "20260902T000000Z.json").write_text(
                json.dumps({
                    "schema_version": "gravity.capability-validation-run.v1",
                    "production_requests_total": 1,
                    "outcomes": [historical],
                }),
                encoding="utf-8",
            )
            workspace = Workspace(
                path=None,
                root=root,
                state_root=root,
                apps={},
                defaults=WorkspaceDefaults(
                    app=None, timezone="UTC", time_window=None
                ),
                datasources={},
                products={},
                recipes={},
            )
            with mock.patch.dict(
                sys.modules,
                {"capability_validation_evidence_support": evidence_support},
            ):
                from scripts import collect_capability_validation_evidence as collector

            trust = {
                "stable": 0,
                "complete": 0,
                "data_quality_pass": 0,
                "provider_matched": 0,
                "total": 231,
            }
            with (
                mock.patch.object(
                    collector,
                    "resolve_env_path",
                    return_value=(root / "unused.env", False),
                ),
                mock.patch.object(collector, "load_workspace", return_value=workspace),
                mock.patch.object(collector, "scope_workspace", return_value=workspace),
                mock.patch.object(collector, "trust_counts", return_value=trust),
            ):
                run_report = collector._run_report(
                    started_at=NOW,
                    finished_at=NOW + timedelta(seconds=1),
                    app_id="1",
                    request_budget=2,
                    prior_requests=1,
                    requests_sent=1,
                    counter_count=1,
                    candidates=[{"contract": {}}],
                    validations=[],
                    store=CapabilityValidationStore(values=[]),
                    outcomes={
                        ("operation", "analysis.event.list"): additive,
                        ("operation", "analysis.event_property.list"): breaking,
                    },
                )
                collector._write_report(
                    root, run_report, NOW + timedelta(seconds=1)
                )
                collector.summarize()

            persisted_run = json.loads(
                (run_root / "20260903T080001Z.json").read_text(encoding="utf-8")
            )
            summary = json.loads(
                (
                    root
                    / "agent-runtime"
                    / "capability-validation-summary.v2.json"
                ).read_text(encoding="utf-8")
            )

        self.assertEqual("gravity.capability-validation-summary.v2", summary["schema_version"])
        self.assertEqual("gravity.capability-validation-run.v2", run_report["schema_version"])
        self.assertEqual(2, summary["source_run_count"])
        self.assertEqual(3, len(summary["unresolved"]))
        self.assertEqual(additive_drift, summary["unresolved"][0]["response_drift"])
        self.assertEqual(breaking_drift, summary["unresolved"][1]["response_drift"])
        persisted_drift = persisted_run["outcomes"][1]["response_drift"]
        self.assertEqual("breaking", persisted_drift["classification"])
        self.assertEqual("array", persisted_drift["fields"][0]["expected_type"])
        self.assertEqual(
            breaking_drift["fields"][0]["expectation_provenance"],
            persisted_drift["fields"][0]["expectation_provenance"],
        )
        self.assertNotIn("response_drift", summary["unresolved"][2])
        self.assertNotIn(legacy_fingerprint_value, json.dumps(summary))


if __name__ == "__main__":
    unittest.main()
