"""Immutable models for OCI artifacts, attestations, and signed metadata."""

from __future__ import annotations

import base64
import binascii
import copy
from dataclasses import dataclass, field
import re
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from .crypto import HMAC_SHA256
from .errors import ControlPlaneVerificationError


_MEDIA_TYPE = re.compile(r"[a-z0-9][a-z0-9!#$&^_.+-]*/[a-z0-9][a-z0-9!#$&^_.+-]*")
_REPOSITORY_SEGMENT = re.compile(r"[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?")


@dataclass(frozen=True)
class Digest:
    algorithm: str
    value: str

    @classmethod
    def parse(cls, value: Any, *, reason: str = "OCI_DESCRIPTOR_INVALID") -> "Digest":
        if not isinstance(value, str) or ":" not in value:
            _invalid(reason, "digest must be an algorithm-prefixed string")
        algorithm, encoded = value.split(":", 1)
        if algorithm != "sha256" or len(encoded) != 64 or not _lower_hex(encoded):
            _invalid(reason, "only canonical sha256 digests are supported")
        return cls(algorithm, encoded)

    def __str__(self) -> str:
        return f"{self.algorithm}:{self.value}"


@dataclass(frozen=True)
class OciDescriptor:
    digest: Digest
    media_type: str
    size: int

    @classmethod
    def from_dict(cls, value: Any) -> "OciDescriptor":
        selected = _object(value, "OCI_DESCRIPTOR_INVALID", "OCI descriptor")
        _fields(
            selected,
            {"digest", "media_type", "size"},
            "OCI_DESCRIPTOR_INVALID",
            "OCI descriptor",
        )
        media_type = _text(
            selected["media_type"], "OCI_DESCRIPTOR_INVALID", "media type"
        )
        if _MEDIA_TYPE.fullmatch(media_type) is None:
            _invalid("OCI_DESCRIPTOR_INVALID", "media type is not canonical")
        size = selected["size"]
        if type(size) is not int or size < 0:
            _invalid("OCI_DESCRIPTOR_INVALID", "size must be a non-negative integer")
        return cls(Digest.parse(selected["digest"]), media_type, size)

    def to_dict(self) -> dict[str, Any]:
        return {
            "digest": str(self.digest),
            "media_type": self.media_type,
            "size": self.size,
        }


@dataclass(frozen=True)
class OciArtifactRef:
    repository: str
    descriptor: OciDescriptor

    @classmethod
    def from_dict(cls, value: Any) -> "OciArtifactRef":
        selected = _object(value, "OCI_REFERENCE_INVALID", "OCI artifact")
        _fields(
            selected,
            {"repository", "descriptor"},
            "OCI_REFERENCE_INVALID",
            "OCI artifact",
        )
        repository = _repository(selected["repository"])
        return cls(repository, OciDescriptor.from_dict(selected["descriptor"]))

    @property
    def reference(self) -> str:
        return f"{self.repository}@{self.descriptor.digest}"

    def to_dict(self) -> dict[str, Any]:
        return {"repository": self.repository, "descriptor": self.descriptor.to_dict()}


@dataclass(frozen=True)
class Signature:
    key_id: str
    algorithm: str
    value: str

    @classmethod
    def from_dict(cls, value: Any) -> "Signature":
        selected = _object(value, "SIGNATURE_INVALID", "signature")
        _fields(
            selected,
            {"key_id", "algorithm", "value"},
            "SIGNATURE_INVALID",
            "signature",
        )
        key_id = _text(selected["key_id"], "SIGNATURE_INVALID", "key id")
        algorithm = _text(selected["algorithm"], "SIGNATURE_INVALID", "algorithm")
        signature = _text(selected["value"], "SIGNATURE_INVALID", "signature")
        if algorithm != HMAC_SHA256 or not _lower_hex(signature, length=64):
            _invalid("SIGNATURE_INVALID", "signature algorithm or encoding is invalid")
        return cls(key_id, algorithm, signature)

    def to_dict(self) -> dict[str, str]:
        return {"key_id": self.key_id, "algorithm": self.algorithm, "value": self.value}


@dataclass(frozen=True)
class VerificationKey:
    key_id: str
    algorithm: str
    key: bytes = field(repr=False)
    identity: str | None = None

    def __post_init__(self) -> None:
        if (
            not self.key_id
            or self.algorithm != HMAC_SHA256
            or len(self.key) < 16
            or (self.identity is not None and not self.identity)
        ):
            _invalid("TRUST_ROOT_INVALID", "verification key is invalid")

    @classmethod
    def from_dict(
        cls, key_id: str, value: Any, *, identity_required: bool = False
    ) -> "VerificationKey":
        selected = _object(value, "TRUST_ROOT_INVALID", "verification key")
        allowed = {"algorithm", "key", "identity"}
        required = allowed if identity_required else {"algorithm", "key"}
        _fields(selected, required, "TRUST_ROOT_INVALID", "verification key", allowed)
        algorithm = _text(selected["algorithm"], "TRUST_ROOT_INVALID", "algorithm")
        if algorithm != HMAC_SHA256:
            _invalid("TRUST_ROOT_INVALID", "unsupported verification algorithm")
        raw = _base64(selected["key"], "TRUST_ROOT_INVALID", "verification key")
        if len(raw) < 16:
            _invalid("TRUST_ROOT_INVALID", "verification key is too short")
        identity_value = selected.get("identity")
        identity = None
        if identity_value is not None:
            identity = _text(identity_value, "TRUST_ROOT_INVALID", "signer identity")
        if identity_required and identity is None:
            _invalid("TRUST_ROOT_INVALID", "signer identity is required")
        return cls(key_id, algorithm, raw, identity)


