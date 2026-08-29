"""Immutable Stage B update, snapshot, and external Installer contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .crypto import canonical_json_bytes, sha256_digest
from .errors import ControlPlaneVerificationError


UPDATE_STEPS = (
    "resolve",
    "download",
    "verify",
    "stage",
    "offline-gate",
    "canary",
    "activation-plan",
    "external-activation",
    "rollback",
)
REQUIRED_OFFLINE_GATES = (
    "artifact-digest",
    "metadata-freshness",
    "provenance",
    "revocation",
    "signature",
    "snapshot-compatibility",
)


@dataclass(frozen=True)
class ArtifactPin:
    name: str
    artifact_kind: str
    version: str
    reference: str
    digest: str
    size: int
    signer_identities: tuple[str, ...]
    builder_id: str
    source_uri: str
    predicate_type: str
    license: str

    def __post_init__(self) -> None:
        texts = (
            self.name,
            self.artifact_kind,
            self.version,
            self.reference,
            self.digest,
            self.builder_id,
            self.source_uri,
            self.predicate_type,
            self.license,
        )
        if (
            any(not value or value != value.strip() for value in texts)
            or not self.reference.endswith(self.digest)
            or not self.digest.startswith("sha256:")
            or self.size < 0
            or not self.signer_identities
            or len(set(self.signer_identities)) != len(self.signer_identities)
        ):
            _invalid("UPDATE_ARTIFACT_INVALID", "artifact pin is incomplete")

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_kind": self.artifact_kind,
            "builder_id": self.builder_id,
            "digest": self.digest,
            "license": self.license,
            "name": self.name,
            "predicate_type": self.predicate_type,
            "reference": self.reference,
            "signer_identities": list(self.signer_identities),
            "size": self.size,
            "source_uri": self.source_uri,
            "version": self.version,
        }


@dataclass(frozen=True)
class ExecutionSnapshot:
    snapshot_id: str
    compatibility_tag: str
    artifacts: tuple[ArtifactPin, ...]
    journey_gates: tuple[str, ...]

    @classmethod
    def create(
        cls,
        *,
        compatibility_tag: str,
        artifacts: tuple[ArtifactPin, ...],
        journey_gates: tuple[str, ...],
    ) -> "ExecutionSnapshot":
        body = _snapshot_body(compatibility_tag, artifacts, journey_gates)
        snapshot_id = sha256_digest(canonical_json_bytes(_snapshot_payload(**body)))
        return cls(snapshot_id, **body)

    def __post_init__(self) -> None:
        body = _snapshot_body(
            self.compatibility_tag, self.artifacts, self.journey_gates
        )
        payload = _snapshot_payload(**body)
        if self.snapshot_id != sha256_digest(canonical_json_bytes(payload)):
            _invalid("SNAPSHOT_DIGEST_INVALID", "execution snapshot digest differs")

    def to_dict(self) -> dict[str, Any]:
        return {"snapshot_id": self.snapshot_id, **_snapshot_dict(self)}


@dataclass(frozen=True)
class TrustPolicyBinding:
    signature_threshold: int
    signer_identities: tuple[str, ...]
    builder_ids: tuple[str, ...]
    source_uris: tuple[str, ...]
    predicate_type: str
    licenses: tuple[str, ...]

    def __post_init__(self) -> None:
        collections = (
            self.signer_identities,
            self.builder_ids,
            self.source_uris,
            self.licenses,
        )
        if (
            self.signature_threshold < 1
            or any(not values or len(set(values)) != len(values) for values in collections)
            or not self.predicate_type
        ):
            _invalid("UPDATE_POLICY_INVALID", "trust policy binding is incomplete")

    def to_dict(self) -> dict[str, Any]:
        return {
            "builder_ids": list(self.builder_ids),
            "licenses": list(self.licenses),
            "predicate_type": self.predicate_type,
            "signature_threshold": self.signature_threshold,
            "signer_identities": list(self.signer_identities),
            "source_uris": list(self.source_uris),
        }


@dataclass(frozen=True)
class InstallerContract:
    owner: str
    target_environment: str
    activation_mode: str = "atomic-complete-snapshot"
    runtime_mutation: str = "forbidden"
    project_lock_mutation: str = "external-only"

    def __post_init__(self) -> None:
        if (
            self.owner != "external-installer"
            or not self.target_environment
            or self.activation_mode != "atomic-complete-snapshot"
            or self.runtime_mutation != "forbidden"
            or self.project_lock_mutation != "external-only"
        ):
            _invalid("INSTALLER_CONTRACT_INVALID", "installer boundary is invalid")

    def to_dict(self) -> dict[str, str]:
        return {
            "activation_mode": self.activation_mode,
            "owner": self.owner,
            "project_lock_mutation": self.project_lock_mutation,
            "runtime_mutation": self.runtime_mutation,
            "target_environment": self.target_environment,
        }


@dataclass(frozen=True)
class UpdatePlan:
    plan_id: str
    current_snapshot: ExecutionSnapshot
    candidate_snapshot: ExecutionSnapshot
    rollback_snapshot: ExecutionSnapshot
    trust_policy: TrustPolicyBinding
    installer: InstallerContract
    lifecycle: tuple[str, ...] = UPDATE_STEPS
    offline_gates: tuple[str, ...] = REQUIRED_OFFLINE_GATES

    @classmethod
    def create(
        cls,
        *,
        current_snapshot: ExecutionSnapshot,
        candidate_snapshot: ExecutionSnapshot,
        rollback_snapshot: ExecutionSnapshot,
        trust_policy: TrustPolicyBinding,
        installer: InstallerContract,
    ) -> "UpdatePlan":
        values = {
            "current_snapshot": current_snapshot,
            "candidate_snapshot": candidate_snapshot,
            "rollback_snapshot": rollback_snapshot,
            "trust_policy": trust_policy,
            "installer": installer,
        }
        plan_id = sha256_digest(canonical_json_bytes(_plan_body(**values)))
        return cls(plan_id=plan_id, **values)

    def __post_init__(self) -> None:
        body = _plan_body(
            current_snapshot=self.current_snapshot,
            candidate_snapshot=self.candidate_snapshot,
            rollback_snapshot=self.rollback_snapshot,
            trust_policy=self.trust_policy,
            installer=self.installer,
        )
        compatible = {
            self.current_snapshot.compatibility_tag,
            self.candidate_snapshot.compatibility_tag,
            self.rollback_snapshot.compatibility_tag,
        }
        if (
            self.plan_id != sha256_digest(canonical_json_bytes(body))
            or self.lifecycle != UPDATE_STEPS
            or self.offline_gates != REQUIRED_OFFLINE_GATES
            or len(compatible) != 1
            or self.rollback_snapshot != self.current_snapshot
            or self.candidate_snapshot == self.current_snapshot
        ):
            _invalid("UPDATE_PLAN_INVALID", "update plan is stale or incompatible")

    def to_dict(self) -> dict[str, Any]:
        return {"plan_id": self.plan_id, **_plan_body(
            current_snapshot=self.current_snapshot,
            candidate_snapshot=self.candidate_snapshot,
            rollback_snapshot=self.rollback_snapshot,
            trust_policy=self.trust_policy,
            installer=self.installer,
        )}


@dataclass(frozen=True)
class UpdatePlanRequest:
    request_id: str
    current_version: str
    target_version: str
    target_environment: str
    distribution: str = "gravity-insight"

    @classmethod
    def create(
        cls, *, current_version: str, target_version: str, target_environment: str
    ) -> "UpdatePlanRequest":
        values = {
            "current_version": current_version,
            "target_version": target_version,
            "target_environment": target_environment,
        }
        request_id = sha256_digest(canonical_json_bytes(_request_body(**values)))
        return cls(request_id=request_id, **values)

    def to_dict(self) -> dict[str, Any]:
        values = {
            "current_version": self.current_version,
            "target_version": self.target_version,
            "target_environment": self.target_environment,
        }
        if self.request_id != sha256_digest(canonical_json_bytes(_request_body(**values))):
            _invalid("UPDATE_PLAN_REQUEST_INVALID", "plan request digest differs")
        return {"request_id": self.request_id, **_request_body(**values)}


@dataclass(frozen=True)
class InstallerEvidence:
    plan_id: str
    downloaded_digests: tuple[str, ...]
    verified_digests: tuple[str, ...]
    staged_digests: tuple[str, ...]
    passed_offline_gates: tuple[str, ...]
    canary_passed: bool


@dataclass(frozen=True)
class SnapshotDecision:
    status: str
    active_snapshot: ExecutionSnapshot
    reason_code: str | None = None


@dataclass(frozen=True)
class JourneySnapshotBinding:
    journey_id: str
    snapshot: ExecutionSnapshot


def _snapshot_body(
    compatibility_tag: str,
    artifacts: tuple[ArtifactPin, ...],
    journey_gates: tuple[str, ...],
) -> dict[str, Any]:
    if (
        not compatibility_tag
        or not artifacts
        or not journey_gates
        or len({artifact.name for artifact in artifacts}) != len(artifacts)
        or len(set(journey_gates)) != len(journey_gates)
    ):
        _invalid("SNAPSHOT_INVALID", "execution snapshot is incomplete")
    return {
        "artifacts": tuple(sorted(artifacts, key=lambda item: item.name)),
        "compatibility_tag": compatibility_tag,
        "journey_gates": tuple(sorted(journey_gates)),
    }


def _snapshot_dict(snapshot: ExecutionSnapshot) -> dict[str, Any]:
    return _snapshot_payload(
        compatibility_tag=snapshot.compatibility_tag,
        artifacts=snapshot.artifacts,
        journey_gates=snapshot.journey_gates,
    )


def _snapshot_payload(
    *,
    compatibility_tag: str,
    artifacts: tuple[ArtifactPin, ...],
    journey_gates: tuple[str, ...],
) -> dict[str, Any]:
    return {
        "artifacts": [artifact.to_dict() for artifact in artifacts],
        "compatibility_tag": compatibility_tag,
        "journey_gates": list(journey_gates),
    }


def _plan_body(
    *,
    current_snapshot: ExecutionSnapshot,
    candidate_snapshot: ExecutionSnapshot,
    rollback_snapshot: ExecutionSnapshot,
    trust_policy: TrustPolicyBinding,
    installer: InstallerContract,
) -> dict[str, Any]:
    return {
        "candidate_snapshot": candidate_snapshot.to_dict(),
        "current_snapshot": current_snapshot.to_dict(),
        "installer": installer.to_dict(),
        "lifecycle": list(UPDATE_STEPS),
        "offline_gates": list(REQUIRED_OFFLINE_GATES),
        "rollback_snapshot": rollback_snapshot.to_dict(),
        "schema_version": "gravity.control-plane-update-plan.v1",
        "trust_policy": trust_policy.to_dict(),
    }


def _request_body(
    *, current_version: str, target_version: str, target_environment: str
) -> dict[str, Any]:
    if not current_version or not target_version or not target_environment:
        _invalid("UPDATE_PLAN_REQUEST_INVALID", "plan request is incomplete")
    return {
        "activation_owner": "external-installer",
        "artifact": f"gravity-insight=={target_version}",
        "current_version": current_version,
        "lifecycle": list(UPDATE_STEPS),
        "required_plan_schema": "gravity.control-plane-update-plan.v1",
        "required_verification": list(REQUIRED_OFFLINE_GATES),
        "runtime_environment_mutation": "forbidden",
        "schema_version": "gravity.control-plane-update-plan-request.v1",
        "target_environment": target_environment,
        "target_version": target_version,
    }


def _invalid(reason: str, message: str) -> None:
    raise ControlPlaneVerificationError(reason, message)
