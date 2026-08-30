"""Lazy client boundary for discovery paths backed by local catalogs."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


class DeferredAgentClient:
    """Build the Insight client only when discovery reads its inventory."""

    def __init__(self, factory: Callable[[], Any]) -> None:
        self._factory = factory
        self._client: Any | None = None

    def __getattr__(self, name: str) -> Any:
        client = self._client
        if client is None:
            client = self._factory()
            self._client = client
        return getattr(client, name)

    def loaded_attribute(self, name: str) -> Any | None:
        """Return an attribute only when the deferred client already exists."""

        client = self._client
        return getattr(client, name, None) if client is not None else None


__all__ = ["DeferredAgentClient"]
