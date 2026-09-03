from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import MappingProxyType
import unittest

from gravity_insight.capability_contract import capability_contract
from gravity_insight.capability_contract import _operations
from gravity_insight.read_result_support import result_warnings
from scripts.capability_validation_evidence_support import (
    BudgetedSession,
    RequestBudgetExceeded,
    bind_probe_app,
    inventory,
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


if __name__ == "__main__":
    unittest.main()