@dataclass(frozen=True)
class Provenance:
    subject_digest: Digest
    builder_id: str
    source_uri: str
    predicate_type: str

    @classmethod
    def from_dict(cls, value: Any) -> "Provenance":
        selected = _object(value, "PROVENANCE_INVALID", "provenance")
        required = {"subject_digest", "builder_id", "source_uri", "predicate_type"}
        _fields(selected, required, "PROVENANCE_INVALID", "provenance")
        return cls(
            Digest.parse(selected["subject_digest"], reason="PROVENANCE_INVALID"),
            _text(selected["builder_id"], "PROVENANCE_INVALID", "builder id"),
            _text(selected["source_uri"], "PROVENANCE_INVALID", "source URI"),
            _text(selected["predicate_type"], "PROVENANCE_INVALID", "predicate type"),
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "subject_digest": str(self.subject_digest),
            "builder_id": self.builder_id,
            "source_uri": self.source_uri,
            "predicate_type": self.predicate_type,
        }


@dataclass(frozen=True)
class ArtifactEnvelope:
    target_name: str
    artifact: OciArtifactRef
    content: bytes = field(repr=False)
    signatures: tuple[Signature, ...]
    provenance: Provenance
    license: str

    @classmethod
    def from_dict(cls, value: Any) -> "ArtifactEnvelope":
        selected = _object(value, "OFFLINE_BUNDLE_INVALID", "artifact envelope")
        required = {
            "target_name", "artifact", "content", "signatures", "provenance", "license"
        }
        _fields(selected, required, "OFFLINE_BUNDLE_INVALID", "artifact envelope")
        signatures = _sequence(selected["signatures"], "SIGNATURE_INVALID", "signatures")
        if not signatures:
            _invalid("SIGNATURE_INVALID", "artifact has no signatures")
        return cls(
            _target_name(selected["target_name"]),
            OciArtifactRef.from_dict(selected["artifact"]),
            _base64(selected["content"], "OFFLINE_BUNDLE_INVALID", "artifact content"),
            tuple(Signature.from_dict(item) for item in signatures),
            Provenance.from_dict(selected["provenance"]),
            _text(selected["license"], "LICENSE_DENIED", "license"),
        )

    def attestation_dict(self) -> dict[str, Any]:
        return {
            "artifact": self.artifact.to_dict(),
            "license": self.license,
            "provenance": self.provenance.to_dict(),
            "target_name": self.target_name,
        }


@dataclass(frozen=True)
class SignedMetadata:
    signed: Mapping[str, Any]
    signatures: tuple[Signature, ...]

    @classmethod
    def from_dict(cls, value: Any) -> "SignedMetadata":
        selected = _object(value, "CONTROL_METADATA_INVALID", "signed metadata")
        _fields(
            selected,
            {"signed", "signatures"},
            "CONTROL_METADATA_INVALID",
            "signed metadata",
        )
        signed = _object(
            selected["signed"], "CONTROL_METADATA_INVALID", "signed metadata payload"
        )
        signatures = _sequence(
            selected["signatures"], "CONTROL_METADATA_INVALID", "metadata signatures"
        )
        if not signatures:
            _invalid("SIGNATURE_THRESHOLD_UNMET", "metadata has no signatures")
        return cls(copy.deepcopy(signed), tuple(Signature.from_dict(item) for item in signatures))

    def to_dict(self) -> dict[str, Any]:
        return {
            "signed": copy.deepcopy(dict(self.signed)),
            "signatures": [signature.to_dict() for signature in self.signatures],
        }


@dataclass(frozen=True)
class OfflineBundle:
    trust_root_digest: Digest
    root_chain: tuple[SignedMetadata, ...]
    targets: SignedMetadata
    snapshot: SignedMetadata
    timestamp: SignedMetadata
    artifacts: tuple[ArtifactEnvelope, ...]

    @classmethod
    def from_dict(cls, value: Any) -> "OfflineBundle":
        selected = _object(value, "OFFLINE_BUNDLE_INVALID", "offline bundle")
        required = {
            "trust_root_digest", "root_chain", "targets", "snapshot", "timestamp", "artifacts"
        }
        _fields(selected, required, "OFFLINE_BUNDLE_INVALID", "offline bundle")
        roots = _sequence(selected["root_chain"], "OFFLINE_BUNDLE_INVALID", "root chain")
        artifacts = _sequence(selected["artifacts"], "OFFLINE_BUNDLE_INVALID", "artifacts")
        if not artifacts:
            _invalid("OFFLINE_BUNDLE_INVALID", "offline bundle has no artifacts")
        return cls(
            Digest.parse(selected["trust_root_digest"], reason="TRUST_ROOT_MISMATCH"),
            tuple(SignedMetadata.from_dict(item) for item in roots),
            SignedMetadata.from_dict(selected["targets"]),
            SignedMetadata.from_dict(selected["snapshot"]),
            SignedMetadata.from_dict(selected["timestamp"]),
            tuple(ArtifactEnvelope.from_dict(item) for item in artifacts),
        )


