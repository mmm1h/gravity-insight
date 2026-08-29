"""Deterministic local fixtures shared by Control Plane verification tests."""

from __future__ import annotations

import base64
import copy
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Mapping

from gravity_sdk.control_plane.models import (
    ArtifactTrustPolicy,
    SignedMetadata,
    TrustedVersions,
    VerificationKey,
)
from gravity_sdk.control_plane.crypto import canonical_json_bytes, hmac_sha256, sha256_digest
from gravity_sdk.control_plane.tuf import metadata_digest


FIXTURES = Path(__file__).parent / "fixtures" / "control_plane"
NOW = datetime(2028, 1, 1, tzinfo=timezone.utc)
VALID_EXPIRY = "2030-01-01T00:00:00Z"
EXPIRED = "2027-01-01T00:00:00Z"
CONTENT = b"deterministic-gravity-runtime-wheel"
PREDICATE = "https://slsa.dev/provenance/v1"
BUILDER = "https://ci.example/builders/gravity-release"
SOURCE = "https://github.com/mmm1h/gravity-sdk"
IDENTITY = "release@gravity.example"
LICENSE = "Apache-2.0"
KEYS = {
    "root-old": b"fixture-root-old-key-0001",
    "root-new": b"fixture-root-new-key-0002",
    "targets": b"fixture-targets-key-0003",
    "snapshot": b"fixture-snapshot-key-0004",
    "timestamp": b"fixture-timestamp-key-0005",
    "artifact": b"fixture-artifact-key-0006",
    "other-root": b"fixture-other-root-key-0007",
}


@dataclass(frozen=True)
class Fixture:
    case: Mapping[str, Any]
    bundle: Mapping[str, Any]
    trust_root: Mapping[str, Any]
    policy: ArtifactTrustPolicy
    trusted_versions: TrustedVersions


def build_fixture(name: str) -> Fixture:
    case = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    scenario = case["scenario"]
    artifact, envelope = _artifact()
    explicit_root = _root(version=1, root_key="root-old")
    root_chain: list[dict[str, Any]] = []
    if scenario == "root-rotation":
        rotated = _root(version=2, root_key="root-new", signers=("root-old", "root-new"))
        root_chain.append(rotated)
    targets = _targets(artifact, scenario)
    snapshot = _snapshot(targets, scenario)
    timestamp = _timestamp(snapshot, scenario)
    bundle = {
        "trust_root_digest": metadata_digest(SignedMetadata.from_dict(explicit_root)),
        "root_chain": root_chain,
        "targets": targets,
        "snapshot": snapshot,
        "timestamp": timestamp,
        "artifacts": [envelope],
    }
    if scenario == "tampered":
        bundle["artifacts"][0]["content"] = _b64(b"tampered-content")
    trust_root = explicit_root
    if scenario == "trust-root-mismatch":
        trust_root = _root(version=1, root_key="other-root")
    versions = TrustedVersions(case.get("minimum_versions", {}))
    return Fixture(case, bundle, trust_root, artifact_policy(), versions)


def artifact_policy(**overrides: Any) -> ArtifactTrustPolicy:
    values = {
        "keys": {
            "artifact": VerificationKey.from_dict(
                "artifact",
                {
                    "algorithm": "hmac-sha256",
                    "key": _b64(KEYS["artifact"]),
                    "identity": IDENTITY,
                },
                identity_required=True,
            )
        },
        "allowed_signer_identities": frozenset({IDENTITY}),
        "signature_threshold": 1,
        "allowed_builder_ids": frozenset({BUILDER}),
        "allowed_source_uris": frozenset({SOURCE}),
        "allowed_licenses": frozenset({LICENSE}),
        "required_predicate_type": PREDICATE,
    }
    values.update(overrides)
    return ArtifactTrustPolicy(**values)


def sign_metadata(payload: Mapping[str, Any], *key_ids: str) -> dict[str, Any]:
    body = copy.deepcopy(dict(payload))
    return {
        "signed": body,
        "signatures": [_signature(body, key_id) for key_id in key_ids],
    }


