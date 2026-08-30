from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from gravity_insight.capability_contract import (
    CapabilityContractError,
    capability_contract,
    capability_contracts,
    current_provider_fingerprint,
    load_declared_capability_contract,
)


class CapabilityContractTests(unittest.TestCase):
    def test_operations_and_explicit_upper_layers_have_separate_contracts(self):
        operations = [
            item
            for item in capability_contracts()
            if item["contract"]["identity_kind"] == "operation"
        ]
        app = capability_contract("operation", "app.list")
        event = capability_contract("product", "analysis.query.spec:event")
        pulse = capability_contract("composite", "composite:business_pulse")

        self.assertGreater(len(operations), 200)
        self.assertEqual("complete", app["contract"]["declared_completeness"])
        self.assertEqual("unknown", event["contract"]["declared_completeness"])
        self.assertEqual("unknown", pulse["contract"]["declared_completeness"])
        self.assertEqual(
            "analysis.event.query",
            event["contract"]["dependencies"][0]["selector"],
        )

    def test_provider_fingerprints_are_current_and_missing_cards_do_not_inherit(self):
        for identity in (
            ("operation", "app.list"),
            ("product", "analysis.query.spec:event"),
            ("composite", "composite:business_pulse"),
            ("product", "metric-anomaly-localization@1"),
        ):
            with self.subTest(identity=identity):
                artifact = capability_contract(*identity)
                self.assertEqual(
                    artifact["contract"]["provider"]["fingerprint"],
                    current_provider_fingerprint(artifact["contract"]),
                )
        self.assertIsNone(
            capability_contract("product", "analysis.query.spec:funnel")
        )

    def test_declared_contract_schema_and_operation_shadowing_fail_closed(self):
        artifact = capability_contract("product", "analysis.query.spec:event")
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "capability.json"
            value = dict(artifact["contract"])
            value["unexpected"] = True
            path.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaises(CapabilityContractError):
                load_declared_capability_contract(path)

            operation = dict(capability_contract("operation", "app.list")["contract"])
            path.write_text(json.dumps(operation), encoding="utf-8")
            with self.assertRaises(CapabilityContractError):
                load_declared_capability_contract(path)


if __name__ == "__main__":
    unittest.main()
