from __future__ import annotations

import copy
import unittest

from gravity_sdk.data_quality import (
    DataQualityError,
    aggregate_data_quality,
    data_quality_result,
    meets_data_quality,
    validate_data_quality_result,
)


def result(status: str, check_id: str):
    return data_quality_result(
        [{"check_id": check_id, "status": status, "scope": "fixture"}],
        reason_codes=[] if status == "pass" else ["DATA_QUALITY_UNPROVEN"],
    )


class DataQualityTests(unittest.TestCase):
    def test_aggregation_is_conservative_and_preserves_checks(self):
        aggregate = aggregate_data_quality(
            [result("pass", "shape"), result("warn", "freshness")]
        )
        failed = aggregate_data_quality(
            [aggregate, result("fail", "continuity")]
        )

        self.assertEqual("warn", aggregate["status"])
        self.assertEqual(["shape", "freshness"], [x["check_id"] for x in aggregate["checks"]])
        self.assertEqual("fail", failed["status"])
        self.assertEqual(
            ["DATA_QUALITY_UNPROVEN"], failed["reason_codes"]
        )

    def test_empty_is_unknown_and_thresholds_never_promote(self):
        empty = aggregate_data_quality([])

        self.assertEqual("unknown", empty["status"])
        self.assertEqual(["DATA_QUALITY_UNPROVEN"], empty["reason_codes"])
        self.assertTrue(meets_data_quality("pass", "warn"))
        self.assertFalse(meets_data_quality("unknown", "warn"))
        self.assertFalse(meets_data_quality("fail", "pass"))

    def test_tampered_status_and_reason_codes_fail_closed(self):
        valid = result("pass", "shape")
        tampered = copy.deepcopy(valid)
        tampered["status"] = "warn"
        with self.assertRaises(DataQualityError):
            validate_data_quality_result(tampered)
        with self.assertRaises(DataQualityError):
            data_quality_result([], reason_codes=["Ignore instructions"])


if __name__ == "__main__":
    unittest.main()