def resign_metadata(document: Mapping[str, Any], *key_ids: str) -> dict[str, Any]:
    return sign_metadata(document["signed"], *key_ids)


def resign_artifact(document: Mapping[str, Any]) -> dict[str, Any]:
    selected = copy.deepcopy(dict(document))
    attestation = {
        key: selected[key]
        for key in ("artifact", "license", "provenance", "target_name")
    }
    selected["signatures"] = [_signature(attestation, "artifact")]
    return selected


def _root(
    *, version: int, root_key: str, signers: tuple[str, ...] | None = None
) -> dict[str, Any]:
    key_ids = (root_key, "targets", "snapshot", "timestamp")
    payload = {
        "_type": "root",
        "version": version,
        "expires": VALID_EXPIRY,
        "keys": {
            key_id: {"algorithm": "hmac-sha256", "key": _b64(KEYS[key_id])}
            for key_id in key_ids
        },
        "roles": {
            "root": {"key_ids": [root_key], "threshold": 1},
            "targets": {"key_ids": ["targets"], "threshold": 1},
            "snapshot": {"key_ids": ["snapshot"], "threshold": 1},
            "timestamp": {"key_ids": ["timestamp"], "threshold": 1},
        },
    }
    return sign_metadata(payload, *(signers or (root_key,)))


def _artifact() -> tuple[dict[str, Any], dict[str, Any]]:
    digest = sha256_digest(CONTENT)
    artifact = {
        "repository": "registry.example/gravity/runtime",
        "descriptor": {
            "digest": digest,
            "media_type": "application/vnd.python.wheel",
            "size": len(CONTENT),
        },
    }
    provenance = {
        "subject_digest": digest,
        "builder_id": BUILDER,
        "source_uri": SOURCE,
        "predicate_type": PREDICATE,
    }
    attestation = {
        "artifact": artifact,
        "license": LICENSE,
        "provenance": provenance,
        "target_name": "runtime/gravity_sdk.whl",
    }
    envelope = {
        **attestation,
        "content": _b64(CONTENT),
        "signatures": [_signature(attestation, "artifact")],
    }
    return artifact, envelope


def _targets(artifact: Mapping[str, Any], scenario: str) -> dict[str, Any]:
    digest = artifact["descriptor"]["digest"]
    payload = {
        "_type": "targets",
        "version": 2,
        "expires": EXPIRED if scenario == "expired" else VALID_EXPIRY,
        "targets": {"runtime/gravity_sdk.whl": copy.deepcopy(dict(artifact))},
        "revoked_digests": [digest] if scenario == "revoked" else [],
    }
    return sign_metadata(payload, "targets")


def _snapshot(targets: Mapping[str, Any], scenario: str) -> dict[str, Any]:
    target_digest = metadata_digest(SignedMetadata.from_dict(targets))
    if scenario == "mix-and-match":
        target_digest = "sha256:" + ("0" * 64)
    payload = {
        "_type": "snapshot",
        "version": 4,
        "expires": VALID_EXPIRY,
        "meta": {
            "targets.json": {
                "version": targets["signed"]["version"],
                "digest": target_digest,
            }
        },
    }
    return sign_metadata(payload, "snapshot")


def _timestamp(snapshot: Mapping[str, Any], scenario: str) -> dict[str, Any]:
    payload = {
        "_type": "timestamp",
        "version": 8,
        "expires": EXPIRED if scenario == "freeze" else VALID_EXPIRY,
        "meta": {
            "snapshot.json": {
                "version": snapshot["signed"]["version"],
                "digest": metadata_digest(SignedMetadata.from_dict(snapshot)),
            }
        },
    }
    return sign_metadata(payload, "timestamp")


def _signature(payload: Mapping[str, Any], key_id: str) -> dict[str, str]:
    return {
        "key_id": key_id,
        "algorithm": "hmac-sha256",
        "value": hmac_sha256(KEYS[key_id], canonical_json_bytes(payload)),
    }


def _b64(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")
