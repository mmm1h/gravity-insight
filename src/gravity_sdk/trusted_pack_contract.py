"""Code-free Trusted Operator/Model Pack descriptor consumed later by R04."""

from __future__ import annotations

import copy
from typing import Any, Mapping

from .agent_runtime_contracts import (
    AgentRuntimeContractError,
    canonical_digest,
    validate_schema,
)


SCHEMA_VERSION = "gravity.trusted-pack-descriptor.v1"
_SCHEMA_NAME = "trusted-pack-descriptor-v1.schema.json"


class TrustedPackContractError(AgentRuntimeContractError):
    """A trusted code-pack descriptor violates the Stage A handoff contract."""

    def __init__(self, reason_code: str, message: str) -> None:
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {message}")


def compile_trusted_pack_descriptor(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise TrustedPackContractError(
            "TRUSTED_PACK_INVALID", "Trusted Pack descriptor must be an object"
        )
    contract = copy.deepcopy(dict(value))
    try:
        validate_schema(contract, _SCHEMA_NAME, "Trusted Pack descriptor")
    except AgentRuntimeContractError as exc:
        raise TrustedPackContractError("TRUSTED_PACK_INVALID", str(exc)) from exc
    if not contract["operators"] and not contract["models"]:
        raise TrustedPackContractError(
            "TRUSTED_PACK_EMPTY", "Trusted Pack must declare an Operator or Model"
        )
    groups = set(contract["allowed_groups"])
    expected = {
        *({"gravity.operators"} if contract["operators"] else set()),
        *({"gravity.models"} if contract["models"] else set()),
    }
    if groups != expected:
        raise TrustedPackContractError(
            "TRUSTED_PACK_GROUP_INVALID",
            "allowed groups disagree with declared artifact identities",
        )
    compatibility = contract["runtime_compatibility"]
    if _version(compatibility["minimum"]) > _version(compatibility["maximum"]):
        raise TrustedPackContractError(
            "TRUSTED_PACK_RUNTIME_INVALID", "Runtime compatibility is reversed"
        )
    normalized = copy.deepcopy(contract)
    normalized["allowed_groups"] = sorted(normalized["allowed_groups"])
    normalized["operators"] = sorted(normalized["operators"])
    normalized["models"] = sorted(normalized["models"])
    return {"contract": normalized, "digest": canonical_digest(normalized)}


def _version(value: str) -> tuple[int, int, int]:
    return tuple(int(item) for item in value.split("."))  # type: ignore[return-value]


__all__ = [
    "SCHEMA_VERSION",
    "TrustedPackContractError",
    "compile_trusted_pack_descriptor",
]
