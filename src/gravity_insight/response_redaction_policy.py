"""Static credential-name policy for public response projection."""

from __future__ import annotations


RESPONSE_CREDENTIALS = frozenset({
    "access_token",
    "authorization",
    "cookie",
    "password",
    "private_key",
    "refresh_token",
    "secret",
    "session_token",
    "token",
})
RESPONSE_CREDENTIAL_SUFFIXES = tuple(
    f"_{key}" for key in RESPONSE_CREDENTIALS
)


__all__: list[str] = []
