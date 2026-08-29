"""TUF-style threshold metadata verification and trust-root rotation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from .crypto import canonical_json_bytes, sha256_digest, verify_ed25519
from .errors import ControlPlaneVerificationError
from .models import Digest, SignedMetadata, TrustedVersions, VerificationKey


ROLES = frozenset({"root", "targets", "snapshot", "timestamp"})


@dataclass(frozen=True)
class RoleSpec:
    key_ids: frozenset[str]
    threshold: int


@dataclass(frozen=True)
class RootView:
    metadata: SignedMetadata
    version: int
    keys: Mapping[str, VerificationKey]
    roles: Mapping[str, RoleSpec]


@dataclass(frozen=True)
class VerifiedMetadataSet:
    root: RootView
    targets: SignedMetadata
    snapshot: SignedMetadata
    timestamp: SignedMetadata
    versions: Mapping[str, int]


def metadata_digest(metadata: SignedMetadata) -> str:
    return sha256_digest(canonical_json_bytes(metadata.to_dict()))


def verify_metadata_set(
    explicit_root: SignedMetadata,
    root_chain: Sequence[SignedMetadata],
    targets: SignedMetadata,
    snapshot: SignedMetadata,
    timestamp: SignedMetadata,
    *,
    trusted_versions: TrustedVersions,
    now: datetime,
) -> VerifiedMetadataSet:
    current = verify_root_chain(
        explicit_root, root_chain, trusted_versions=trusted_versions, now=now
    )
    versions = {"root": current.version}
    for role, metadata in (
        ("targets", targets),
        ("snapshot", snapshot),
        ("timestamp", timestamp),
    ):
        version = _verify_role(
            metadata,
            role,
            current,
            trusted_versions=trusted_versions,
            now=now,
        )
        versions[role] = version
    _verify_link(timestamp, "snapshot.json", snapshot)
    _verify_link(snapshot, "targets.json", targets)
    return VerifiedMetadataSet(current, targets, snapshot, timestamp, versions)


def verify_root_chain(
    explicit_root: SignedMetadata,
    root_chain: Sequence[SignedMetadata],
    *,
    trusted_versions: TrustedVersions,
    now: datetime,
) -> RootView:
    current = _root_view(explicit_root)
    _verify_threshold(explicit_root, current.roles["root"], current.keys)
    _check_expiry(explicit_root, "root", now)
    for candidate_metadata in root_chain:
        candidate = _root_view(candidate_metadata)
        if candidate.version != current.version + 1:
            _reject("ROLLBACK", "root rotation is not a consecutive version")
        _verify_threshold(candidate_metadata, current.roles["root"], current.keys)
        _verify_threshold(candidate_metadata, candidate.roles["root"], candidate.keys)
        _check_expiry(candidate_metadata, "root", now)
        current = candidate
    _check_rollback("root", current.version, trusted_versions)
    return current


def signed_payload(metadata: SignedMetadata, role: str) -> Mapping[str, Any]:
    selected = dict(metadata.signed)
    expected = _role_fields(role)
    if set(selected) != expected or selected.get("_type") != role:
        _reject("CONTROL_METADATA_INVALID", f"{role} metadata fields are invalid")
    _version(selected, role)
    _expires(selected, role)
    return selected


def trusted_now(value: datetime | None) -> datetime:
    selected = datetime.now(timezone.utc) if value is None else value
    if selected.tzinfo is None or selected.utcoffset() is None:
        _reject("VERIFICATION_TIME_INVALID", "verification time must be timezone-aware")
    return selected.astimezone(timezone.utc)


def _verify_role(
    metadata: SignedMetadata,
    role: str,
    root: RootView,
    *,
    trusted_versions: TrustedVersions,
    now: datetime,
) -> int:
    payload = signed_payload(metadata, role)
    _verify_threshold(metadata, root.roles[role], root.keys)
    version = _version(payload, role)
    _check_rollback(role, version, trusted_versions)
    _check_expiry(metadata, role, now)
    return version


def _root_view(metadata: SignedMetadata) -> RootView:
    payload = signed_payload(metadata, "root")
    raw_keys = _mapping(payload["keys"], "root keys")
    raw_roles = _mapping(payload["roles"], "root roles")
    if set(raw_roles) != ROLES or not raw_keys:
        _reject("TRUST_ROOT_INVALID", "root must define all four roles and keys")
    keys = {
        key_id: VerificationKey.from_dict(key_id, value)
        for key_id, value in raw_keys.items()
        if isinstance(key_id, str) and key_id
    }
    if len(keys) != len(raw_keys):
        _reject("TRUST_ROOT_INVALID", "root key ids are invalid")
    roles = {
        role: _role_spec(raw_roles[role], role, keys)
        for role in sorted(ROLES)
    }
    return RootView(metadata, _version(payload, "root"), keys, roles)


def _role_spec(
    value: Any, role: str, keys: Mapping[str, VerificationKey]
) -> RoleSpec:
    selected = _mapping(value, f"{role} role")
    if set(selected) != {"key_ids", "threshold"}:
        _reject("TRUST_ROOT_INVALID", f"{role} role fields are invalid")
    raw_ids = _array(selected["key_ids"], f"{role} key ids")
    key_ids = frozenset(raw_ids)
    threshold = selected["threshold"]
    if (
        len(key_ids) != len(raw_ids)
        or not key_ids
        or any(not isinstance(key_id, str) or key_id not in keys for key_id in key_ids)
        or type(threshold) is not int
        or threshold < 1
        or threshold > len(key_ids)
    ):
        _reject("TRUST_ROOT_INVALID", f"{role} threshold policy is invalid")
    return RoleSpec(key_ids, threshold)


def _verify_threshold(
    metadata: SignedMetadata,
    role: RoleSpec,
    keys: Mapping[str, VerificationKey],
) -> None:
    payload = canonical_json_bytes(dict(metadata.signed))
    valid: set[str] = set()
    for signature in metadata.signatures:
        if signature.key_id not in role.key_ids or signature.key_id in valid:
            continue
        key = keys[signature.key_id]
        if signature.algorithm == key.algorithm and verify_ed25519(
            key.key, payload, signature.value
        ):
            valid.add(signature.key_id)
    if len(valid) < role.threshold:
        _reject("SIGNATURE_THRESHOLD_UNMET", "metadata signature threshold was not met")


def _verify_link(
    parent: SignedMetadata, name: str, child: SignedMetadata
) -> None:
    role = str(parent.signed.get("_type", ""))
    payload = signed_payload(parent, role)
    meta = _mapping(payload["meta"], f"{role} meta")
    if set(meta) != {name}:
        _reject("MIX_AND_MATCH", f"{role} metadata names an unexpected child set")
    reference = _mapping(meta[name], f"{role} {name} reference")
    if set(reference) != {"version", "digest"}:
        _reject("MIX_AND_MATCH", f"{role} child reference fields are invalid")
    expected_version = _version(dict(child.signed), str(child.signed.get("_type", "")))
    if reference["version"] != expected_version:
        _reject("MIX_AND_MATCH", f"{name} version does not match its parent")
    digest = Digest.parse(reference["digest"], reason="MIX_AND_MATCH")
    if str(digest) != metadata_digest(child):
        _reject("MIX_AND_MATCH", f"{name} digest does not match its parent")


def _check_expiry(metadata: SignedMetadata, role: str, now: datetime) -> None:
    expires = _expires(dict(metadata.signed), role)
    if now >= expires:
        reason = "FREEZE" if role == "timestamp" else "EXPIRED"
        _reject(reason, f"{role} metadata is expired")


def _check_rollback(role: str, version: int, trusted: TrustedVersions) -> None:
    minimum = trusted.minimum.get(role, 1)
    if version < minimum:
        _reject("ROLLBACK", f"{role} metadata version is below trusted state")


def _version(payload: Mapping[str, Any], role: str) -> int:
    version = payload.get("version")
    if type(version) is not int or version < 1:
        _reject("CONTROL_METADATA_INVALID", f"{role} version is invalid")
    return version


def _expires(payload: Mapping[str, Any], role: str) -> datetime:
    value = payload.get("expires")
    if not isinstance(value, str) or not value.endswith("Z"):
        _reject("CONTROL_METADATA_INVALID", f"{role} expiry is invalid")
    try:
        parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError as exc:
        raise ControlPlaneVerificationError(
            "CONTROL_METADATA_INVALID", f"{role} expiry is invalid"
        ) from exc
    return parsed


def _role_fields(role: str) -> set[str]:
    if role == "root":
        return {"_type", "version", "expires", "keys", "roles"}
    if role == "targets":
        return {"_type", "version", "expires", "targets", "revoked_digests"}
    if role in {"snapshot", "timestamp"}:
        return {"_type", "version", "expires", "meta"}
    _reject("CONTROL_METADATA_INVALID", "metadata role is unsupported")


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        _reject("CONTROL_METADATA_INVALID", f"{label} must be an object")
    return dict(value)


def _array(value: Any, label: str) -> list[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        _reject("CONTROL_METADATA_INVALID", f"{label} must be an array")
    return list(value)


def _reject(reason: str, message: str) -> None:
    raise ControlPlaneVerificationError(reason, message)
