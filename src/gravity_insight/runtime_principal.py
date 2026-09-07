"""Read the authenticated account principal from a runtime credential source."""

from __future__ import annotations

from typing import Any

from .credentials import Credential
from .errors import AuthenticationError, CredentialError, PermissionUnavailableError


def current_principal_id(credentials: Any) -> str | None:
    resolver = getattr(credentials, "current_principal_id", None)
    credential_or_id = resolver() if callable(resolver) else credentials.get()
    value = (
        credential_or_id
        if isinstance(credential_or_id, (str, int))
        and not isinstance(credential_or_id, bool)
        else getattr(credential_or_id, "gravity_id", None)
    )
    selected = str(value).strip() if value is not None else ""
    return selected or None


def refresh_if_rejected(provider: Any, credential: Credential) -> Credential:
    refresh = getattr(provider, "refresh_if_rejected", None)
    if callable(refresh):
        return refresh(credential)
    return provider.refresh()


def authentication_rejected(response: Any, semantic_codes: Any, lease: Any) -> bool:
    from collections.abc import Mapping

    code = response.payload.get("code") if isinstance(response.payload, Mapping) else None
    if lease is None:
        return response.status_code in {401, 403} or code in semantic_codes
    if response.status_code == 403:
        raise PermissionUnavailableError("the authenticated Gravity account cannot read this capability")
    # Owner's 2026-09-07 two-process reproduction (382 + 7 requests) disproved
    # account-isolated 429 quotas. Capacity/5xx bodies cannot trigger failover.
    return response.status_code == 401 or (200 <= response.status_code < 300 and code in semantic_codes)


def refresh_authentication(provider: Any, credential: Credential, response: Any,
                           semantic_codes: Any, refreshed: bool, lease: Any) -> bool:
    if not authentication_rejected(response, semantic_codes, lease):
        return False
    if lease is not None:
        lease.check()
    if refreshed:
        if response.status_code == 403:
            raise PermissionUnavailableError("the authenticated Gravity account cannot read this capability")
        raise AuthenticationError("Gravity authorization is invalid or expired")
    try:
        refresh_if_rejected(provider, credential)
    except CredentialError:
        if lease is None:
            raise
        raise AuthenticationError("Gravity authorization is invalid or expired") from None
    if lease is not None:
        lease.after_refresh()
    return True


__all__ = ["current_principal_id", "refresh_if_rejected"]
