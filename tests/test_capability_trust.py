from __future__ import annotations

import copy
from datetime import datetime, timezone
import unittest
from unittest.mock import patch

from gravity_insight.agent_runtime_contracts import canonical_digest
from gravity_insight.capability_contract import capability_contract
from gravity_insight.capability_trust import CapabilityTrustService
from gravity_insight.capability_validation import CapabilityValidationStore
from gravity_insight.data_quality import data_quality_result


NOW = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)


def validation(identity_kind="operation", selector="app.list", **overrides):
    artifact = capability_contract(identity_kind, selector)
    contract = artifact["contract"]
    value = {
        "schema_version": "gravity.capability-validation.v1",
        "identity_kind": identity_kind,
        "selector": selector,
        "contract_version": contract["contract_version"],
        "contract_digest": artifact["digest"],
        "provider_fingerprint": contract["provider"]["fingerprint"],
        "validated_at": "2026-08-22T08:00:00Z",
        "expires_at": "2026-08-23T08:00:00Z",
        "trust_status": "stable",
        "completeness": contract["declared_completeness"],
        "data_quality": data_quality_result(
            [{"check_id": "shape", "status": "pass", "scope": selector}]
        ),
        "evidence_references": [
            {"kind": "fixture", "reference": "fixture://r02/trust"}
        ],
        "reason_codes": [],
    }
    value.update(overrides)
    return value


class CapabilityTrustTests(unittest.TestCase):
    def service(self, *values):
        return CapabilityTrustService(
            CapabilityValidationStore(values=values), clock=lambda: NOW
        )

    def test_current_contracts_are_honestly_unknown_or_blocked(self):
        app = self.service().trust("operation", "app.list")
        event = self.service().trust("product", "analysis.query.spec:event")
        pulse = self.service().trust("composite", "composite:business_pulse")
        reference = self.service().trust("product", "metric-anomaly-localization@1")

        self.assertEqual("unknown", app["trust_status"])
        self.assertEqual(["CAPABILITY_VALIDATION_MISSING"], app["reason_codes"])
        for result in (event, pulse, reference):
            with self.subTest(selector=result["selector"]):
                self.assertEqual("blocked", result["trust_status"])
                self.assertIn("COMPLETENESS_INSUFFICIENT", result["reason_codes"])
                self.assertFalse(result["network_called"])
                self.assertEqual([], result["allowed_claims"])

    @patch.object(CapabilityValidationStore, "for_current_principal")
    def test_default_service_reads_only_the_current_principal_store(self, current):
        current.return_value = CapabilityValidationStore(values=[validation()])

        result = CapabilityTrustService(clock=lambda: NOW).trust(
            "operation", "app.list"
        )

        self.assertEqual("stable", result["trust_status"])
        current.assert_called_once_with()

    def test_valid_current_validation_can_make_one_operation_stable(self):
        result = self.service(validation()).trust("operation", "app.list")

        self.assertEqual("stable", result["trust_status"])
        self.assertEqual("complete", result["completeness"])
        self.assertEqual("pass", result["data_quality"]["status"])
        self.assertRegex(result["validation"]["digest"], r"^[0-9a-f]{64}$")

    def test_expiry_ttl_fingerprint_and_quality_fail_closed(self):
        expired = self.service(
            validation(expires_at="2026-08-22T12:00:00Z")
        ).trust("operation", "app.list")
        oversized = self.service(
            validation(expires_at="2026-08-24T08:00:00Z")
        ).trust("operation", "app.list")
        drift = self.service(
            validation(provider_fingerprint="a" * 64)
        ).trust("operation", "app.list")
        failed_quality = self.service(
            validation(
                data_quality=data_quality_result(
                    [
                        {
                            "check_id": "shape",
                            "status": "fail",
                            "scope": "app.list",
                        }
                    ],
                    reason_codes=["DATA_QUALITY_FAILED"],
                )
            )
        ).trust("operation", "app.list")

        self.assertEqual("unknown", expired["trust_status"])
        self.assertEqual("quarantined", oversized["trust_status"])
        self.assertEqual("quarantined", drift["trust_status"])
        self.assertEqual("blocked", failed_quality["trust_status"])
        self.assertIn("DATA_QUALITY_FAILED", failed_quality["reason_codes"])

    @patch(
        "gravity_insight.capability_contract._product_card_fingerprints",
        return_value={"analysis.query.spec:event": "a" * 64},
    )
    def test_current_product_provider_drift_quarantines(self, _fingerprints):
        result = self.service().trust("product", "analysis.query.spec:event")

        self.assertEqual("quarantined", result["trust_status"])
        self.assertEqual(
            ["CAPABILITY_FINGERPRINT_MISMATCH", "CAPABILITY_VALIDATION_MISSING", "COMPLETENESS_INSUFFICIENT"],
            result["reason_codes"],
        )

    def test_parent_never_inherits_stable_child_validation(self):
        child_contract = _synthetic_contract("operation", "fixture.child")
        parent_contract = _synthetic_contract(
            "product",
            "fixture.parent",
            dependencies=[
                {
                    "identity_kind": "operation",
                    "selector": "fixture.child",
                    "contract_version": "1",
                    "minimum_trust": "stable",
                    "completeness": "complete",
                    "data_quality": "pass",
                }
            ],
        )
        artifacts = {
            ("operation", "fixture.child"): _synthetic_artifact(child_contract),
            ("product", "fixture.parent"): _synthetic_artifact(parent_contract),
        }
        child_validation = _synthetic_validation(artifacts[("operation", "fixture.child")])
        child_only = CapabilityTrustService(
            CapabilityValidationStore(values=[child_validation]),
            contracts=artifacts,
            provider_resolver=lambda contract: contract["provider"]["fingerprint"],
            clock=lambda: NOW,
        ).trust("product", "fixture.parent")
        parent_validation = _synthetic_validation(artifacts[("product", "fixture.parent")])
        both = CapabilityTrustService(
            CapabilityValidationStore(values=[child_validation, parent_validation]),
            contracts=artifacts,
            provider_resolver=lambda contract: contract["provider"]["fingerprint"],
            clock=lambda: NOW,
        ).trust("product", "fixture.parent")

        self.assertEqual("unknown", child_only["trust_status"])
        self.assertEqual("stable", child_only["dependencies"][0]["trust_status"])
        self.assertEqual("stable", both["trust_status"])

    def test_composite_requires_its_own_same_layer_validation(self):
        child_contract = _synthetic_contract("operation", "fixture.component")
        composite_contract = _synthetic_contract(
            "composite",
            "composite:fixture",
            dependencies=[
                {
                    "identity_kind": "operation",
                    "selector": "fixture.component",
                    "contract_version": "1",
                    "minimum_trust": "stable",
                    "completeness": "complete",
                    "data_quality": "pass",
                }
            ],
        )
        artifacts = {
            ("operation", "fixture.component"): _synthetic_artifact(child_contract),
            ("composite", "composite:fixture"): _synthetic_artifact(composite_contract),
        }
        child_validation = _synthetic_validation(
            artifacts[("operation", "fixture.component")]
        )
        result = CapabilityTrustService(
            CapabilityValidationStore(values=[child_validation]),
            contracts=artifacts,
            provider_resolver=lambda contract: contract["provider"]["fingerprint"],
            clock=lambda: NOW,
        ).trust("composite", "composite:fixture")

        self.assertEqual("unknown", result["trust_status"])
        self.assertEqual("stable", result["dependencies"][0]["trust_status"])
        self.assertEqual([], result["allowed_claims"])

    def test_validation_cannot_promote_beyond_declared_completeness(self):
        contract = _synthetic_contract("product", "fixture.unknown-product")
        contract["declared_completeness"] = "unknown"
        artifact = _synthetic_artifact(contract)
        value = _synthetic_validation(artifact)
        service = CapabilityTrustService(
            CapabilityValidationStore(values=[value]),
            contracts={("product", "fixture.unknown-product"): artifact},
            provider_resolver=lambda selected: selected["provider"]["fingerprint"],
            clock=lambda: NOW,
        )

        result = service.trust("product", "fixture.unknown-product")

        self.assertEqual("quarantined", result["trust_status"])
        self.assertEqual(
            ["CAPABILITY_VALIDATION_CONTRADICTS_CONTRACT"],
            result["reason_codes"],
        )
        self.assertEqual("unknown", result["completeness"])

    def test_missing_same_layer_contract_is_blocked(self):
        result = self.service().trust("product", "analysis.query.spec:funnel")

        self.assertEqual("blocked", result["trust_status"])
        self.assertEqual(
            ["CAPABILITY_TRUST_CONTRACT_MISSING"], result["reason_codes"]
        )


