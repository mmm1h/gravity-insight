"""Deterministic cryptographic helpers for local verification."""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

from .errors import ControlPlaneVerificationError


HMAC_SHA256 = "hmac-sha256"


def canonical_json_bytes(value: Any) -> bytes:
    try:
        rendered = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise ControlPlaneVerificationError(
            "CONTROL_METADATA_INVALID", "value is not canonical JSON"
        ) from exc
    return rendered.encode("utf-8")


def sha256_digest(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def hmac_sha256(key: bytes, payload: bytes) -> str:
    return hmac.new(key, payload, hashlib.sha256).hexdigest()


def verify_hmac_sha256(key: bytes, payload: bytes, signature: str) -> bool:
    if len(key) < 16 or not _hex_digest(signature):
        return False
    expected = hmac_sha256(key, payload)
    return hmac.compare_digest(expected, signature)


def _hex_digest(value: str) -> bool:
    if len(value) != 64:
        return False
    return all(character in "0123456789abcdef" for character in value)