@dataclass(frozen=True)
class ArtifactTrustPolicy:
    keys: Mapping[str, VerificationKey]
    allowed_signer_identities: frozenset[str]
    signature_threshold: int
    allowed_builder_ids: frozenset[str]
    allowed_source_uris: frozenset[str]
    allowed_licenses: frozenset[str]
    required_predicate_type: str

    def __post_init__(self) -> None:
        keys = dict(self.keys)
        if not keys or any(key_id != key.key_id for key_id, key in keys.items()):
            _invalid("ARTIFACT_POLICY_INVALID", "artifact verification keys are invalid")
        sets = (
            self.allowed_signer_identities,
            self.allowed_builder_ids,
            self.allowed_source_uris,
            self.allowed_licenses,
        )
        if (
            self.signature_threshold < 1
            or self.signature_threshold > len(keys)
            or any(not values for values in sets)
            or any(
                not isinstance(key, VerificationKey)
                or key.identity is None
                for key in keys.values()
            )
        ):
            _invalid("ARTIFACT_POLICY_INVALID", "artifact trust policy is incomplete")
        object.__setattr__(self, "keys", MappingProxyType(keys))
        object.__setattr__(self, "allowed_signer_identities", frozenset(sets[0]))
        object.__setattr__(self, "allowed_builder_ids", frozenset(sets[1]))
        object.__setattr__(self, "allowed_source_uris", frozenset(sets[2]))
        object.__setattr__(self, "allowed_licenses", frozenset(sets[3]))
        _text(self.required_predicate_type, "ARTIFACT_POLICY_INVALID", "predicate type")


@dataclass(frozen=True)
class TrustedVersions:
    minimum: Mapping[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        allowed = {"root", "targets", "snapshot", "timestamp"}
        selected = dict(self.minimum)
        if any(role not in allowed or type(version) is not int or version < 1 for role, version in selected.items()):
            _invalid("TRUSTED_VERSIONS_INVALID", "trusted metadata versions are invalid")
        object.__setattr__(self, "minimum", MappingProxyType(selected))


@dataclass(frozen=True)
class VerifiedArtifact:
    target_name: str
    reference: str
    signer_identities: tuple[str, ...]


@dataclass(frozen=True)
class VerifiedBundle:
    root_version: int
    metadata_versions: Mapping[str, int]
    artifacts: tuple[VerifiedArtifact, ...]
    network_requests: int = 0


def _object(value: Any, reason: str, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        _invalid(reason, f"{label} must be an object")
    return dict(value)


def _sequence(value: Any, reason: str, label: str) -> list[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        _invalid(reason, f"{label} must be an array")
    return list(value)


def _fields(
    value: Mapping[str, Any],
    required: set[str],
    reason: str,
    label: str,
    allowed: set[str] | None = None,
) -> None:
    permitted = required if allowed is None else allowed
    if not required.issubset(value) or not set(value).issubset(permitted):
        _invalid(reason, f"{label} fields are invalid")


def _text(value: Any, reason: str, label: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        _invalid(reason, f"{label} must be non-empty normalized text")
    return value


def _base64(value: Any, reason: str, label: str) -> bytes:
    if not isinstance(value, str) or not value:
        _invalid(reason, f"{label} must be base64 text")
    try:
        return base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ControlPlaneVerificationError(reason, f"{label} is not valid base64") from exc


def _repository(value: Any) -> str:
    selected = _text(value, "OCI_REFERENCE_INVALID", "repository")
    segments = selected.split("/")
    host = segments[0].split(":", 1)
    valid_port = len(host) == 1 or (len(host) == 2 and host[1].isdigit())
    path = [host[0], *segments[1:]]
    if (
        "@" in selected
        or selected != selected.lower()
        or not valid_port
        or any(_REPOSITORY_SEGMENT.fullmatch(part) is None for part in path)
    ):
        _invalid("OCI_REFERENCE_INVALID", "repository is not a normalized OCI name")
    return selected


def _target_name(value: Any) -> str:
    selected = _text(value, "OFFLINE_BUNDLE_INVALID", "target name")
    parts = selected.split("/")
    if "\\" in selected or selected.startswith("/") or any(part in {"", ".", ".."} for part in parts):
        _invalid("OFFLINE_BUNDLE_INVALID", "target name is not normalized")
    return selected


def _lower_hex(value: str, *, length: int | None = None) -> bool:
    if length is not None and len(value) != length:
        return False
    return bool(value) and all(character in "0123456789abcdef" for character in value)


def _invalid(reason: str, message: str) -> None:
    raise ControlPlaneVerificationError(reason, message)
