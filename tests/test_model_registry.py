from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from gravity_insight.model_contract import ModelContractError, compile_model_artifact
from gravity_insight.model_registry import ModelRegistry
from gravity_insight.operator_ids import RETURNED_DIMENSION_CHANGE_URI


MODEL_URI = "model://project/ltv-curve@1"


def model_artifact(**overrides):
    value = {
        "artifact_kind": "model",
        "schema_version": "gravity.model-artifact.v1",
        "uri": MODEL_URI,
        "version": 1,
        "alias": "ltv-curve",
        "owner": "model-risk",
        "lifecycle": "active",
        "operator_uri": RETURNED_DIMENSION_CHANGE_URI,
        "artifact": {"kind": "parameters", "digest": "1" * 64},
        "lineage": {
            "fitting_window": {"start": "2026-01-01", "end": "2026-06-30"},
            "data_uris": ["metric://project/ltv@1"],
            "source_digests": ["2" * 64],
            "sample_count": 1000,
        },
        "evaluation": {
            "status": "validated",
            "evaluated_at": "2026-07-01",
            "expires_at": "2026-12-31",
            "metrics": [
                {"name": "coverage", "value": 0.95, "threshold": 0.9, "passed": True}
            ],
        },
        "safe_domain": {
            "horizon_days": 30,
            "minimum_samples": 100,
            "units": ["currency"],
        },
        "approval": {
            "status": "approved",
            "approved_by": "model-risk-board",
            "approved_at": "2026-07-02",
        },
        "claim_policy": {
            "validated": ["validated forecast interval"],
            "scenario": ["scenario projection"],
            "forbidden": ["causal claim"],
        },
    }
    value.update(overrides)
    return value


def trusted_registry(artifact):
    digest = compile_model_artifact(artifact)["digest"]
    return ModelRegistry([artifact], trusted_artifact_digests=[digest])


