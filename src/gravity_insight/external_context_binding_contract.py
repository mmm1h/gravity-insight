"""Tracked external Context descriptor and requirement registry."""

from __future__ import annotations

import copy
import json
from collections.abc import Mapping
from datetime import date
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .agent_runtime_contracts import AgentRuntimeContractError, canonical_digest, validate_schema
from .context_contract import ContextContractError
from .external_context_contract import (
    ExternalContextContractError,
    build_rpc_request,
    compile_external_provider,
    resource_is_allowed,
)
from .repo_context_git import assert_clean_paths, git_snapshot
from .repo_context_index import read_context_file


SCHEMA_VERSION = "gravity.external-context-bindings.v1"
BINDINGS_FILENAME = "gravity.external-context.json"
_SCHEMA_NAME = "external-context-bindings-v1.schema.json"
_MAX_BINDING_BYTES = 2_097_152
_VALIDATION_REQUEST_ID = "00000000-0000-4000-8000-000000000000"


class ExternalContextBindingError(AgentRuntimeContractError):
    """An external Context project binding cannot be trusted or resolved."""

    def __init__(self, reason_code: str, message: str) -> None:
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {message}")


def compile_external_context_bindings(value: Mapping[str, Any]) -> dict[str, Any]:
    contract = _binding_object(value)
    try:
        validate_schema(contract, _SCHEMA_NAME, "External Context bindings")
        providers = [compile_external_provider(item) for item in contract["providers"]]
    except (AgentRuntimeContractError, ExternalContextContractError) as exc:
        raise ExternalContextBindingError(
            "EXTERNAL_CONTEXT_BINDING_INVALID", str(exc)
        ) from exc
    provider_by_uri = {item["contract"]["uri"]: item for item in providers}
    if len(provider_by_uri) != len(providers):
        raise ExternalContextBindingError(
            "EXTERNAL_CONTEXT_BINDING_CONFLICT", "Provider identities are duplicated"
        )
    requirements = [
        _compile_requirement(item, provider_by_uri)
        for item in contract["requirements"]
    ]
    identities = [item["contract"]["requirement_id"] for item in requirements]
    if len(identities) != len(set(identities)):
        raise ExternalContextBindingError(
            "EXTERNAL_CONTEXT_BINDING_CONFLICT", "Requirement identities are duplicated"
        )
    normalized = _normalized_registry(providers, requirements)
    return {
        "contract": normalized,
        "digest": canonical_digest(normalized),
        "providers": {item["contract"]["uri"]: copy.deepcopy(item) for item in providers},
        "requirements": {
            item["contract"]["requirement_id"]: copy.deepcopy(item)
            for item in requirements
        },
    }


def load_external_context_bindings(root: str | Path) -> dict[str, Any]:
    project_root = Path(root).resolve()
    try:
        snapshot = git_snapshot(project_root)
        content, _path = read_context_file(
            project_root,
            BINDINGS_FILENAME,
            maximum=_MAX_BINDING_BYTES,
            require_tracked=True,
            max_depth=1,
        )
        selected = compile_external_context_bindings(json.loads(content))
        verify_external_context_binding_revision(project_root, snapshot["source_revision"])
    except ExternalContextBindingError:
        raise
    except ContextContractError as exc:
        raise ExternalContextBindingError(_context_reason(exc.reason_code), str(exc)) from exc
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ExternalContextBindingError(
            "EXTERNAL_CONTEXT_BINDING_INVALID", "Binding registry is not UTF-8 JSON"
        ) from exc
    return {
        **selected,
        "source_revision": snapshot["source_revision"],
        "observed_at": snapshot["observed_at"],
        "network_called": False,
    }


def verify_external_context_binding_revision(root: Path, revision: str) -> None:
    assert_clean_paths(root, [BINDINGS_FILENAME])
    if git_snapshot(root)["source_revision"] != revision:
        raise ExternalContextBindingError(
            "EXTERNAL_CONTEXT_BINDING_SNAPSHOT_CHANGED",
            "External Context binding changed during resolution",
        )


