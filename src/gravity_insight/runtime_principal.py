"""Read the authenticated account principal from a runtime credential source."""

from __future__ import annotations

from typing import Any

from .credentials import Credential


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


__all__ = ["current_principal_id", "refresh_if_rejected"]
