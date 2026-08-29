"""Shared credential removal for caller-visible values."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from . import json_output


_CREDENTIAL_KEYS = {
    "authorization",
    "cookie",
    "password",
    "secret",
    "access_token",
    "refresh_token",
    "gravity_auth_token",
    "gravity_authorization",
    "session_token",
    "token",
}
_CREDENTIAL_KEY_SUFFIXES = (
    "_password",
    "_token",
    "_secret",
    "_authorization",
    "_cookie",
)
_PUBLIC_CURSOR_KEYS = {"continuation_token"}
_BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]+=*")
_JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b")
_CREDENTIAL_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(?P<label>(?:authorization|cookie|password|secret|access_token|"
    r"refresh_token|gravity_auth_token|gravity_authorization|session_token|token|"
    r"[A-Za-z0-9_]+_(?:password|token|secret|authorization|cookie)))"
    r"(?P<separator>\s*[:=]\s*)"
    r'(?:"[^"]*"|\'[^\']*\'|[^\r\n,}\]]+)',
)


def sanitize_credentials(value: Any) -> Any:
    """Remove credentials from a caller-visible value tree."""

    value = json_output.to_jsonable(value)
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if (
                lowered in _CREDENTIAL_KEYS
                or (
                    lowered.endswith(_CREDENTIAL_KEY_SUFFIXES)
                    and lowered not in _PUBLIC_CURSOR_KEYS
                )
            ):
                continue
            result[str(key)] = sanitize_credentials(item)
        return result
    if isinstance(value, list):
        return [sanitize_credentials(item) for item in value]
    if isinstance(value, str):
        sanitized = _BEARER_RE.sub("Bearer [REDACTED]", value)
        sanitized = _JWT_RE.sub("[REDACTED]", sanitized)
        return _CREDENTIAL_ASSIGNMENT_RE.sub(
            r"\g<label>\g<separator>[REDACTED]", sanitized
        )
    return value


__all__ = ["sanitize_credentials"]
