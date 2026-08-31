"""Isolated legal/provenance registry for externally inspired methods."""

from __future__ import annotations

import copy
import hashlib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .agent_runtime_contracts import (
    AgentRuntimeContractError,
    canonical_digest,
    load_json_object,
    validate_schema,
)


SCHEMA_VERSION = "gravity.external-method-source-registry.v1"
SCHEMA_NAME = "external-method-source-registry-v1.schema.json"
REGISTRY_PATH = Path(__file__).resolve().parents[2] / "skills" / "sources" / "registry.json"
SOURCE_REF_PREFIX = "source://external-method/"


class ExternalMethodRegistryError(AgentRuntimeContractError):
    """The isolated external-method registry is malformed or drifted."""

    def __init__(self, reason_code: str, message: str) -> None:
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {message}")


def opaque_source_id(source_locator: str) -> str:
    return hashlib.sha256(source_locator.encode("utf-8")).hexdigest()[:16]


def source_ref(source_locator: str) -> str:
    return SOURCE_REF_PREFIX + opaque_source_id(source_locator)


def load_source_registry(path: Path = REGISTRY_PATH) -> dict[str, Any]:
    return validate_source_registry(load_json_object(path, "external method source registry"))


def validate_source_registry(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        _invalid("EXTERNAL_METHOD_REGISTRY_INVALID", "registry must be an object")
    selected = copy.deepcopy(dict(value))
    try:
        validate_schema(selected, SCHEMA_NAME, "external method source registry")
    except AgentRuntimeContractError as exc:
        raise ExternalMethodRegistryError(
            "EXTERNAL_METHOD_REGISTRY_INVALID", "registry schema validation failed"
        ) from exc
    digest = selected.pop("registry_sha256")
    expected = canonical_digest(selected)
    selected["registry_sha256"] = digest
    if digest != expected:
        _invalid("EXTERNAL_METHOD_SOURCE_CHANGED", "registry digest changed")
    _validate_items(selected)
    return selected


def _validate_items(registry: Mapping[str, Any]) -> None:
    items = registry["items"]
    opaque_ids = [item["opaque_id"] for item in items]
    locators = [item["source_locator"] for item in items]
    if registry["item_count"] != len(items):
        _invalid("EXTERNAL_METHOD_REGISTRY_INVALID", "item count is not derived")
    if opaque_ids != sorted(opaque_ids) or len(opaque_ids) != len(set(opaque_ids)):
        _invalid("EXTERNAL_METHOD_REGISTRY_INVALID", "opaque IDs must be unique and sorted")
    if len(locators) != len(set(locators)):
        _invalid("EXTERNAL_METHOD_REGISTRY_INVALID", "source locators must be unique")
    for item in items:
        if item["opaque_id"] != opaque_source_id(item["source_locator"]):
            _invalid("EXTERNAL_METHOD_SOURCE_CHANGED", "opaque source identity changed")
        _validate_mapping(item)


def _validate_mapping(item: Mapping[str, Any]) -> None:
    if item["mapping_kind"] == "future_skill":
        valid = (
            item["future_skill_uri"] is not None
            and item["reason_code"] is None
            and item["license_review"] == "approved"
            and item["independent_authorship"] == "required"
            and item["authorship_evidence"] == "independent_rewrite_reviewed"
        )
        if not valid:
            _invalid("EXTERNAL_METHOD_REGISTRY_INVALID", "future Skill mapping is incomplete")
        return
    if item["future_skill_uri"] is not None or item["reason_code"] != "VENDOR_SPECIFIC_CAPABILITY":
        _invalid("VENDOR_SPECIFIC_CAPABILITY", "alternative mapping is not fail-closed")


def _invalid(reason_code: str, message: str) -> None:
    raise ExternalMethodRegistryError(reason_code, message)


__all__ = [
    "ExternalMethodRegistryError",
    "REGISTRY_PATH",
    "SCHEMA_NAME",
    "SCHEMA_VERSION",
    "SOURCE_REF_PREFIX",
    "load_source_registry",
    "opaque_source_id",
    "source_ref",
    "validate_source_registry",
]
