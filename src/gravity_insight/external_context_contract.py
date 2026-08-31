"""Strict contracts for external Context Providers and their RPC wire."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import urlparse

from .agent_runtime_contracts import AgentRuntimeContractError, canonical_digest, validate_schema
from .context_contract import (
    ContextContractError,
    clamp_context_authority,
    validate_context_item,
)


EXTERNAL_PROVIDER_SCHEMA_VERSION = "gravity.external-context-provider.v1"
RPC_REQUEST_SCHEMA_VERSION = "gravity.provider-rpc-request.v1"
RPC_RESPONSE_SCHEMA_VERSION = "gravity.provider-rpc-response.v1"
RPC_RESULT_SCHEMA_VERSION = "gravity.provider-rpc-result.v1"
_PROVIDER_SCHEMA = "external-context-provider-v1.schema.json"
_REQUEST_SCHEMA = "provider-rpc-request-v1.schema.json"
_RESPONSE_SCHEMA = "provider-rpc-response-v1.schema.json"
_RESULT_SCHEMA = "provider-rpc-result-v1.schema.json"
_PROVIDER_URI = re.compile(
    r"^context-provider://[a-z0-9.-]+/(?P<path>[a-z0-9./-]+)@(?P<version>[1-9][0-9]*)$"
)
_SAFE_OPERATION_FIELDS = {
    "list": frozenset({"cursor", "limit"}),
    "search": frozenset({"query", "cursor", "limit"}),
    "read": frozenset({"resource_uri"}),
    "list_changed": frozenset({"since_revision", "cursor", "limit"}),
}
_REQUIRED_OPERATION_FIELDS = {
    "list": frozenset(),
    "search": frozenset({"query"}),
    "read": frozenset({"resource_uri"}),
    "list_changed": frozenset({"since_revision"}),
}
_READ_RESOURCE_FIELDS = frozenset(
    {
        "uri",
        "title",
        "resource_type",
        "source_revision",
        "item_id",
        "fact_id",
        "entity_refs",
        "valid_time",
        "effective_range",
        "observed_at",
        "authority",
        "freshness",
        "supersedes",
        "sensitivity",
        "citation",
        "content",
        "content_hash",
    }
)


class ExternalContextContractError(AgentRuntimeContractError):
    """An external Provider descriptor or RPC envelope is invalid."""

    def __init__(self, reason_code: str, message: str) -> None:
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {message}")


def compile_external_provider(value: Mapping[str, Any]) -> dict[str, Any]:
    contract = _contract(value, _PROVIDER_SCHEMA, "PROVIDER_DESCRIPTOR_INVALID")
    _validate_provider_identity(contract)
    _validate_provider_read_boundary(contract)
    normalized = _normalized_provider(contract)
    _validate_provider_transport(normalized)
    _validate_provider_capabilities(normalized)
    _validate_provider_authority(normalized)
    return {"contract": normalized, "digest": canonical_digest(normalized)}


def _validate_provider_identity(contract: Mapping[str, Any]) -> None:
    match = _PROVIDER_URI.fullmatch(contract["uri"])
    if (
        match is None
        or int(match.group("version")) != contract["version"]
        or match.group("path").split("/")[-1] != contract["provider_id"]
    ):
        raise ExternalContextContractError(
            "PROVIDER_DESCRIPTOR_INVALID", "Provider identity fields disagree"
        )


def _validate_provider_read_boundary(contract: Mapping[str, Any]) -> None:
    if contract["effects"] != ["read"] or contract["role"] != "data":
        raise ExternalContextContractError(
            "PROVIDER_EFFECT_UNSUPPORTED", "External Context Providers are read-only data"
        )


def _normalized_provider(contract: Mapping[str, Any]) -> dict[str, Any]:
    normalized = copy.deepcopy(contract)
    for field in ("resource_types", "allowed_resource_prefixes"):
        normalized[field] = sorted(normalized[field])
    normalized["capabilities"]["operations"] = sorted(
        normalized["capabilities"]["operations"]
    )
    normalized["capabilities"]["output_formats"] = sorted(
        normalized["capabilities"]["output_formats"]
    )
    normalized["deployment"]["declared_egress_hosts"] = sorted(
        normalized["deployment"]["declared_egress_hosts"]
    )
    for prefix in normalized["allowed_resource_prefixes"]:
        _resource_prefix(prefix)
    for host in normalized["deployment"]["declared_egress_hosts"]:
        _egress_host(host)
    return normalized


def _validate_provider_transport(normalized: Mapping[str, Any]) -> None:
    subprocess_binding = normalized["deployment"]["subprocess"]
    if normalized["transport"] == "subprocess":
        if not isinstance(subprocess_binding, Mapping):
            raise ExternalContextContractError(
                "PROVIDER_DESCRIPTOR_INVALID", "Subprocess transport requires a binding"
            )
        executable = Path(str(subprocess_binding["executable"]))
        working_directory = Path(str(subprocess_binding["working_directory"]))
        if not executable.is_absolute() or not working_directory.is_absolute():
            raise ExternalContextContractError(
                "PROVIDER_DESCRIPTOR_INVALID", "Subprocess paths must be absolute"
            )
        if any(_unsafe_argument(item) for item in subprocess_binding["arguments"]):
            raise ExternalContextContractError(
                "PROVIDER_DESCRIPTOR_INVALID", "Subprocess arguments contain control bytes"
            )
    elif subprocess_binding is not None:
        raise ExternalContextContractError(
            "PROVIDER_DESCRIPTOR_INVALID", "Callable transport cannot declare a subprocess"
        )


def _validate_provider_capabilities(normalized: Mapping[str, Any]) -> None:
    capabilities = normalized["capabilities"]
    if "list_changed" in capabilities["operations"] and capabilities[
        "freshness_model"
    ] == "none":
        raise ExternalContextContractError(
            "PROVIDER_DESCRIPTOR_INVALID",
            "list_changed requires a revision or freshness model",
        )


def _validate_provider_authority(normalized: Mapping[str, Any]) -> None:
    ceiling = normalized["authority_ceiling"]
    trust = normalized["source_trust"]
    alignment = normalized["capabilities"]["entity_time_alignment"]
    valid = (
        ceiling == "unverified"
        or (
            ceiling == "declared_intent"
            and trust in {"reviewed", "observed"}
            and alignment in {"full", "partial"}
        )
        or (
            ceiling == "supporting"
            and trust == "reviewed"
            and alignment in {"full", "partial"}
        )
        or (
            ceiling in {"project_authoritative", "canonical"}
            and trust == "reviewed"
            and alignment == "full"
        )
    )
    if not valid:
        raise ExternalContextContractError(
            "PROVIDER_DESCRIPTOR_INVALID",
            "Provider authority ceiling exceeds its trust or alignment capability",
        )


def build_rpc_request(
    provider_uri: str,
    operation: str,
    payload: Mapping[str, Any],
    *,
    request_id: str,
) -> dict[str, Any]:
    return compile_rpc_request(
        {
            "schema_version": RPC_REQUEST_SCHEMA_VERSION,
            "request_id": request_id,
            "provider_uri": provider_uri,
            "operation": operation,
            "payload": copy.deepcopy(dict(payload)),
        }
    )


def compile_rpc_request(value: Mapping[str, Any]) -> dict[str, Any]:
    request = _contract(value, _REQUEST_SCHEMA, "PROVIDER_RPC_REQUEST_INVALID")
    operation = request["operation"]
    payload = request["payload"]
    allowed = _SAFE_OPERATION_FIELDS[operation]
    required = _REQUIRED_OPERATION_FIELDS[operation]
    if set(payload) - allowed or not required.issubset(payload):
        raise ExternalContextContractError(
            "PROVIDER_RPC_REQUEST_INVALID", "RPC payload fields disagree with operation"
        )
    if operation == "read":
        _resource_uri(payload["resource_uri"])
    return request


def compile_rpc_response(
    value: Mapping[str, Any], *, expected_request_id: str
) -> dict[str, Any]:
    response = _contract(value, _RESPONSE_SCHEMA, "PROVIDER_RPC_RESPONSE_INVALID")
    if response["request_id"] != expected_request_id:
        raise ExternalContextContractError(
            "PROVIDER_RPC_RESPONSE_INVALID", "RPC response request identity changed"
        )
    resources = response["resources"]
    status = response["status"]
    if (
        (status == "success" and not resources)
        or (status != "success" and resources)
        or (status not in {"success", "empty"} and response["next_cursor"] is not None)
    ):
        raise ExternalContextContractError(
            "PROVIDER_RPC_RESPONSE_INVALID", "RPC response status and resources disagree"
        )
    identities = [item["uri"] for item in resources]
    if len(identities) != len(set(identities)):
        raise ExternalContextContractError(
            "PROVIDER_RPC_RESPONSE_INVALID", "RPC resources are duplicated"
        )
    normalized = copy.deepcopy(response)
    normalized["resources"] = sorted(resources, key=lambda item: item["uri"])
    for resource in normalized["resources"]:
        _resource_uri(resource["uri"])
        if "content" in resource:
            expected = hashlib.sha256(resource["content"].encode("utf-8")).hexdigest()
            if resource.get("content_hash") != expected:
                raise ExternalContextContractError(
                    "PROVIDER_RESOURCE_HASH_MISMATCH", "Provider content digest changed"
                )
        elif "content_hash" in resource:
            raise ExternalContextContractError(
                "PROVIDER_RPC_RESPONSE_INVALID", "Content hash has no content"
            )
    return normalized


def decode_rpc_response(
    content: bytes,
    *,
    expected_request_id: str,
    max_output_bytes: int,
    max_output_tokens: int,
) -> tuple[dict[str, Any], int]:
    if not isinstance(content, bytes) or len(content) > max_output_bytes:
        raise ExternalContextContractError(
            "PROVIDER_RPC_OUTPUT_LIMIT", "Provider output exceeds its byte budget"
        )
    token_units = len(content)
    if token_units > max_output_tokens:
        raise ExternalContextContractError(
            "PROVIDER_RPC_TOKEN_LIMIT", "Provider output exceeds its token-unit budget"
        )
    try:
        value = json.loads(
            content.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise ExternalContextContractError(
            "PROVIDER_RPC_MALFORMED", "Provider output is not strict UTF-8 JSON"
        ) from exc
    if not isinstance(value, Mapping):
        raise ExternalContextContractError(
            "PROVIDER_RPC_MALFORMED", "Provider output must be an object"
        )
    return compile_rpc_response(value, expected_request_id=expected_request_id), token_units


def normalize_external_context_item(
    provider: Mapping[str, Any], resource: Mapping[str, Any]
) -> dict[str, Any]:
    compiled = compile_external_provider(provider)["contract"]
    missing = _READ_RESOURCE_FIELDS - set(resource)
    if missing or set(resource) - _READ_RESOURCE_FIELDS:
        raise ExternalContextContractError(
            "CONTEXT_ALIGNMENT_UNSUPPORTED",
            "Provider read result lacks exact Context alignment metadata",
        )
    if not resource["entity_refs"]:
        raise ExternalContextContractError(
            "CONTEXT_ALIGNMENT_UNSUPPORTED", "Provider resource has no entity identity"
        )
    alignment = compiled["capabilities"]["entity_time_alignment"]
    authority = clamp_context_authority(
        resource["authority"], compiled["authority_ceiling"]
    )
    if compiled["source_trust"] == "untrusted" or alignment == "none":
        authority = "unverified"
    source_trust = {
        "reviewed": "reviewed",
        "observed": "observed",
        "untrusted": "untrusted",
    }[compiled["source_trust"]]
    item = {
        "schema_version": "gravity.context-item.v1",
        "uri": resource["uri"],
        "provider_uri": compiled["uri"],
        "item_id": resource["item_id"],
        "fact_id": resource["fact_id"],
        "resource_type": resource["resource_type"],
        "title": resource["title"],
        "entity_refs": sorted(resource["entity_refs"]),
        "resolved_entity_refs": sorted(resource["entity_refs"]),
        "valid_time": copy.deepcopy(resource["valid_time"]),
        "effective_range": copy.deepcopy(resource["effective_range"]),
        "observed_at": resource["observed_at"],
        "authority": authority,
        "source_revision": resource["source_revision"],
        "content_hash": resource["content_hash"],
        "freshness": resource["freshness"],
        "source_trust": source_trust,
        "supersedes": sorted(resource["supersedes"]),
        "sensitivity": resource["sensitivity"],
        "role": "data",
        "citation": copy.deepcopy(resource["citation"]),
        "content": resource["content"],
    }
    try:
        return validate_context_item(item)
    except ContextContractError as exc:
        raise ExternalContextContractError(
            "CONTEXT_ALIGNMENT_UNSUPPORTED", "Provider resource is not a Context Item"
        ) from exc


def compile_rpc_result(value: Mapping[str, Any]) -> dict[str, Any]:
    result = _contract(value, _RESULT_SCHEMA, "PROVIDER_RPC_RESULT_INVALID")
    _validate_result_status(result)
    _validate_result_payload(result)
    _validate_result_items(result)
    return result


def _validate_result_status(result: Mapping[str, Any]) -> None:
    gap = result["status"] == "context_gap"
    if (
        result["ok"] == gap
        or bool(result["reason_codes"]) != gap
        or (result["exit_code"] is not None) != gap
        or (gap and (result["resources"] or result["context_items"]))
    ):
        raise ExternalContextContractError(
            "PROVIDER_RPC_RESULT_INVALID", "RPC result status fields disagree"
        )


def _validate_result_payload(result: Mapping[str, Any]) -> None:
    populated = bool(result["resources"] or result["context_items"])
    invalid_status = (result["status"] == "success" and not populated) or (
        result["status"] == "empty" and populated
    )
    read_shape = result["operation"] == "read" and (
        bool(result["resources"]) or result["next_cursor"] is not None
    )
    collection_shape = result["operation"] != "read" and bool(
        result["context_items"]
    )
    if invalid_status or read_shape or collection_shape:
        raise ExternalContextContractError(
            "PROVIDER_RPC_RESULT_INVALID", "RPC result payload fields disagree"
        )


def _validate_result_items(result: Mapping[str, Any]) -> None:
    for item in result["context_items"]:
        try:
            validate_context_item(item)
        except ContextContractError as exc:
            raise ExternalContextContractError(
                "PROVIDER_RPC_RESULT_INVALID", "RPC result Context Item changed"
            ) from exc
    uris = [item["uri"] for item in result["resources"]]
    if uris != sorted(uris) or len(uris) != len(set(uris)):
        raise ExternalContextContractError(
            "PROVIDER_RPC_RESULT_INVALID", "RPC result resources are not deterministic"
        )


def resource_summary(resource: Mapping[str, Any]) -> dict[str, Any]:
    fields = (
        "uri",
        "title",
        "resource_type",
        "source_revision",
        "entity_refs",
        "valid_time",
        "effective_range",
        "authority",
        "freshness",
        "sensitivity",
    )
    return {
        field: copy.deepcopy(resource[field])
        for field in fields
        if field in resource
    }


def resource_is_allowed(uri: str, prefixes: Sequence[str]) -> bool:
    return any(uri.startswith(prefix) for prefix in prefixes)


def _contract(value: Mapping[str, Any], schema: str, reason: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ExternalContextContractError(reason, "Contract must be an object")
    contract = copy.deepcopy(dict(value))
    try:
        validate_schema(contract, schema, reason)
    except AgentRuntimeContractError as exc:
        raise ExternalContextContractError(reason, str(exc)) from exc
    return contract


def _resource_prefix(value: str) -> None:
    _resource_uri(value)
    if not value.endswith("/"):
        raise ExternalContextContractError(
            "PROVIDER_DESCRIPTOR_INVALID", "Resource prefixes must end with slash"
        )


def _resource_uri(value: str) -> None:
    try:
        parsed = urlparse(value)
    except ValueError as exc:
        raise ExternalContextContractError(
            "PROVIDER_RESOURCE_INVALID", "Provider resource URI is unsafe"
        ) from exc
    if (
        not parsed.scheme
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or "%" in value
        or "\\" in value
        or "/../" in f"{parsed.path}/"
        or "/./" in f"{parsed.path}/"
        or parsed.netloc != parsed.netloc.casefold()
        or any(ord(character) < 32 for character in value)
    ):
        raise ExternalContextContractError(
            "PROVIDER_RESOURCE_INVALID", "Provider resource URI is unsafe"
        )


def _egress_host(value: str) -> None:
    _host, separator, port = value.rpartition(":")
    if separator and (not port.isdigit() or not 1 <= int(port) <= 65535):
        raise ExternalContextContractError(
            "PROVIDER_DESCRIPTOR_INVALID", "Declared egress port is invalid"
        )


def _unsafe_argument(value: Any) -> bool:
    if not isinstance(value, str) or any(
        character in value for character in ("\x00", "\r", "\n")
    ):
        return True
    lowered = value.casefold()
    return any(
        marker in lowered
        for marker in (
            "--token",
            "--password",
            "--secret",
            "--cookie",
            "--authorization",
            "--api-key",
            "token=",
            "password=",
            "secret=",
            "cookie=",
            "authorization=",
            "api_key=",
        )
    )


def _unique_object(values: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in values:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant: {value}")


__all__ = [
    "EXTERNAL_PROVIDER_SCHEMA_VERSION",
    "RPC_REQUEST_SCHEMA_VERSION",
    "RPC_RESPONSE_SCHEMA_VERSION",
    "RPC_RESULT_SCHEMA_VERSION",
    "ExternalContextContractError",
    "build_rpc_request",
    "compile_external_provider",
    "compile_rpc_request",
    "compile_rpc_response",
    "compile_rpc_result",
    "decode_rpc_response",
    "normalize_external_context_item",
    "resource_is_allowed",
    "resource_summary",
]
