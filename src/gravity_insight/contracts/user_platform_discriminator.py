"""Reviewed user-side platform discriminator bindings for acquisition rows."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

from ..agent_runtime_contracts import AgentRuntimeContractError, load_json_object, validate_schema
from ..models import OperationSpec, load_operation_manifest
from ..paths import CONTRACT_ROOT, MANIFEST_ROOT


SCHEMA_VERSION = "gravity.user-platform-discriminator-registry.v1"
RESOLUTION_SCHEMA_VERSION = "gravity.user-platform-discriminator-resolution.v1"
_SCHEMA_NAME = "user-platform-discriminator-v1.schema.json"
_REGISTRY_PATH = CONTRACT_ROOT / "user-platform-discriminators" / "registry.v1.json"


class UserPlatformDiscriminatorError(AgentRuntimeContractError):
    """A platform discriminator binding is missing, stale, or inconsistent."""


@dataclass(frozen=True)
class UserPlatformBinding:
    schema_version: str
    binding_id: str
    platform: str
    field_path: str
    accepted_value: str
    evidence: Mapping[str, Any]


def validate_user_platform_discriminator_registry(
    value: Mapping[str, Any], *, manifest_root: Path = MANIFEST_ROOT
) -> dict[str, Any]:
    selected = copy.deepcopy(dict(value))
    try:
        validate_schema(selected, _SCHEMA_NAME, "User platform discriminator registry")
        _validate_semantics(selected, manifest_root)
    except AgentRuntimeContractError as exc:
        raise UserPlatformDiscriminatorError(str(exc)) from exc
    return selected


def load_user_platform_discriminator_registry(
    path: Path, *, manifest_root: Path = MANIFEST_ROOT
) -> dict[str, Any]:
    selected = load_json_object(path, f"User platform discriminator registry {path.name}")
    return validate_user_platform_discriminator_registry(selected, manifest_root=manifest_root)


@lru_cache(maxsize=1)
def _registry() -> dict[str, Any]:
    return load_user_platform_discriminator_registry(_REGISTRY_PATH)


def user_platform_discriminator_registry() -> dict[str, Any]:
    return copy.deepcopy(_registry())


def require_proven_user_platform_binding(
    platform: str, *, as_of: str | date | None = None
) -> UserPlatformBinding:
    matches = [item for item in _registry()["bindings"] if item["platform"] == platform]
    if len(matches) != 1:
        raise UserPlatformDiscriminatorError(
            "user-side platform discriminator is not proven for this platform"
        )
    binding = matches[0]
    _require_current(binding["evidence"], as_of)
    return UserPlatformBinding(
        RESOLUTION_SCHEMA_VERSION,
        binding["binding_id"],
        binding["platform"],
        binding["field"]["path"],
        binding["accepted_value"],
        copy.deepcopy(binding["evidence"]),
    )


def inspect_user_platform_discriminator_contract(root: Path) -> list[str]:
    path = root / "src/gravity_insight/contracts/user-platform-discriminators/registry.v1.json"
    manifests = root / "src/gravity_insight/manifests"
    try:
        load_user_platform_discriminator_registry(path, manifest_root=manifests)
    except (AgentRuntimeContractError, OSError, UnicodeError, ValueError) as exc:
        return [f"user-platform-discriminator-contract: {exc}"]
    return []


def _validate_semantics(registry: Mapping[str, Any], manifest_root: Path) -> None:
    bindings = registry["bindings"]
    platforms = [item["platform"] for item in bindings]
    identities = [item["binding_id"] for item in bindings]
    if len(platforms) != len(set(platforms)) or len(identities) != len(set(identities)):
        raise UserPlatformDiscriminatorError("platform discriminator binding is duplicated")
    operations = _operation_index(manifest_root)
    for binding in bindings:
        if binding["accepted_value"] != binding["platform"]:
            raise UserPlatformDiscriminatorError("platform discriminator value contradicts platform")
        _validate_field_reference(binding["field"], operations)
        _validate_evidence(binding)


def _operation_index(manifest_root: Path) -> dict[str, OperationSpec]:
    operations: dict[str, OperationSpec] = {}
    for path in sorted(manifest_root.glob("*.json")):
        for operation in load_operation_manifest(path):
            if operation.operation_id in operations:
                raise UserPlatformDiscriminatorError("operation identity is duplicated")
            operations[operation.operation_id] = operation
    if not operations:
        raise UserPlatformDiscriminatorError("operation manifest catalog is empty")
    return operations


def _validate_field_reference(
    reference: Mapping[str, Any], operations: Mapping[str, OperationSpec]
) -> None:
    operation = operations.get(reference["operation_id"])
    field = str(reference["path"]).rsplit(".", 1)[-1]
    if operation is None or field not in operation.response_projection.item_keys:
        raise UserPlatformDiscriminatorError(
            "platform discriminator field is absent from response projection"
        )


def _validate_evidence(binding: Mapping[str, Any]) -> None:
    evidence = binding["evidence"]
    sampled = _canonical_date(evidence["sampled_on"], "sampled_on")
    review = _canonical_date(evidence["revalidate_after"], "revalidate_after")
    if review <= sampled:
        raise UserPlatformDiscriminatorError("platform evidence revalidation must follow sampling")
    observations = evidence["observations"]
    fields = [item["field"] for item in observations]
    if len(fields) != len(set(fields)):
        raise UserPlatformDiscriminatorError("platform evidence field is duplicated")
    expected = [binding["accepted_value"]]
    if any(item["observed_values"] != expected for item in observations):
        raise UserPlatformDiscriminatorError("platform evidence contains an unaccepted value")
    if any(item["selected_row_count"] > evidence["source_row_count"] for item in observations):
        raise UserPlatformDiscriminatorError("platform evidence row count exceeds its source")
    if "source_completeness_unknown" not in evidence["limitation_codes"]:
        raise UserPlatformDiscriminatorError("platform evidence must retain source completeness")


def _require_current(evidence: Mapping[str, Any], as_of: str | date | None) -> None:
    selected = date.today() if as_of is None else _as_of_date(as_of)
    sampled = _canonical_date(evidence["sampled_on"], "sampled_on")
    review = _canonical_date(evidence["revalidate_after"], "revalidate_after")
    if selected < sampled or selected > review:
        raise UserPlatformDiscriminatorError(
            "user-side platform discriminator evidence is not current"
        )


def _as_of_date(value: str | date) -> date:
    return value if isinstance(value, date) else _canonical_date(value, "as_of")


def _canonical_date(value: Any, field: str) -> date:
    try:
        selected = date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise UserPlatformDiscriminatorError(
            f"platform discriminator {field} must be YYYY-MM-DD"
        ) from exc
    if selected.isoformat() != value:
        raise UserPlatformDiscriminatorError(
            f"platform discriminator {field} must be canonical YYYY-MM-DD"
        )
    return selected


__all__ = [
    "RESOLUTION_SCHEMA_VERSION",
    "SCHEMA_VERSION",
    "UserPlatformBinding",
    "UserPlatformDiscriminatorError",
    "inspect_user_platform_discriminator_contract",
    "load_user_platform_discriminator_registry",
    "require_proven_user_platform_binding",
    "user_platform_discriminator_registry",
    "validate_user_platform_discriminator_registry",
]
