"""Deterministic cryptographic helpers for local verification."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from typing import Any

from .errors import ControlPlaneVerificationError

try:
    from nacl.exceptions import BadSignatureError as _BadSignatureError
    from nacl.signing import VerifyKey as _VerifyKey
except ImportError as exc:
    _BadSignatureError = None
    _VerifyKey = None
    _NACL_IMPORT_ERROR: ImportError | None = exc
else:
    _NACL_IMPORT_ERROR = None


ED25519 = "ed25519"


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


def verify_ed25519(public_key: bytes, payload: bytes, signature: str) -> bool:
    verify_key, bad_signature_error = _ed25519_backend()
    if len(public_key) != 32:
        return False
    try:
        encoded = base64.b64decode(signature, validate=True)
    except (binascii.Error, ValueError):
        return False
    if len(encoded) != 64 or base64.b64encode(encoded).decode("ascii") != signature:
        return False
    try:
        verify_key(public_key).verify(payload, encoded)
    except (bad_signature_error, ValueError):
        return False
    return True


def _ed25519_backend() -> tuple[Any, type[Exception]]:
    if (
        _NACL_IMPORT_ERROR is not None
        or _VerifyKey is None
        or _BadSignatureError is None
    ):
        raise ControlPlaneVerificationError(
            "CRYPTO_BACKEND_UNAVAILABLE",
            "Ed25519 verification requires the optional control-plane dependency; "
            'install it with `pip install "gravity-insight[control-plane]"`',
        ) from _NACL_IMPORT_ERROR
    return _VerifyKey, _BadSignatureError
