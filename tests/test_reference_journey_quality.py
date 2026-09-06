from __future__ import annotations

import copy
import unittest

from gravity_insight.reference_journey_quality import evaluate_playbook_data_quality


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
    def test_quality_is_orthogonal_to_product_completeness(self):
        quality = evaluate_playbook_data_quality(result())

        self.assertEqual("pass", quality["status"])
        self.assertEqual([], quality["reason_codes"])
        self.assertEqual(
            {"playbook-result", "query-result-audit"},
            {item["check_id"] for item in quality["checks"]},
        )

    def test_missing_or_malformed_query_evidence_fails(self):
        broken = result()
        broken["steps"][0]["result_audit"] = None
        truncated = result()
        truncated["steps"].pop()
        malformed_id = result()
        malformed_id["steps"][0]["id"] = []

        for value in (broken, truncated, malformed_id):
            with self.subTest(value=value):
                quality = evaluate_playbook_data_quality(copy.deepcopy(value))
                self.assertEqual("fail", quality["status"])
                self.assertEqual(["DATA_QUALITY_FAILED"], quality["reason_codes"])


if __name__ == "__main__":
    unittest.main()
