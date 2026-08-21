from __future__ import annotations

import copy
import unittest

from gravity_sdk.reference_journey_quality import evaluate_playbook_data_quality


def result():
    return {
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


class ReferenceJourneyQualityTests(unittest.TestCase):
    def test_quality_never_infers_missing_product_completeness(self):
        unknown = evaluate_playbook_data_quality(result(), completeness="unknown")
        passed = evaluate_playbook_data_quality(result(), completeness="complete")

        self.assertEqual("unknown", unknown["status"])
        self.assertEqual(["DATA_QUALITY_UNPROVEN"], unknown["reason_codes"])
        self.assertEqual("pass", passed["status"])
        self.assertEqual([], passed["reason_codes"])

    def test_missing_or_malformed_query_evidence_fails(self):
        broken = result()
        broken["steps"][0]["result_audit"] = None
        truncated = result()
        truncated["steps"].pop()
        malformed_id = result()
        malformed_id["steps"][0]["id"] = []

        for value in (broken, truncated, malformed_id):
            with self.subTest(value=value):
                quality = evaluate_playbook_data_quality(
                    copy.deepcopy(value), completeness="complete"
                )
                self.assertEqual("fail", quality["status"])
                self.assertEqual(["DATA_QUALITY_FAILED"], quality["reason_codes"])


if __name__ == "__main__":
    unittest.main()
