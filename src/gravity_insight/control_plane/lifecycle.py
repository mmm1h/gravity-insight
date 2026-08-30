"""Pure Stage B lifecycle decisions for an external Installer to execute."""

from __future__ import annotations

from typing import Any, Mapping

from .errors import ControlPlaneVerificationError
from .models import ArtifactTrustPolicy, OfflineBundle, SignedMetadata, TrustedVersions
from .update_models import (
    ArtifactPin,
    ExecutionSnapshot,
    InstallerContract,
    InstallerEvidence,
    JourneySnapshotBinding,
    REQUIRED_OFFLINE_GATES,
    SnapshotDecision,
    TrustPolicyBinding,
    UpdatePlan,
)
from .verification import verify_offline_bundle


def resolve_update_plan(
    bundle: OfflineBundle | Mapping[str, Any],
    *,
    trust_root: SignedMetadata | Mapping[str, Any],
    artifact_policy: ArtifactTrustPolicy,
    current_snapshot: ExecutionSnapshot,
    artifact_versions: Mapping[str, str],
    artifact_kinds: Mapping[str, str],
    target_environment: str,
    trusted_versions: TrustedVersions | None = None,
    now: Any = None,
) -> UpdatePlan:
    """Verify local material and freeze one exact, compatible Update Plan."""

    selected = bundle if isinstance(bundle, OfflineBundle) else OfflineBundle.from_dict(bundle)
    verified = verify_offline_bundle(
        selected,
        trust_root=trust_root,
        artifact_policy=artifact_policy,
        trusted_versions=trusted_versions,
        now=now,
    )
    envelopes = {artifact.target_name: artifact for artifact in selected.artifacts}
    verified_by_name = {artifact.target_name: artifact for artifact in verified.artifacts}
    names = set(envelopes)
    if names != set(artifact_versions) or names != set(artifact_kinds):
        _reject("UPDATE_ARTIFACT_SET_INCOMPLETE", "artifact metadata is not exact")
    pins = tuple(
        _artifact_pin(
            envelopes[name],
            verified_by_name[name],
            artifact_versions[name],
            artifact_kinds[name],
        )
        for name in sorted(names)
    )
    candidate = ExecutionSnapshot.create(
        compatibility_tag=current_snapshot.compatibility_tag,
        artifacts=pins,
        journey_gates=current_snapshot.journey_gates,
    )
    return UpdatePlan.create(
        current_snapshot=current_snapshot,
        candidate_snapshot=candidate,
        rollback_snapshot=current_snapshot,
        trust_policy=_policy_binding(artifact_policy),
        installer=InstallerContract("external-installer", target_environment),
    )


def bind_journey_snapshot(
    journey_id: str, active_snapshot: ExecutionSnapshot
) -> JourneySnapshotBinding:
    if not journey_id or journey_id != journey_id.strip():
        _reject("JOURNEY_BINDING_INVALID", "journey id is invalid")
    return JourneySnapshotBinding(journey_id, active_snapshot)


def decide_activation(
    plan: UpdatePlan,
    evidence: InstallerEvidence,
    active_snapshot: ExecutionSnapshot,
) -> SnapshotDecision:
    """Return an atomic switch decision; never perform the switch."""

    if active_snapshot != plan.current_snapshot:
        return _denied(active_snapshot, "ACTIVATION_PLAN_STALE")
    if evidence.plan_id != plan.plan_id:
        return _denied(active_snapshot, "INSTALLER_EVIDENCE_MISMATCH")
    expected = tuple(artifact.digest for artifact in plan.candidate_snapshot.artifacts)
    evidence_sets = (
        evidence.downloaded_digests,
        evidence.verified_digests,
        evidence.staged_digests,
    )
    if any(not _exact_set(values, expected) for values in evidence_sets):
        return _denied(active_snapshot, "PARTIAL_ARTIFACT_SET")
    if not _exact_set(evidence.passed_offline_gates, REQUIRED_OFFLINE_GATES):
        return _denied(active_snapshot, "OFFLINE_GATE_FAILED")
    if evidence.canary_passed is not True:
        return _denied(active_snapshot, "CANARY_FAILED")
    return SnapshotDecision("activation_allowed", plan.candidate_snapshot)


def decide_rollback(
    plan: UpdatePlan,
    active_snapshot: ExecutionSnapshot,
    available_digests: tuple[str, ...],
) -> SnapshotDecision:
    """Allow rollback only to the prior complete frozen snapshot."""

    if active_snapshot != plan.candidate_snapshot:
        return _denied(active_snapshot, "ROLLBACK_PLAN_STALE")
    expected = tuple(artifact.digest for artifact in plan.rollback_snapshot.artifacts)
    if not _exact_set(available_digests, expected):
        return _denied(active_snapshot, "ROLLBACK_SNAPSHOT_INCOMPLETE")
    return SnapshotDecision("rollback_allowed", plan.rollback_snapshot)


def _artifact_pin(
    envelope: Any, verified: Any, version: str, artifact_kind: str
) -> ArtifactPin:
    provenance = envelope.provenance
    descriptor = envelope.artifact.descriptor
    return ArtifactPin(
        name=envelope.target_name,
        artifact_kind=artifact_kind,
        version=version,
        reference=verified.reference,
        digest=str(descriptor.digest),
        size=descriptor.size,
        signer_identities=verified.signer_identities,
        builder_id=provenance.builder_id,
        source_uri=provenance.source_uri,
        predicate_type=provenance.predicate_type,
        license=envelope.license,
    )


def _policy_binding(policy: ArtifactTrustPolicy) -> TrustPolicyBinding:
    return TrustPolicyBinding(
        signature_threshold=policy.signature_threshold,
        signer_identities=tuple(sorted(policy.allowed_signer_identities)),
        builder_ids=tuple(sorted(policy.allowed_builder_ids)),
        source_uris=tuple(sorted(policy.allowed_source_uris)),
        predicate_type=policy.required_predicate_type,
        licenses=tuple(sorted(policy.allowed_licenses)),
    )


def _exact_set(actual: tuple[str, ...], expected: tuple[str, ...]) -> bool:
    return len(actual) == len(expected) and set(actual) == set(expected)


def _denied(active: ExecutionSnapshot, reason: str) -> SnapshotDecision:
    return SnapshotDecision("activation_denied", active, reason)


def _reject(reason: str, message: str) -> None:
    raise ControlPlaneVerificationError(reason, message)
