"""Agent-facing facade for one explicitly bound external Context Provider."""

from __future__ import annotations

import copy
import threading
import time
from pathlib import Path
from typing import Any, Callable, Mapping

from .provider_rpc_guard import ProviderRpcGuard
from .provider_rpc_transport import ProviderTransport, SubprocessProviderTransport


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


def _public_descriptor(value: Mapping[str, Any]) -> dict[str, Any]:
    selected = copy.deepcopy(dict(value))
    binding = selected["deployment"].pop("subprocess")
    selected["deployment"]["subprocess_configured"] = binding is not None
    selected["deployment"]["subprocess_argument_count"] = (
        len(binding["arguments"]) if isinstance(binding, Mapping) else 0
    )
    return selected


__all__ = ["ExternalContextProvider", "subprocess_context_provider"]
