from __future__ import annotations

import copy
import unittest

from gravity_sdk.control_plane.errors import ControlPlaneVerificationError
from gravity_sdk.control_plane.verification import verify_offline_bundle
from tests.test_control_plane_fixtures import (
    NOW,
    build_fixture,
    resign_metadata,
)


class ControlPlaneTufTests(unittest.TestCase):
    def test_offline_bundle_verifies_from_explicit_root(self) -> None:
        fixture = build_fixture("valid")
        result = self._verify(fixture)
        self.assertEqual(1, result.root_version)
        self.assertEqual(
            {"root": 1, "targets": 2, "snapshot": 4, "timestamp": 8},
            dict(result.metadata_versions),
        )

    def test_explicit_trust_root_mismatch_is_rejected(self) -> None:
        self._assert_fixture_rejected("trust-root-mismatch")

    def test_consecutive_dual_threshold_root_rotation_verifies(self) -> None:
        fixture = build_fixture("root-rotation")
        result = self._verify(fixture)
        self.assertEqual(2, result.root_version)

    def test_rotated_root_requires_previous_root_threshold(self) -> None:
        fixture = build_fixture("root-rotation")
        bundle = copy.deepcopy(fixture.bundle)
        signatures = bundle["root_chain"][0]["signatures"]
        bundle["root_chain"][0]["signatures"] = [signatures[1]]
        self._assert_rejected(fixture, "SIGNATURE_THRESHOLD_UNMET", bundle)

    def test_rotated_root_requires_new_root_threshold(self) -> None:
        fixture = build_fixture("root-rotation")
        bundle = copy.deepcopy(fixture.bundle)
        signatures = bundle["root_chain"][0]["signatures"]
        bundle["root_chain"][0]["signatures"] = [signatures[0]]
        self._assert_rejected(fixture, "SIGNATURE_THRESHOLD_UNMET", bundle)

    def test_rollback_fixture_is_rejected(self) -> None:
        self._assert_fixture_rejected("rollback")

    def test_freeze_fixture_is_rejected(self) -> None:
        self._assert_fixture_rejected("freeze")

    def test_mix_and_match_fixture_is_rejected(self) -> None:
        self._assert_fixture_rejected("mix-and-match")

    def test_expired_fixture_is_rejected(self) -> None:
        self._assert_fixture_rejected("expired")

    def test_metadata_threshold_failure_is_rejected(self) -> None:
        fixture = build_fixture("valid")
        bundle = copy.deepcopy(fixture.bundle)
        bundle["timestamp"]["signatures"] = []
        self._assert_rejected(fixture, "SIGNATURE_THRESHOLD_UNMET", bundle)

    def test_signed_metadata_tampering_is_rejected(self) -> None:
        fixture = build_fixture("valid")
        bundle = copy.deepcopy(fixture.bundle)
        bundle["snapshot"]["signed"]["expires"] = "2031-01-01T00:00:00Z"
        self._assert_rejected(fixture, "SIGNATURE_THRESHOLD_UNMET", bundle)

    def test_root_rotation_cannot_skip_a_version(self) -> None:
        fixture = build_fixture("root-rotation")
        bundle = copy.deepcopy(fixture.bundle)
        rotated = bundle["root_chain"][0]
        rotated["signed"]["version"] = 3
        bundle["root_chain"][0] = resign_metadata(rotated, "root-old", "root-new")
        self._assert_rejected(fixture, "ROLLBACK", bundle)

    def _verify(self, fixture: object) -> object:
        return verify_offline_bundle(
            fixture.bundle,
            trust_root=fixture.trust_root,
            artifact_policy=fixture.policy,
            trusted_versions=fixture.trusted_versions,
            now=NOW,
        )

    def _assert_fixture_rejected(self, name: str) -> None:
        fixture = build_fixture(name)
        self._assert_rejected(fixture, fixture.case["expected_reason"], fixture.bundle)

    def _assert_rejected(self, fixture: object, reason: str, bundle: object) -> None:
        with self.assertRaises(ControlPlaneVerificationError) as raised:
            verify_offline_bundle(
                bundle,
                trust_root=fixture.trust_root,
                artifact_policy=fixture.policy,
                trusted_versions=fixture.trusted_versions,
                now=NOW,
            )
        self.assertEqual(reason, raised.exception.reason_code)
