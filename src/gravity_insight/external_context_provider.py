"""Agent-facing facade for one explicitly bound external Context Provider."""

from __future__ import annotations

import copy
import threading
import time
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .provider_rpc_guard import ProviderRpcGuard
from .provider_rpc_transport import (
    CallableProviderTransport,
    ProviderTransport,
    SubprocessProviderTransport,
)
import hashlib
import json


_FIXTURE_FIELDS = {
    "schema_version",
    "observed_at",
    "previous_snapshot_revision",
    "changed_resource_uris",
    "resources",
}
_RESOURCE_FIELDS = {
    "uri",
    "title",
    "resource_type",
    "item_id",
    "fact_id",
    "entity_refs",
    "valid_time",
    "effective_range",
    "authority",
    "supersedes",
    "sensitivity",
    "citation_path",
    "content",
}


class ExternalContextProvider:
    """Expose read-only Provider operations without binding them to a Skill."""

    def __init__(
        self,
        descriptor: Mapping[str, Any],
        transport: ProviderTransport,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._guard = ProviderRpcGuard(descriptor, transport, clock=clock)

    def describe(self) -> dict[str, Any]:
        return {
            "schema_version": "gravity.external-context-provider-description.v1",
            "status": "success",
            "provider": _public_descriptor(self._guard.descriptor),
            "provider_digest": self._guard.descriptor_digest,
            "provider_internal_io_controlled": False,
            "provider_internal_network": "not_observable",
        }

    def list(
        self,
        *,
        cursor: str | None = None,
        limit: int = 50,
        cancellation: threading.Event | None = None,
    ) -> dict[str, Any]:
        return self._guard.invoke(
            "list", {"cursor": cursor, "limit": limit}, cancellation=cancellation
        )

    def search(
        self,
        query: str,
        *,
        cursor: str | None = None,
        limit: int = 50,
        cancellation: threading.Event | None = None,
    ) -> dict[str, Any]:
        return self._guard.invoke(
            "search",
            {"query": query, "cursor": cursor, "limit": limit},
            cancellation=cancellation,
        )

    def read(
        self,
        resource_uri: str,
        *,
        cancellation: threading.Event | None = None,
    ) -> dict[str, Any]:
        return self._guard.invoke(
            "read", {"resource_uri": resource_uri}, cancellation=cancellation
        )

    def list_changed(
        self,
        since_revision: str,
        *,
        cursor: str | None = None,
        limit: int = 50,
        cancellation: threading.Event | None = None,
    ) -> dict[str, Any]:
        return self._guard.invoke(
            "list_changed",
            {
                "since_revision": since_revision,
                "cursor": cursor,
                "limit": limit,
            },
            cancellation=cancellation,
        )

    def metrics(self) -> dict[str, Any]:
        return self._guard.metrics()


def subprocess_context_provider(
    descriptor: Mapping[str, Any],
    *,
    work_root: str | Path,
    environment: Mapping[str, str] | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> ExternalContextProvider:
    transport = SubprocessProviderTransport(
        descriptor, work_root=work_root, environment=environment
    )
    return ExternalContextProvider(descriptor, transport, clock=clock)


def feishu_fixture_provider_descriptor() -> dict[str, Any]:
    """Return the fixed test descriptor without discovering Providers."""

    return {
        "artifact_kind": "external_context_provider",
        "schema_version": "gravity.external-context-provider.v1",
        "uri": "context-provider://gravity/feishu-fixture@1",
        "version": 1,
        "provider_id": "feishu-fixture",
        "owner": "gravity-runtime/context",
        "transport": "host",
        "effects": ["read"],
        "auth_scope": "project",
        "resource_types": ["document", "project_semantic"],
        "allowed_resource_prefixes": [
            "feishu://fixture/base/",
            "feishu://fixture/docx/",
        ],
        "capabilities": {
            "operations": ["list", "search", "read", "list_changed"],
            "supports_cancellation": True,
            "supports_cache": True,
            "output_formats": ["json"],
            "freshness_model": "content_hash",
            "entity_time_alignment": "partial",
        },
        "rpc": {
            "max_concurrency": 1,
            "max_calls_per_session": 64,
            "timeout_ms": 5_000,
            "cancellation_grace_ms": 0,
            "max_attempts": 1,
            "max_output_bytes": 262_144,
            "max_output_tokens": 262_144,
            "circuit_failure_threshold": 2,
            "circuit_cooldown_ms": 1_000,
        },
        "deployment": {
            "sandbox_owner": "gravity-runtime/context-fixture",
            "declared_egress_hosts": [],
            "inherits_gravity_credentials": False,
            "subprocess": None,
        },
        "source_trust": "observed",
        "authority_ceiling": "declared_intent",
        "role": "data",
    }


class FeishuFixtureContextProvider(ExternalContextProvider):
    """Exercise the weak-source contract locally; never calls Feishu or reads credentials."""

    def __init__(self, fixture: Mapping[str, Any]) -> None:
        descriptor = feishu_fixture_provider_descriptor()
        handler = _FeishuFixtureHandler(descriptor, fixture)
        super().__init__(
            descriptor,
            CallableProviderTransport("host", handler),
        )


class _FeishuFixtureHandler:
    def __init__(
        self, descriptor: Mapping[str, Any], fixture: Mapping[str, Any]
    ) -> None:
        fixture = copy.deepcopy(dict(fixture))
        if set(fixture) != _FIXTURE_FIELDS or fixture.get("schema_version") != (
            "gravity.feishu-context-fixture.v1"
        ):
            raise ValueError("Feishu fixture fields are invalid")
        source_revision = _snapshot_revision(fixture)
        self._resources = _fixture_resources(
            fixture["resources"],
            source_revision=source_revision,
            observed_at=fixture["observed_at"],
        )
        self._by_uri = {item["uri"]: item for item in self._resources}
        if any(
            not any(uri.startswith(prefix) for prefix in descriptor["allowed_resource_prefixes"])
            for uri in self._by_uri
        ):
            raise ValueError("Feishu fixture resource exceeds its descriptor")
        changed = fixture["changed_resource_uris"]
        if (
            not isinstance(changed, list)
            or len(changed) != len(set(changed))
            or not set(changed).issubset(self._by_uri)
        ):
            raise ValueError("Changed Feishu fixture resources are invalid")
        previous = fixture["previous_snapshot_revision"]
        if (
            not isinstance(previous, str)
            or not previous.startswith("snapshot:")
            or len(previous) != 73
            or previous == source_revision
        ):
            raise ValueError("Previous Feishu fixture snapshot is invalid")
        self._source_revision = source_revision
        self._previous_revision = previous
        self._changed = frozenset(changed)

    def __call__(
        self, request: Mapping[str, Any], cancellation: threading.Event
    ) -> dict[str, Any]:
        operation = request["operation"]
        if cancellation.is_set():
            return _fixture_response(request, "unavailable", [])
        if operation == "read":
            resource = self._by_uri.get(request["payload"]["resource_uri"])
            return _fixture_response(
                request,
                "success" if resource is not None else "empty",
                [resource] if resource is not None else [],
            )
        if operation == "list_changed":
            since = request["payload"]["since_revision"]
            if since == self._source_revision:
                return _fixture_response(request, "empty", [])
            if since != self._previous_revision:
                return _fixture_response(request, "unsupported", [])
            selected = [
                item for item in self._resources if item["uri"] in self._changed
            ]
            return self._page(request, selected)
        selected = self._resources
        if operation == "search":
            query = request["payload"]["query"].casefold()
            selected = [
                item
                for item in selected
                if query in item["title"].casefold()
                or query in item["content"].casefold()
            ]
        return self._page(request, selected)

    def _page(
        self, request: Mapping[str, Any], resources: Sequence[Mapping[str, Any]]
    ) -> dict[str, Any]:
        payload = request["payload"]
        try:
            offset = int(payload.get("cursor") or "0")
            limit = int(payload.get("limit", 50))
        except (TypeError, ValueError):
            return _fixture_response(request, "unsupported", [])
        if offset < 0 or limit < 1:
            return _fixture_response(request, "unsupported", [])
        page = list(resources[offset : offset + limit])
        next_cursor = (
            str(offset + limit) if offset + limit < len(resources) else None
        )
        return _fixture_response(
            request,
            "success" if page else "empty",
            [_fixture_summary(item) for item in page],
            next_cursor=next_cursor,
        )


def _snapshot_revision(fixture: Mapping[str, Any]) -> str:
    resources = fixture.get("resources")
    if not isinstance(resources, list) or not resources:
        raise ValueError("Feishu fixture has no resources")
    selected: list[dict[str, Any]] = []
    for resource in resources:
        if not isinstance(resource, Mapping) or set(resource) != _RESOURCE_FIELDS:
            raise ValueError("Feishu fixture resource fields are invalid")
        content = resource["content"]
        if not isinstance(content, str) or not content:
            raise ValueError("Feishu fixture content is invalid")
        selected.append(
            {
                "uri": resource["uri"],
                "content_hash": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            }
        )
    encoded = json.dumps(
        {
            "observed_at": fixture.get("observed_at"),
            "resources": sorted(selected, key=lambda item: item["uri"]),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return "snapshot:" + hashlib.sha256(encoded).hexdigest()


def _fixture_resources(
    values: Sequence[Mapping[str, Any]],
    *,
    source_revision: str,
    observed_at: str,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for value in values:
        content = value["content"]
        lines = content.splitlines()
        resource = {
            key: copy.deepcopy(value[key])
            for key in _RESOURCE_FIELDS
            if key != "citation_path"
        }
        resource.update(
            {
                "source_revision": source_revision,
                "observed_at": observed_at,
                "freshness": "current",
                "citation": {
                    "path": value["citation_path"],
                    "line_start": 1,
                    "line_end": max(1, len(lines)),
                },
                "content_hash": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            }
        )
        result.append(resource)
    uris = [item["uri"] for item in result]
    if len(uris) != len(set(uris)):
        raise ValueError("Feishu fixture resource URIs are duplicated")
    return sorted(result, key=lambda item: item["uri"])


def _fixture_summary(resource: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: copy.deepcopy(resource[key])
        for key in ("uri", "title", "resource_type", "source_revision")
    }


def _fixture_response(
    request: Mapping[str, Any],
    status: str,
    resources: Sequence[Mapping[str, Any] | None],
    *,
    next_cursor: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": "gravity.provider-rpc-response.v1",
        "request_id": request["request_id"],
        "status": status,
        "resources": [copy.deepcopy(dict(item)) for item in resources if item],
        "next_cursor": next_cursor,
        "stats": {"internal_requests": 0, "retries": 0, "cache_hits": 0},
    }


def _public_descriptor(value: Mapping[str, Any]) -> dict[str, Any]:
    selected = copy.deepcopy(dict(value))
    binding = selected["deployment"].pop("subprocess")
    selected["deployment"]["subprocess_configured"] = binding is not None
    selected["deployment"]["subprocess_argument_count"] = (
        len(binding["arguments"]) if isinstance(binding, Mapping) else 0
    )
    return selected


__all__ = [
    "ExternalContextProvider",
    "FeishuFixtureContextProvider",
    "feishu_fixture_provider_descriptor",
    "subprocess_context_provider",
]
