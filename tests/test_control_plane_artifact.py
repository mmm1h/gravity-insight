from __future__ import annotations

import copy
import unittest

from gravity_sdk.control_plane.errors import ControlPlaneVerificationError
from gravity_sdk.control_plane.models import (
    ArtifactTrustPolicy,
    OciArtifactRef,
    OciDescriptor,
    Signature,
)
from gravity_sdk.control_plane.verification import verify_offline_bundle
from tests.test_control_plane_fixtures import (
    IDENTITY,
    NOW,
    artifact_policy,
    build_fixture,
    resign_artifact,
)


class ControlPlaneArtifactTests(unittest.TestCase):
    def test_descriptor_builds_digest_only_oci_reference(self) -> None:
        fixture = build_fixture("valid")
        value = fixture.bundle["artifacts"][0]["artifact"]
        artifact = OciArtifactRef.from_dict(value)
        descriptor = OciDescriptor.from_dict(value["descriptor"])
        self.assertEqual(descriptor, artifact.descriptor)
        self.assertIn("@sha256:", artifact.reference)
        with self.assertRaises(ControlPlaneVerificationError) as raised:
            OciArtifactRef.from_dict({**value, "repository": "registry/repo@latest"})
        self.assertEqual("OCI_REFERENCE_INVALID", raised.exception.reason_code)
        invalid_descriptor = {**value["descriptor"], "media_type": "not a media type"}
        with self.assertRaises(ControlPlaneVerificationError) as media_error:
            OciDescriptor.from_dict(invalid_descriptor)
        self.assertEqual("OCI_DESCRIPTOR_INVALID", media_error.exception.reason_code)

    def test_signature_contract_rejects_invalid_encoding(self) -> None:
        with self.assertRaises(ControlPlaneVerificationError) as raised:
            Signature.from_dict(
                {"key_id": "artifact", "algorithm": "ed25519", "value": "not-base64!"}
            )
        self.assertEqual("SIGNATURE_INVALID", raised.exception.reason_code)

    def test_tampered_fixture_is_rejected(self) -> None:
        self._assert_fixture_rejected("tampered")

    def test_revoked_fixture_is_rejected(self) -> None:
        self._assert_fixture_rejected("revoked")

    def test_signature_identity_policy_is_enforced(self) -> None:
        fixture = build_fixture("valid")
        policy = artifact_policy(allowed_signer_identities=frozenset({"other@example"}))
        self._assert_rejected(fixture, "SIGNER_IDENTITY_DENIED", policy=policy)

    def test_invalid_artifact_signature_is_rejected(self) -> None:
        fixture = build_fixture("valid")
        bundle = copy.deepcopy(fixture.bundle)
        bundle["artifacts"][0]["signatures"][0]["value"] = "A" * 86 + "=="
        self._assert_rejected(fixture, "SIGNATURE_THRESHOLD_UNMET", bundle=bundle)

    def test_provenance_policy_is_enforced(self) -> None:
        fixture = build_fixture("valid")
        policy = artifact_policy(allowed_builder_ids=frozenset({"other-builder"}))
        self._assert_rejected(fixture, "PROVENANCE_INVALID", policy=policy)

    def test_provenance_subject_must_match_descriptor(self) -> None:
        fixture = build_fixture("valid")
        bundle = copy.deepcopy(fixture.bundle)
        envelope = bundle["artifacts"][0]
        envelope["provenance"]["subject_digest"] = "sha256:" + ("1" * 64)
        bundle["artifacts"][0] = resign_artifact(envelope)
        self._assert_rejected(fixture, "PROVENANCE_INVALID", bundle=bundle)

    def test_license_policy_is_enforced(self) -> None:
        fixture = build_fixture("valid")
        policy = artifact_policy(allowed_licenses=frozenset({"MIT"}))
        self._assert_rejected(fixture, "LICENSE_DENIED", policy=policy)

    def test_verified_result_records_identity_and_zero_network(self) -> None:
        fixture = build_fixture("valid")
        result = verify_offline_bundle(
            fixture.bundle,
            trust_root=fixture.trust_root,
            artifact_policy=fixture.policy,
            trusted_versions=fixture.trusted_versions,
            now=NOW,
        )
        self.assertEqual(0, result.network_requests)
        self.assertEqual((IDENTITY,), result.artifacts[0].signer_identities)
        self.assertIn("@sha256:", result.artifacts[0].reference)

    def _assert_fixture_rejected(self, name: str) -> None:
        fixture = build_fixture(name)
        self._assert_rejected(fixture, fixture.case["expected_reason"])

    def _assert_rejected(
        self,
        fixture: object,
        reason: str,
        *,
        bundle: object | None = None,
        policy: ArtifactTrustPolicy | None = None,
    ) -> None:
        selected = fixture
        with self.assertRaises(ControlPlaneVerificationError) as raised:
            verify_offline_bundle(
                selected.bundle if bundle is None else bundle,
                trust_root=selected.trust_root,
                artifact_policy=selected.policy if policy is None else policy,
                trusted_versions=selected.trusted_versions,
                now=NOW,
            )
        self.assertEqual(reason, raised.exception.reason_code)