def _synthetic_contract(identity_kind, selector, *, dependencies=()):
    return {
        "artifact_kind": "capability",
        "schema_version": "gravity.capability.v1",
        "identity_kind": identity_kind,
        "selector": selector,
        "contract_version": "1",
        "display_name": selector,
        "lifecycle": "active",
        "owner": "tests",
        "effect": "read",
        "privacy_classification": "internal_business",
        "provider": {"kind": "operation_manifest", "fingerprint": "b" * 64},
        "dependencies": list(dependencies),
        "declared_completeness": "complete",
        "required_data_quality": "pass",
        "allowed_claims": ["fixture-observation"],
        "validation_ttl_seconds": 86400,
    }


def _synthetic_artifact(contract):
    return {"contract": copy.deepcopy(contract), "digest": canonical_digest(contract)}


def _synthetic_validation(artifact):
    contract = artifact["contract"]
    return {
        "schema_version": "gravity.capability-validation.v1",
        "identity_kind": contract["identity_kind"],
        "selector": contract["selector"],
        "contract_version": contract["contract_version"],
        "contract_digest": artifact["digest"],
        "provider_fingerprint": contract["provider"]["fingerprint"],
        "validated_at": "2026-08-22T08:00:00Z",
        "expires_at": "2026-08-23T08:00:00Z",
        "trust_status": "stable",
        "completeness": "complete",
        "data_quality": data_quality_result(
            [{"check_id": "shape", "status": "pass", "scope": contract["selector"]}]
        ),
        "evidence_references": [{"kind": "fixture", "reference": "fixture://r02/synthetic"}],
        "reason_codes": [],
    }


if __name__ == "__main__":
    unittest.main()