def _binding_object(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ExternalContextBindingError(
            "EXTERNAL_CONTEXT_BINDING_INVALID", "Binding registry must be an object"
        )
    return copy.deepcopy(dict(value))


def _normalized_registry(
    providers: list[dict[str, Any]], requirements: list[dict[str, Any]]
) -> dict[str, Any]:
    return {
        "artifact_kind": "external_context_bindings",
        "schema_version": SCHEMA_VERSION,
        "providers": [
            copy.deepcopy(item["contract"])
            for item in sorted(providers, key=lambda item: item["contract"]["uri"])
        ],
        "requirements": [
            copy.deepcopy(item["contract"])
            for item in sorted(
                requirements, key=lambda item: item["contract"]["requirement_id"]
            )
        ],
    }


def _compile_requirement(
    value: Mapping[str, Any], providers: Mapping[str, Mapping[str, Any]]
) -> dict[str, Any]:
    contract = copy.deepcopy(dict(value))
    provider = providers.get(contract["provider_uri"])
    if provider is None:
        raise ExternalContextBindingError(
            "EXTERNAL_CONTEXT_BINDING_INVALID", "Requirement Provider is not declared"
        )
    descriptor = provider["contract"]
    if "read" not in descriptor["capabilities"]["operations"]:
        raise ExternalContextBindingError(
            "EXTERNAL_CONTEXT_BINDING_INVALID", "Requirement Provider cannot read"
        )
    _validate_requirement_policy(contract)
    _validate_requirement_resources(contract, descriptor)
    contract["subject_entities"] = sorted(contract["subject_entities"])
    contract["required_windows"] = sorted(contract["required_windows"])
    contract["authority_policy"]["required"] = sorted(contract["authority_policy"]["required"])
    contract["allowed_sensitivity"] = sorted(contract["allowed_sensitivity"])
    contract["resources"] = sorted(contract["resources"], key=lambda item: item["item_id"])
    return {"contract": contract, "digest": canonical_digest(contract)}


def _validate_requirement_policy(contract: Mapping[str, Any]) -> None:
    try:
        ZoneInfo(contract["timezone"])
        if contract["freshness_policy"]["as_of"] is not None:
            selected = date.fromisoformat(contract["freshness_policy"]["as_of"])
            if selected.isoformat() != contract["freshness_policy"]["as_of"]:
                raise ValueError("non-canonical date")
    except (ValueError, ZoneInfoNotFoundError) as exc:
        raise ExternalContextBindingError(
            "EXTERNAL_CONTEXT_BINDING_INVALID", "Requirement time policy is invalid"
        ) from exc
    authority = contract["authority_policy"]
    if "supporting" in authority["required"] and not authority["allow_supporting"]:
        raise ExternalContextBindingError(
            "EXTERNAL_CONTEXT_BINDING_INVALID", "Requirement authority policy conflicts"
        )


def _validate_requirement_resources(
    contract: Mapping[str, Any], descriptor: Mapping[str, Any]
) -> None:
    resources = contract["resources"]
    item_ids = [item["item_id"] for item in resources]
    uris = [item["resource_uri"] for item in resources]
    invalid = (
        len(item_ids) != len(set(item_ids))
        or len(uris) != len(set(uris))
        or contract["budget"]["max_files"] < len(resources)
        or any(not _valid_bound_resource(descriptor, uri) for uri in uris)
    )
    if invalid:
        raise ExternalContextBindingError(
            "EXTERNAL_CONTEXT_BINDING_INVALID", "Requirement resources are invalid"
        )


def _valid_bound_resource(descriptor: Mapping[str, Any], resource_uri: str) -> bool:
    try:
        build_rpc_request(
            descriptor["uri"],
            "read",
            {"resource_uri": resource_uri},
            request_id=_VALIDATION_REQUEST_ID,
        )
    except ExternalContextContractError:
        return False
    return resource_is_allowed(resource_uri, descriptor["allowed_resource_prefixes"])


def _context_reason(reason: str) -> str:
    if reason == "CONTEXT_RESOURCE_MISSING":
        return "EXTERNAL_CONTEXT_BINDING_MISSING"
    if reason == "CONTEXT_SNAPSHOT_CHANGED":
        return "EXTERNAL_CONTEXT_BINDING_SNAPSHOT_CHANGED"
    return "EXTERNAL_CONTEXT_BINDING_INVALID"


__all__ = [
    "BINDINGS_FILENAME",
    "ExternalContextBindingError",
    "SCHEMA_VERSION",
    "compile_external_context_bindings",
    "load_external_context_bindings",
    "verify_external_context_binding_revision",
]
