from __future__ import annotations

import copy
from datetime import datetime, timezone
import unittest
from unittest.mock import patch

from gravity_sdk.reference_journey_contract import reference_artifacts
from gravity_sdk.reference_journey_trust import (
    evaluate_playbook_data_quality,
    evaluate_reference_trust,
)


NOW = datetime(2026, 8, 21, 12, 0, tzinfo=timezone.utc)
COMPLETE_OPERATION = {
    "operation_id": "report.multidim.query",
    "contract_version": "4",
    "contract_fingerprint": "5f5cf69fb1184ea1f25a279c39e5bd1dde6493e39c09dfda81639dfda373d991",
    "completeness": "complete",
    "pagination_evidence": "production",
}


def validation(**overrides):
    artifact = reference_artifacts()["capability_trust"]
    value = {
        "schema_version": "gravity.capability-validation.v1",
        "selector": "metric-anomaly-localization@1",
        "contract_digest": artifact["digest"],
        "provider_fingerprint": COMPLETE_OPERATION["contract_fingerprint"],
        "validated_at": "2026-08-21T11:00:00Z",
        "expires_at": "2026-08-22T11:00:00Z",
        "trust_status": "stable",
        "completeness": "complete",
        "data_quality": "pass",
        "reason_codes": [],
    }
    value.update(overrides)
    return value


class ReferenceJourneyTrustTests(unittest.TestCase):
    def test_current_contract_honestly_blocks_unknown_completeness(self):
        result = evaluate_reference_trust(now=NOW)

        self.assertEqual("blocked", result["trust_status"])
        self.assertEqual(["COMPLETENESS_INSUFFICIENT"], result["reason_codes"])
        self.assertEqual("unknown", result["operation"]["completeness"])
        self.assertEqual([], result["allowed_claims"])
        self.assertFalse(result["network_called"])

    @patch(
        "gravity_sdk.reference_journey_trust._operation_state",
        return_value=COMPLETE_OPERATION,
    )
    def test_complete_contract_still_requires_fresh_same_layer_validation(self, _state):
        missing = evaluate_reference_trust(now=NOW)
        stable = evaluate_reference_trust(validation(), now=NOW)

        self.assertEqual("unknown", missing["trust_status"])
        self.assertEqual(["CAPABILITY_VALIDATION_MISSING"], missing["reason_codes"])
        self.assertEqual("stable", stable["trust_status"])
        self.assertTrue(stable["allowed_claims"])

    @patch(
        "gravity_sdk.reference_journey_trust._operation_state",
        return_value=COMPLETE_OPERATION,
    )
    def test_expiry_and_fingerprint_drift_do_not_degrade_to_stable(self, _state):
        expired = evaluate_reference_trust(
            validation(expires_at="2026-08-21T12:00:00Z"), now=NOW
        )
        oversized_ttl = evaluate_reference_trust(
            validation(expires_at="2026-08-23T11:00:00Z"), now=NOW
        )
        drift = evaluate_reference_trust(
            validation(provider_fingerprint="f" * 64), now=NOW
        )

        self.assertEqual("unknown", expired["trust_status"])
        self.assertEqual(["CAPABILITY_VALIDATION_EXPIRED"], expired["reason_codes"])
        self.assertEqual("quarantined", oversized_ttl["trust_status"])
        self.assertEqual(
            ["CAPABILITY_VALIDATION_INVALID"], oversized_ttl["reason_codes"]
        )
        self.assertEqual("quarantined", drift["trust_status"])
        self.assertEqual(["CAPABILITY_FINGERPRINT_MISMATCH"], drift["reason_codes"])

    @patch(
        "gravity_sdk.reference_journey_trust._operation_state",
        return_value={**COMPLETE_OPERATION, "contract_fingerprint": "a" * 64},
    )
    def test_static_operation_drift_quarantines_before_validation(self, _state):
        result = evaluate_reference_trust(validation(), now=NOW)
        self.assertEqual("quarantined", result["trust_status"])
        self.assertEqual(["CAPABILITY_FINGERPRINT_MISMATCH"], result["reason_codes"])

    @patch(
        "gravity_sdk.reference_journey_trust.playbook_definition_fingerprint",
        return_value="a" * 64,
    )
    @patch(
        "gravity_sdk.reference_journey_trust._operation_state",
        return_value=COMPLETE_OPERATION,
    )
    def test_product_definition_drift_quarantines_same_layer_trust(
        self, _state, _fingerprint
    ):
        result = evaluate_reference_trust(validation(), now=NOW)

        self.assertEqual("quarantined", result["trust_status"])
        self.assertEqual(
            ["CAPABILITY_FINGERPRINT_MISMATCH"], result["reason_codes"]
        )

    def test_data_quality_never_infers_missing_completeness(self):
        result = {
            "schema_version": "gravity.metric-anomaly-localization-result.v1",
            "ok": True,
            "status": "success",
            "conclusion": {"verdict": "observed"},
            "steps": [
                {
                    "id": step_id,
                    "kind": "query",
                    "status": "success",
                    "result_audit": {"schema_version": "gravity.result-audit.v1"},
                }
                for step_id in (
                    "compare_current",
                    "compare_reference",
                    "validate_current",
                    "validate_reference",
                )
            ],
        }
        unknown = evaluate_playbook_data_quality(result, completeness="unknown")
        passed = evaluate_playbook_data_quality(result, completeness="complete")

        self.assertEqual("unknown", unknown["status"])
        self.assertEqual(["DATA_QUALITY_UNPROVEN"], unknown["reason_codes"])
        self.assertEqual("pass", passed["status"])
        self.assertEqual([], passed["reason_codes"])

        broken = copy.deepcopy(result)
        broken["steps"][0]["result_audit"] = None
        self.assertEqual(
            "fail",
            evaluate_playbook_data_quality(broken, completeness="complete")["status"],
        )
        truncated = copy.deepcopy(result)
        truncated["steps"].pop()
        self.assertEqual(
            "fail",
            evaluate_playbook_data_quality(
                truncated, completeness="complete"
            )["status"],
        )
        malformed_id = copy.deepcopy(result)
        malformed_id["steps"][0]["id"] = []
        self.assertEqual(
            "fail",
            evaluate_playbook_data_quality(
                malformed_id, completeness="complete"
            )["status"],
        )

    @patch(
        "gravity_sdk.reference_journey_trust._operation_state",
        return_value=COMPLETE_OPERATION,
    )
    def test_validation_reason_codes_are_structured_and_consistent(self, _state):
        malformed = evaluate_reference_trust(
            validation(trust_status="blocked", reason_codes="UNTRUSTED"),
            now=NOW,
        )
        contradictory = evaluate_reference_trust(
            validation(reason_codes=["CAPABILITY_VALIDATION_BLOCKED"]),
            now=NOW,
        )

        self.assertEqual("quarantined", malformed["trust_status"])
        self.assertEqual("quarantined", contradictory["trust_status"])
        self.assertEqual(
            ["CAPABILITY_VALIDATION_INVALID"], malformed["reason_codes"]
        )


if __name__ == "__main__":
    unittest.main()
