"""Fail-closed verification for local Stage B offline bundles."""

from __future__ import annotations

from datetime import datetime
from types import MappingProxyType
from typing import Any, Mapping

from .crypto import canonical_json_bytes, sha256_digest, verify_ed25519
from .errors import ControlPlaneVerificationError
from .models import (
    ArtifactEnvelope,
    ArtifactTrustPolicy,
    Digest,
    OfflineBundle,
    OciArtifactRef,
    SignedMetadata,
    TrustedVersions,
    VerifiedArtifact,
    VerifiedBundle,
)
from .tuf import metadata_digest, signed_payload, trusted_now, verify_metadata_set


def verify_offline_bundle(
    bundle: OfflineBundle | Mapping[str, Any],
    *,
    trust_root: SignedMetadata | Mapping[str, Any],
    artifact_policy: ArtifactTrustPolicy,
    trusted_versions: TrustedVersions | None = None,
    now: datetime | None = None,
) -> VerifiedBundle:
    selected_bundle = (
        bundle if isinstance(bundle, OfflineBundle) else OfflineBundle.from_dict(bundle)
    )
    selected_root = (
        trust_root
        if isinstance(trust_root, SignedMetadata)
        else SignedMetadata.from_dict(trust_root)
    )
    if str(selected_bundle.trust_root_digest) != metadata_digest(selected_root):
        _reject("TRUST_ROOT_MISMATCH", "bundle is not bound to the explicit trust root")
    versions = TrustedVersions() if trusted_versions is None else trusted_versions
    verified_metadata = verify_metadata_set(
        selected_root,
        selected_bundle.root_chain,
        selected_bundle.targets,
        selected_bundle.snapshot,
        selected_bundle.timestamp,
        trusted_versions=versions,
        now=trusted_now(now),
    )
    targets, revoked = _targets(verified_metadata.targets)
    envelopes = _unique_envelopes(selected_bundle.artifacts)
    if set(envelopes) != set(targets):
        _reject("OFFLINE_BUNDLE_INCOMPLETE", "bundle and targets do not match exactly")
    artifacts = tuple(
        _verify_artifact(envelopes[name], targets[name], revoked, artifact_policy)
        for name in sorted(envelopes)
    )
    return VerifiedBundle(
        verified_metadata.root.version,
        MappingProxyType(dict(verified_metadata.versions)),
        artifacts,
    )


def artifact_attestation_payload(envelope: ArtifactEnvelope) -> bytes:
    return canonical_json_bytes(envelope.attestation_dict())


def _targets(metadata: SignedMetadata) -> tuple[dict[str, Any], frozenset[str]]:
    payload = signed_payload(metadata, "targets")
    raw_targets = payload["targets"]
    raw_revoked = payload["revoked_digests"]
    if not isinstance(raw_targets, Mapping) or not raw_targets:
        _reject("CONTROL_METADATA_INVALID", "targets must be a non-empty object")
    if not isinstance(raw_revoked, list):
        _reject("CONTROL_METADATA_INVALID", "revocations must be an array")
    revoked = frozenset(
        str(Digest.parse(value, reason="CONTROL_METADATA_INVALID"))
        for value in raw_revoked
    )
    return dict(raw_targets), revoked


def _unique_envelopes(
    artifacts: tuple[ArtifactEnvelope, ...],
) -> dict[str, ArtifactEnvelope]:
    selected = {artifact.target_name: artifact for artifact in artifacts}
    if len(selected) != len(artifacts):
        _reject("OFFLINE_BUNDLE_INVALID", "bundle target names are duplicated")
    return selected


def _verify_artifact(
    envelope: ArtifactEnvelope,
    target: Any,
    revoked: frozenset[str],
    policy: ArtifactTrustPolicy,
) -> VerifiedArtifact:
    expected = OciArtifactRef.from_dict(target)
    if expected != envelope.artifact:
        _reject("MIX_AND_MATCH", "target metadata and artifact descriptor disagree")
    digest = str(envelope.artifact.descriptor.digest)
    if digest in revoked:
        _reject("REVOKED", "artifact digest is revoked")
    _verify_content(envelope)
    _verify_provenance(envelope, policy)
    if envelope.license not in policy.allowed_licenses:
        _reject("LICENSE_DENIED", "artifact license is not allowed")
    identities = _verify_artifact_signatures(envelope, policy)
    return VerifiedArtifact(envelope.target_name, envelope.artifact.reference, identities)


def _verify_content(envelope: ArtifactEnvelope) -> None:
    descriptor = envelope.artifact.descriptor
    if len(envelope.content) != descriptor.size:
        _reject("TAMPERED", "artifact size does not match its descriptor")
    if sha256_digest(envelope.content) != str(descriptor.digest):
        _reject("TAMPERED", "artifact content does not match its digest")


def _verify_provenance(
    envelope: ArtifactEnvelope, policy: ArtifactTrustPolicy
) -> None:
    provenance = envelope.provenance
    if str(provenance.subject_digest) != str(envelope.artifact.descriptor.digest):
        _reject("PROVENANCE_INVALID", "provenance subject does not match artifact")
    if (
        provenance.builder_id not in policy.allowed_builder_ids
        or provenance.source_uri not in policy.allowed_source_uris
        or provenance.predicate_type != policy.required_predicate_type
    ):
        _reject("PROVENANCE_INVALID", "provenance does not satisfy policy")


def _verify_artifact_signatures(
    envelope: ArtifactEnvelope, policy: ArtifactTrustPolicy
) -> tuple[str, ...]:
    payload = artifact_attestation_payload(envelope)
    valid_identities: set[str] = set()
    allowed_keys: set[str] = set()
    cryptographic_signatures = 0
    seen: set[str] = set()
    for signature in envelope.signatures:
        key = policy.keys.get(signature.key_id)
        if key is None or signature.key_id in seen:
            continue
        if signature.algorithm != key.algorithm or not verify_ed25519(
            key.key, payload, signature.value
        ):
            continue
        seen.add(signature.key_id)
        cryptographic_signatures += 1
        if key.identity in policy.allowed_signer_identities:
            allowed_keys.add(key.key_id)
            valid_identities.add(str(key.identity))
    if cryptographic_signatures < policy.signature_threshold:
        _reject("SIGNATURE_THRESHOLD_UNMET", "artifact signature threshold was not met")
    if len(allowed_keys) < policy.signature_threshold:
        _reject("SIGNER_IDENTITY_DENIED", "artifact signer identity is not allowed")
    return tuple(sorted(valid_identities))


def _reject(reason: str, message: str) -> None:
    raise ControlPlaneVerificationError(reason, message)
