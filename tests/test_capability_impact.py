from __future__ import annotations

import unittest

from gravity_sdk.capability_impact import capability_impact
from gravity_sdk.errors import InputValidationError


def request(selector: str, *, identity_kind: str = "operation"):
    return {
        "schema_version": "gravity.capability-impact-request.v1",
        "changes": [
            {
                "identity_kind": identity_kind,
                "selector": selector,
                "change_kind": "provider_fingerprint_changed",
            }
        ],
    }


class CapabilityImpactTests(unittest.TestCase):
    def test_operation_change_propagates_through_product_skill_and_journey(self):
        result = capability_impact(request("report.multidim.query"))

        self.assertEqual("affected", result["status"])
        self.assertEqual(
            [
                ("operation", "report.multidim.query"),
                ("product", "metric-anomaly-localization@1"),
            ],
            [
                (item["identity_kind"], item["selector"])
                for item in result["affected_capabilities"]
            ],
        )
        self.assertEqual(
            ["skill://gravity.game/ap-cost-anomaly-localization@1.0.0"],
            [item["skill_uri"] for item in result["affected_skills"]],
        )
        self.assertEqual(
            ["analysis.merge2.ap-cost-anomaly-localization"],
            [item["journey_id"] for item in result["affected_journeys"]],
        )
        self.assertFalse(result["network_called"])

    def test_product_and_composite_paths_do_not_cross_inherit(self):
        event = capability_impact(request("analysis.event.query"))
        pulse = capability_impact(
            request("report.overview.query")
        )

        self.assertEqual(
            [
                "analysis.event-trend",
                "analysis.thinkingai.community-context-correlation",
                "analysis.thinkingai.device-segment-event-review",
                "analysis.thinkingai.project-metric-contract-check",
                "analysis.thinkingai.returned-filter-comparison",
            ],
            [item["journey_id"] for item in event["affected_journeys"]],
        )
        self.assertEqual(
            [
                "analysis.business-pulse",
                "analysis.thinkingai.revenue-forecast-readiness",
            ],
            [item["journey_id"] for item in pulse["affected_journeys"]],
        )
        self.assertEqual(
            [
                "skill://gravity.game/analysis-metric-definition-alignment@1.0.0",
                "skill://gravity.game/app-device-performance-analysis@1.0.0",
                "skill://gravity.game/community-hot-topic-analysis@1.0.0",
                "skill://gravity.game/filter-result-bias-diagnosis@1.0.0",
            ],
            [item["skill_uri"] for item in event["affected_skills"]],
        )
        self.assertEqual(
            ["skill://gravity.game/game-revenue-forecast@1.0.0"],
            [item["skill_uri"] for item in pulse["affected_skills"]],
        )

    def test_unknown_identity_is_value_free_and_has_no_invented_dependents(self):
        result = capability_impact(request("fixture.unknown"))

        self.assertIsNone(result["affected_capabilities"][0]["contract_version"])
        self.assertEqual([], result["affected_skills"])
        self.assertEqual([], result["affected_journeys"])
        self.assertEqual(
            {"identity_kind", "selector", "change_kind"},
            set(result["changes"][0]),
        )

    def test_malformed_and_duplicate_changes_fail_closed(self):
        malformed = request("app.list")
        malformed["changes"][0]["change_kind"] = "trust_me"
        with self.assertRaises(InputValidationError):
            capability_impact(malformed)

        duplicate = request("app.list")
        duplicate["changes"].append(dict(duplicate["changes"][0]))
        with self.assertRaises(InputValidationError):
            capability_impact(duplicate)


if __name__ == "__main__":
    unittest.main()
