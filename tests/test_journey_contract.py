from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest

from gravity_sdk.journey_contract import (
    JourneyContractError,
    journey_artifact,
    journey_artifacts,
    load_journey_contract,
    validate_journey_bindings,
    verify_journey_registry,
)
from gravity_sdk.journey_ledger import load_packaged_journey_ledger


EXPECTED = {
    "analysis.readable-app-catalog",
    "analysis.event-trend",
    "analysis.business-pulse",
    "analysis.merge2.ap-cost-anomaly-localization",
    "analysis.experiment-outcome-evaluation",
    "analysis.ltv-curve-fit",
    "analysis.thinkingai.community-context-correlation",
    "analysis.thinkingai.device-segment-event-review",
    "analysis.thinkingai.project-metric-contract-check",
    "analysis.thinkingai.returned-filter-comparison",
    "analysis.thinkingai.revenue-forecast-readiness",
}


class JourneyContractTests(unittest.TestCase):
    def test_pilot_matrix_has_exact_explicit_display_bindings(self):
        artifacts = journey_artifacts()
        ids = {item["contract"]["journey_id"] for item in artifacts}

        self.assertEqual(EXPECTED, ids)
        self.assertEqual(
            len(artifacts),
            len(
                {
                    item["contract"]["display_binding"]["legacy_display_key"]
                    for item in artifacts
                }
            ),
        )
        for artifact in artifacts:
            contract = artifact["contract"]
            self.assertEqual(
                contract["display_name"],
                contract["display_binding"]["legacy_display_key"],
            )
            self.assertRegex(artifact["digest"], r"^[0-9a-f]{64}$")

    def test_registry_verification_preserves_human_ledger_authority(self):
        result = verify_journey_registry()

        self.assertEqual("valid", result["status"])
        self.assertEqual(69, result["ledger_row_count"])
        self.assertEqual(11, result["machine_contract_count"])
        self.assertFalse(result["network_called"])
        first = next(
            item
            for item in result["bindings"]
            if item["journey_id"] == "analysis.event-trend"
        )
        self.assertEqual("已闭环", first["ledger_status"])

    def test_r01_and_expected_model_gap_remain_explicit(self):
        reference = journey_artifact(
            "analysis.merge2.ap-cost-anomaly-localization"
        )["contract"]
        ltv = journey_artifact("analysis.ltv-curve-fit")["contract"]

        self.assertEqual(
            "metric-anomaly-localization@1",
            reference["required_capabilities"][0]["selector"],
        )
        self.assertTrue(reference["project_contract_path"].endswith(".json"))
        self.assertEqual("unavailable", ltv["execution"]["mode"])
        self.assertTrue(ltv["required_operators"])
        self.assertTrue(ltv["required_models"])
        self.assertTrue(all(value == "missing" for value in ltv["surfaces"].values()))

        outcome = journey_artifact("analysis.experiment-outcome-evaluation")["contract"]
        self.assertEqual("unavailable", outcome["execution"]["mode"])
        self.assertEqual(
            ["operator://gravity/significance-test@1"],
            outcome["required_operators"],
        )
        self.assertTrue(
            all(value == "missing" for value in outcome["surfaces"].values())
        )

    def test_schema_display_and_surface_contradictions_fail_closed(self):
        source = journey_artifact("analysis.event-trend")["contract"]
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "journey.json"
            malformed = copy.deepcopy(source)
            malformed["unexpected"] = True
            path.write_text(json.dumps(malformed), encoding="utf-8")
            with self.assertRaises(JourneyContractError):
                load_journey_contract(path)

        contradictory = copy.deepcopy(source)
        contradictory["surfaces"]["cli"] = "missing"
        with self.assertRaises(JourneyContractError):
            validate_journey_bindings(
                [contradictory], load_packaged_journey_ledger()
            )


if __name__ == "__main__":
    unittest.main()
