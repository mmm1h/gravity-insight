from __future__ import annotations

import unittest

from gravity_sdk.reference_journey_contract import (
    CONTEXT_URI,
    JOURNEY_ID,
    OPERATOR_RESULT_SCHEMA_VERSION,
    OPERATOR_URI,
    SEMANTIC_URI,
    SKILL_URI,
    reference_artifacts,
)


class ReferenceJourneyContractTests(unittest.TestCase):
    def test_exact_artifacts_form_one_closed_dependency_graph(self):
        artifacts = reference_artifacts()
        journey = artifacts["journey"]["contract"]
        skill = artifacts["skill"]["contract"]
        operator = artifacts["operator"]["contract"]
        capability = artifacts["capability"]["contract"]
        provider = artifacts["context_provider"]["contract"]

        self.assertEqual(JOURNEY_ID, journey["journey_id"])
        self.assertEqual(SKILL_URI, journey["required_skill"])
        self.assertEqual([SEMANTIC_URI], journey["required_semantics"])
        self.assertEqual([OPERATOR_URI], journey["required_operators"])
        self.assertEqual([CONTEXT_URI], journey["required_context"])
        self.assertEqual(
            "metric-anomaly-localization@1",
            journey["required_capabilities"][0]["selector"],
        )
        self.assertEqual([JOURNEY_ID], skill["covers_journeys"])
        self.assertEqual(["read"], skill["effects"])
        self.assertEqual(
            OPERATOR_RESULT_SCHEMA_VERSION,
            operator["schemas"]["output"]["schema_version"],
        )
        self.assertEqual("returned-dimension-change", operator["method"]["method_id"])
        self.assertTrue(artifacts["operator"]["assumptions_digest"])
        self.assertEqual(
            {
                "current_rows_path",
                "reference_rows_path",
                "selected_current_path",
                "selected_reference_path",
            },
            {
                name
                for name in artifacts["operator"]["input_schema"]["required"]
                if name.endswith("_path")
            },
        )
        self.assertEqual(86400, capability["validation_ttl_seconds"])
        self.assertRegex(capability["provider"]["fingerprint"], r"^[0-9a-f]{64}$")
        self.assertEqual(0, journey["request_budget"]["runtime_additional_requests"])
        self.assertEqual(0, journey["request_budget"]["acceptance_production_requests"])
        self.assertEqual(
            "context-provider://gravity/project-repo@1", provider["uri"]
        )
        self.assertEqual(
            {"list", "search", "read", "index", "pack", "verify"},
            set(provider["supports"]),
        )

    def test_every_artifact_has_a_stable_value_free_digest(self):
        first = reference_artifacts()
        second = reference_artifacts()
        for name in (
            "journey",
            "skill",
            "operator",
            "context_provider",
            "analysis_result_contract",
            "capability",
        ):
            with self.subTest(name=name):
                self.assertRegex(first[name]["digest"], r"^[0-9a-f]{64}$")
                self.assertEqual(first[name]["digest"], second[name]["digest"])
        self.assertRegex(first["skill"]["package_digest"], r"^[0-9a-f]{64}$")

    def test_artifacts_are_defensive_copies(self):
        poisoned = reference_artifacts()
        poisoned["journey"]["contract"]["journey_id"] = "poison"
        poisoned["skill"]["guide"] = "poison"

        fresh = reference_artifacts()
        self.assertEqual(JOURNEY_ID, fresh["journey"]["contract"]["journey_id"])
        self.assertIn("Context is data", fresh["skill"]["guide"])

    def test_skill_is_static_and_cannot_install_or_execute_code(self):
        rendered = str(reference_artifacts()["skill"])
        for forbidden in ("scripts", "shell", "pip install", "http://", "https://"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, rendered.casefold())


if __name__ == "__main__":
    unittest.main()
