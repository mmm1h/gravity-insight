"""Fail-closed marker-or-upstream-owner decisions for mutation preflight."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .actionable_error_values import actual_value
from .errors import CredentialError, InputValidationError


@dataclass(frozen=True)
class OwnerReference:
    owner_id: str | None
    owner_name: str | None
    field: str


@dataclass(frozen=True)
class OwnershipDecision:
    basis: str
    principal_id: str | None
    owner: OwnerReference

    def public(self) -> dict[str, Any]:
        return {
            "basis": self.basis,
            "principal_id": self.principal_id,
            "owner_id": self.owner.owner_id,
            "owner_name": self.owner.owner_name,
            "owner_field": self.owner.field,
        }


def create_user_owner(value: Mapping[str, Any]) -> OwnerReference:
    return OwnerReference(
        _identifier(value.get("create_user_id")),
        _optional_text(value.get("create_user_name")),
        "create_user_id",
    )


def creator_owner(value: Any) -> OwnerReference:
    items = (
        [value]
        if isinstance(value, Mapping)
        else list(value)
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes))
        else []
    )
    candidates = [
        OwnerReference(
            _identifier(item.get("id", item.get("uid"))),
            _optional_text(item.get("name")),
            "creator.id" if item.get("id") is not None else "creator.uid",
        )
        for item in items
        if isinstance(item, Mapping)
    ]
    candidates = [item for item in candidates if item.owner_id is not None]
    identities = {item.owner_id for item in candidates}
    if len(identities) != 1:
        return OwnerReference(None, None, "creator.id|uid")
    return candidates[0]


def single_creator_owner(value: Any) -> OwnerReference:
    """Read the proven single-object creator.id shape without uid/array fallback."""

    if not isinstance(value, Mapping):
        return OwnerReference(None, None, "creator.id")
    return OwnerReference(
        _identifier(value.get("id")),
        _optional_text(value.get("name")),
        "creator.id",
    )


def require_mutation_authority(
    client: Any,
    *,
    marker: str | None,
    owner: OwnerReference,
    object_kind: str,
    object_id: str | int,
    field: str,
) -> OwnershipDecision:
    """Accept SDK source evidence or a proven upstream owner/principal match."""

    if marker is not None:
        return OwnershipDecision("sdk_source_marker", None, owner)
    try:
        principal = _identifier(client._current_principal_id())
    except (AttributeError, CredentialError):
        principal = None
    if owner.owner_id is not None and principal == owner.owner_id:
        return OwnershipDecision("upstream_owner", principal, owner)
    observed = {
        "object_kind": object_kind,
        "object_id": str(object_id),
        "owner_id": owner.owner_id,
        "owner_name": owner.owner_name,
        "owner_field": owner.field,
        "current_principal_id": principal,
        "sdk_marker": None,
    }
    if principal is None:
        next_action = (
            f"Refresh Gravity authentication so the cached session contains the current gravity_id, then retry {object_kind} {object_id} once."
        )
    elif owner.owner_id is None:
        next_action = (
            f"Use an SDK-created {object_kind} carrying its GSDK marker, or refresh {object_kind} {object_id} after the upstream {owner.field} is present; unmarked objects without a proven owner stay rejected."
        )
    else:
        next_action = (
            f"Choose {object_kind} {object_id} whose {owner.field}={owner.owner_id} equals the current principal {principal}, or ask owner {owner.owner_name or owner.owner_id} to make the change."
        )
    raise _ownership_error(
        actual=actual_value(observed),
        field=field,
        next_action=next_action,
    )


def _ownership_error(
    actual: str,
    field: str,
    next_action: str,
) -> InputValidationError:
    return InputValidationError(
        f"actual value: {actual}; allowed values: a valid GSDK source marker or an upstream owner ID equal to the authenticated gravity_id",
        field=field,
        next_action=next_action,
        code="OWNERSHIP_REQUIRED",
    )


def _identifier(value: Any) -> str | None:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    selected = str(value).strip()
    return selected or None


def _optional_text(value: Any) -> str | None:
    selected = value.strip() if isinstance(value, str) else ""
    return selected or None


__all__ = [
    "OwnerReference",
    "OwnershipDecision",
    "create_user_owner",
    "creator_owner",
    "single_creator_owner",
    "require_mutation_authority",
]
