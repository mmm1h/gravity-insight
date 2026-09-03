from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from gravity_insight.errors import InputValidationError
from gravity_insight.journey_service import JourneyService


class NoClientSDK:
    def __init__(self, workspace):
        self.workspace = workspace

    @property
    def insight(self):
        raise AssertionError("offline Journey inspection constructed a client")

    @property
    def sql(self):
        raise AssertionError("offline Journey inspection constructed a client")


class JourneyServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.workspace = SimpleNamespace(root=root, state_root=root / "state")
        self.service = JourneyService(NoClientSDK(self.workspace))

    def tearDown(self):
        self.temporary.cleanup()

    def test_list_verify_and_describe_are_deterministic_and_offline(self):
        listed = self.service.list()
        verified = self.service.verify()
        described = self.service.describe("analysis.event-trend")

        self.assertEqual(11, listed["count"])
        self.assertEqual(
            sorted(item["journey_id"] for item in listed["journeys"]),
            [item["journey_id"] for item in listed["journeys"]],
        )
        self.assertEqual("valid", verified["status"])
        self.assertEqual(
            "analysis.event-trend", described["journey"]["journey_id"]
        )
        self.assertEqual(2, len(described["required_capabilities"]))
        self.assertFalse(listed["network_called"])
        self.assertFalse(described["network_called"])

    def test_current_pilot_matrix_has_no_invented_verified_result(self):
        results = {
            journey_id: self.service.can_run(journey_id)
            for journey_id in (
                "analysis.readable-app-catalog",
                "analysis.event-trend",
                "analysis.business-pulse",
                "analysis.ltv-curve-fit",
                "analysis.experiment-outcome-evaluation",
            )
        }

        self.assertEqual("unknown", results["analysis.readable-app-catalog"]["can_run_status"])
        self.assertEqual("blocked", results["analysis.event-trend"]["can_run_status"])
        self.assertEqual("blocked", results["analysis.business-pulse"]["can_run_status"])
        ltv = results["analysis.ltv-curve-fit"]
        self.assertEqual("blocked", ltv["can_run_status"])
        self.assertEqual(
            {
                "SEMANTIC_DEFINITION_MISSING",
                "OPERATOR_UNAVAILABLE",
            },
            set(ltv["reason_codes"]),
        )
        self.assertEqual(
            ["OPERATOR_UNAVAILABLE"],
            ltv["dependencies"]["operators"][0]["reason_codes"],
        )
        self.assertEqual(
            [],
            ltv["dependencies"]["models"][0]["reason_codes"],
        )
        self.assertTrue(
            ltv["dependencies"]["models"][0]["production_claims_allowed"]
        )
        outcome = results["analysis.experiment-outcome-evaluation"]
        self.assertEqual("unknown", outcome["can_run_status"])
        self.assertEqual([], outcome["reason_codes"])
        self.assertEqual(
            0,
            sum(
                result["can_run_status"] == "verified"
                for result in results.values()
            ),
        )
        self.assertTrue(all(not result["network_called"] for result in results.values()))

    def test_non_reference_run_returns_a_structured_zero_network_gap(self):
        result = self.service.run("analysis.event-trend", {})

        self.assertEqual("blocked", result["status"])
        self.assertEqual([], result["findings"])
        self.assertEqual([], result["allowed_claims"])
        self.assertFalse(result["network_called"])

    def test_unknown_identity_fails_before_any_runtime_construction(self):
        with self.assertRaises(InputValidationError):
            self.service.describe("analysis.unknown")


if __name__ == "__main__":
    unittest.main()
