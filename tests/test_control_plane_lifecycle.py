from __future__ import annotations

import copy
import unittest

from gravity_insight.control_plane.errors import ControlPlaneVerificationError
from gravity_insight.control_plane.lifecycle import (
    bind_journey_snapshot,
    decide_activation,
    decide_rollback,
    resolve_update_plan,
)
from gravity_insight.control_plane.update_models import (
    ArtifactPin,
    ExecutionSnapshot,
    InstallerEvidence,
    REQUIRED_OFFLINE_GATES,
    UPDATE_STEPS,
)
from tests.test_control_plane_fixtures import (
    BUILDER,
    IDENTITY,
    LICENSE,
    NOW,
    PREDICATE,
    SOURCE,
    build_fixture,
)


class ControlPlaneLifecycleTests(unittest.TestCase):
    def test_resolve_freezes_exact_verified_snapshot_and_installer_contract(self) -> None:
        plan = self._plan()
        fixture = build_fixture("valid")
        envelope = fixture.bundle["artifacts"][0]
        artifact = plan.candidate_snapshot.artifacts[0]
        rendered = plan.to_dict()

        self.assertEqual(tuple(UPDATE_STEPS), plan.lifecycle)
        self.assertEqual(plan.current_snapshot, plan.rollback_snapshot)
        self.assertEqual(envelope["artifact"]["descriptor"]["digest"], artifact.digest)
        self.assertEqual((IDENTITY,), artifact.signer_identities)
        self.assertEqual((BUILDER, SOURCE, PREDICATE), (
            artifact.builder_id, artifact.source_uri, artifact.predicate_type
        ))
        self.assertEqual("external-installer", rendered["installer"]["owner"])
        self.assertEqual("forbidden", rendered["installer"]["runtime_mutation"])
        self.assertEqual("external-only", rendered["installer"]["project_lock_mutation"])

    def test_tampered_artifact_cannot_produce_an_update_plan(self) -> None:
        fixture = build_fixture("tampered")
        with self.assertRaises(ControlPlaneVerificationError) as raised:
            self._resolve(fixture)
        self.assertEqual("TAMPERED", raised.exception.reason_code)

    def test_provenance_policy_failure_cannot_produce_an_update_plan(self) -> None:
        fixture = build_fixture("valid")
        policy = fixture.policy.__class__(
            keys=fixture.policy.keys,
            allowed_signer_identities=fixture.policy.allowed_signer_identities,
            signature_threshold=fixture.policy.signature_threshold,
            allowed_builder_ids=frozenset({"other-builder"}),
            allowed_source_uris=fixture.policy.allowed_source_uris,
            allowed_licenses=fixture.policy.allowed_licenses,
            required_predicate_type=fixture.policy.required_predicate_type,
        )
        fixture = fixture.__class__(
            fixture.case, fixture.bundle, fixture.trust_root, policy, fixture.trusted_versions
        )
        with self.assertRaises(ControlPlaneVerificationError) as raised:
            self._resolve(fixture)
        self.assertEqual("PROVENANCE_INVALID", raised.exception.reason_code)

    def test_plan_rejects_incomplete_artifact_metadata(self) -> None:
        fixture = build_fixture("valid")
        with self.assertRaises(ControlPlaneVerificationError) as raised:
            resolve_update_plan(
                fixture.bundle,
                trust_root=fixture.trust_root,
                artifact_policy=fixture.policy,
                current_snapshot=self._current_snapshot(),
                artifact_versions={},
                artifact_kinds={},
                target_environment="C:/external/gravity/python.exe",
                trusted_versions=fixture.trusted_versions,
                now=NOW,
            )
        self.assertEqual("UPDATE_ARTIFACT_SET_INCOMPLETE", raised.exception.reason_code)

    def test_partial_artifact_set_never_becomes_active(self) -> None:
        plan = self._plan()
        evidence = self._evidence(plan, staged_digests=())
        decision = decide_activation(plan, evidence, plan.current_snapshot)
        self.assertEqual("PARTIAL_ARTIFACT_SET", decision.reason_code)
        self.assertEqual(plan.current_snapshot, decision.active_snapshot)

    def test_canary_failure_leaves_prior_complete_snapshot_active(self) -> None:
        plan = self._plan()
        evidence = self._evidence(plan, canary_passed=False)
        decision = decide_activation(plan, evidence, plan.current_snapshot)
        self.assertEqual("CANARY_FAILED", decision.reason_code)
        self.assertEqual(plan.current_snapshot, decision.active_snapshot)

    def test_complete_external_evidence_allows_only_the_candidate_snapshot(self) -> None:
        plan = self._plan()
        decision = decide_activation(
            plan, self._evidence(plan), plan.current_snapshot
        )
        self.assertEqual("activation_allowed", decision.status)
        self.assertEqual(plan.candidate_snapshot, decision.active_snapshot)

    def test_rollback_targets_the_prior_complete_snapshot(self) -> None:
        plan = self._plan()
        digests = tuple(item.digest for item in plan.rollback_snapshot.artifacts)
        decision = decide_rollback(plan, plan.candidate_snapshot, digests)
        self.assertEqual("rollback_allowed", decision.status)
        self.assertEqual(plan.current_snapshot, decision.active_snapshot)

    def test_incomplete_rollback_does_not_replace_the_candidate_snapshot(self) -> None:
        plan = self._plan()
        decision = decide_rollback(plan, plan.candidate_snapshot, ())
        self.assertEqual("ROLLBACK_SNAPSHOT_INCOMPLETE", decision.reason_code)
        self.assertEqual(plan.candidate_snapshot, decision.active_snapshot)

    def test_in_flight_journey_finishes_on_its_frozen_snapshot(self) -> None:
        plan = self._plan()
        binding = bind_journey_snapshot("analysis.reference", plan.current_snapshot)
        decision = decide_activation(
            plan, self._evidence(plan), plan.current_snapshot
        )
        self.assertEqual(plan.candidate_snapshot, decision.active_snapshot)
        self.assertEqual(plan.current_snapshot, binding.snapshot)
        self.assertNotEqual(binding.snapshot.snapshot_id, decision.active_snapshot.snapshot_id)

    def test_stale_activation_evidence_fails_closed(self) -> None:
        plan = self._plan()
        evidence = self._evidence(plan)
        stale = copy.copy(evidence)
        object.__setattr__(stale, "plan_id", "sha256:" + ("0" * 64))
        decision = decide_activation(plan, stale, plan.current_snapshot)
        self.assertEqual("INSTALLER_EVIDENCE_MISMATCH", decision.reason_code)
        self.assertEqual(plan.current_snapshot, decision.active_snapshot)

    def _plan(self):
        return self._resolve(build_fixture("valid"))

    def _resolve(self, fixture):
        return resolve_update_plan(
            fixture.bundle,
            trust_root=fixture.trust_root,
            artifact_policy=fixture.policy,
            current_snapshot=self._current_snapshot(),
            artifact_versions={"runtime/gravity_insight.whl": "99.0.0"},
            artifact_kinds={"runtime/gravity_insight.whl": "runtime-wheel"},
            target_environment="C:/external/gravity/python.exe",
            trusted_versions=fixture.trusted_versions,
            now=NOW,
        )

    def _current_snapshot(self):
        digest = "sha256:" + ("1" * 64)
        artifact = ArtifactPin(
            name="runtime/gravity_insight.whl",
            artifact_kind="runtime-wheel",
            version="0.4.0",
            reference=f"registry.example/gravity/runtime@{digest}",
            digest=digest,
            size=32,
            signer_identities=(IDENTITY,),
            builder_id=BUILDER,
            source_uri=SOURCE,
            predicate_type=PREDICATE,
            license=LICENSE,
        )
        return ExecutionSnapshot.create(
            compatibility_tag="gravity-runtime-v1",
            artifacts=(artifact,),
            journey_gates=("analysis.reference",),
        )

    def _evidence(self, plan, *, staged_digests=None, canary_passed=True):
        digests = tuple(item.digest for item in plan.candidate_snapshot.artifacts)
        return InstallerEvidence(
            plan_id=plan.plan_id,
            downloaded_digests=digests,
            verified_digests=digests,
            staged_digests=digests if staged_digests is None else staged_digests,
            passed_offline_gates=REQUIRED_OFFLINE_GATES,
            canary_passed=canary_passed,
        )


if __name__ == "__main__":
    unittest.main()