class ModelRegistryTests(unittest.TestCase):
    def test_runtime_ships_no_model_and_missing_is_explicit(self) -> None:
        registry = ModelRegistry()
        self.assertEqual(0, registry.list()["count"])

        result = registry.evaluate(MODEL_URI, at="2026-08-22", horizon_days=7)
        self.assertEqual("missing", result["status"])
        self.assertEqual(["MODEL_UNVALIDATED"], result["reason_codes"])
        self.assertFalse(result["production_claims_allowed"])
        self.assertEqual([], result["allowed_claims"])
        self.assertFalse(result["network_called"])
        self.assertFalse(hasattr(registry, "predict"))

    def test_valid_artifact_allows_only_validated_claims_within_safe_domain(self) -> None:
        registry = trusted_registry(model_artifact())
        result = registry.evaluate(
            MODEL_URI, at="2026-08-22", horizon_days=30, unit="currency"
        )

        self.assertEqual("approved", result["status"])
        self.assertTrue(result["production_claims_allowed"])
        self.assertEqual(["validated forecast interval"], result["allowed_claims"])
        self.assertEqual(["causal claim"], result["forbidden_claims"])
        self.assertRegex(result["model"]["lineage_digest"], r"^[0-9a-f]{64}$")
        self.assertRegex(result["model"]["evaluation_digest"], r"^[0-9a-f]{64}$")

    def test_self_declared_local_approval_is_not_source_trust(self) -> None:
        result = ModelRegistry([model_artifact()]).evaluate(
            MODEL_URI, at="2026-08-22", horizon_days=7, unit="currency"
        )
        self.assertEqual("blocked", result["status"])
        self.assertEqual(["MODEL_SOURCE_UNTRUSTED"], result["reason_codes"])
        self.assertFalse(result["production_claims_allowed"])
        self.assertEqual(["scenario projection"], result["allowed_claims"])

    def test_lifecycle_evaluation_horizon_unit_sample_and_operator_gates(self) -> None:
        cases = []

        unapproved = model_artifact()
        unapproved["approval"] = {
            "status": "unapproved",
            "approved_by": None,
            "approved_at": None,
        }
        cases.append((unapproved, {}, "MODEL_UNAPPROVED"))

        unvalidated = model_artifact()
        unvalidated["evaluation"] = {
            "status": "unvalidated",
            "evaluated_at": None,
            "expires_at": None,
            "metrics": [],
        }
        cases.append((unvalidated, {}, "MODEL_UNVALIDATED"))

        revoked = model_artifact(lifecycle="revoked")
        cases.append((revoked, {}, "MODEL_REVOKED"))
        cases.append((model_artifact(), {"at": "2027-01-01"}, "MODEL_EXPIRED"))
        cases.append(
            (model_artifact(), {"at": "2026-07-01"}, "MODEL_NOT_YET_APPROVED")
        )
        cases.append((model_artifact(), {"horizon_days": 31}, "MODEL_HORIZON_UNSAFE"))
        cases.append((model_artifact(), {"unit": "count"}, "MODEL_UNIT_UNSUPPORTED"))

        undersampled = model_artifact()
        undersampled["lineage"]["sample_count"] = 99
        cases.append((undersampled, {}, "MODEL_SAMPLE_INSUFFICIENT"))

        missing_operator = model_artifact(operator_uri="operator://gravity/not-installed@1")
        cases.append((missing_operator, {}, "MODEL_OPERATOR_UNAVAILABLE"))

        for artifact, scope, reason in cases:
            with self.subTest(reason=reason):
                result = trusted_registry(artifact).evaluate(
                    MODEL_URI,
                    at=scope.get("at", "2026-08-22"),
                    horizon_days=scope.get("horizon_days", 7),
                    unit=scope.get("unit", "currency"),
                )
                self.assertEqual("blocked", result["status"])
                self.assertIn(reason, result["reason_codes"])
                self.assertFalse(result["production_claims_allowed"])
                self.assertEqual(["scenario projection"], result["allowed_claims"])

    def test_failed_calibration_is_recorded_but_never_approved(self) -> None:
        failed = model_artifact()
        failed["evaluation"] = {
            "status": "failed",
            "evaluated_at": "2026-07-01",
            "expires_at": None,
            "metrics": [
                {"name": "coverage", "value": 0.7, "threshold": 0.9, "passed": False}
            ],
        }
        result = trusted_registry(failed).evaluate(MODEL_URI, at="2026-08-22")
        self.assertEqual(["MODEL_UNVALIDATED"], result["reason_codes"])
        self.assertFalse(result["production_claims_allowed"])

    def test_identity_lineage_evaluation_approval_and_claim_drift_fail(self) -> None:
        cases = []
        identity = model_artifact(version=2)
        cases.append((identity, "MODEL_IDENTITY_INVALID"))

        lineage = model_artifact()
        lineage["lineage"]["fitting_window"] = {
            "start": "2026-07-01",
            "end": "2026-06-01",
        }
        cases.append((lineage, "MODEL_LINEAGE_INVALID"))

        evaluation = model_artifact()
        evaluation["evaluation"]["metrics"][0]["passed"] = False
        cases.append((evaluation, "MODEL_EVALUATION_INVALID"))

        approval = model_artifact()
        approval["approval"]["approved_by"] = None
        cases.append((approval, "MODEL_APPROVAL_INVALID"))

        early_approval = model_artifact()
        early_approval["approval"]["approved_at"] = "2026-06-01"
        cases.append((early_approval, "MODEL_APPROVAL_INVALID"))

        claims = model_artifact()
        claims["claim_policy"]["forbidden"].append("scenario projection")
        cases.append((claims, "MODEL_CLAIM_CONFLICT"))

        for artifact, reason in cases:
            with self.subTest(reason=reason), self.assertRaisesRegex(
                ModelContractError, reason
            ):
                compile_model_artifact(artifact)

    def test_digest_is_deterministic_and_duplicate_identity_conflicts(self) -> None:
        artifact = model_artifact()
        reordered = {key: copy.deepcopy(artifact[key]) for key in reversed(artifact)}
        self.assertEqual(
            compile_model_artifact(artifact)["digest"],
            compile_model_artifact(reordered)["digest"],
        )
        with self.assertRaisesRegex(ModelContractError, "MODEL_IDENTITY_CONFLICT"):
            ModelRegistry([artifact, copy.deepcopy(artifact)])
        alias = model_artifact(uri="model://project/ltv-curve-second@2", version=2)
        with self.assertRaisesRegex(ModelContractError, "MODEL_ALIAS_CONFLICT"):
            ModelRegistry([artifact, alias])

    def test_explicit_json_source_and_registry_are_offline(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.json"
            path.write_text(json.dumps(model_artifact()), encoding="utf-8")
            with patch("socket.socket", side_effect=AssertionError("network attempted")):
                artifact = model_artifact()
                registry = ModelRegistry(
                    [path],
                    trusted_artifact_digests=[compile_model_artifact(artifact)["digest"]],
                )
                result = registry.evaluate(MODEL_URI, at="2026-08-22")
        self.assertTrue(result["ok"])
        self.assertFalse(result["network_called"])


if __name__ == "__main__":
    unittest.main()
