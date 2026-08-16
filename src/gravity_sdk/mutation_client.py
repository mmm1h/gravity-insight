"""Private mutation execution hooks for governed product surfaces."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .mutation import MutationExecutor


class MutationClientMixin:
    """Bind mutation execution to the same registry, policy, and transport."""

    def _initialize_mutation_client(self) -> None:
        executor = self._executor
        self._mutation_executor = MutationExecutor(
            executor._registry, executor._policy, executor._transport
        )
        self._mutation_executor.bind_call_guard(self._operation_catalog.guard)

    def _preview_mutation(
        self, operation_id: str, inputs: Mapping[str, Any]
    ) -> dict[str, Any]:
        return self._mutation_executor.preview(operation_id, inputs)

    def _execute_mutation(
        self, operation_id: str, inputs: Mapping[str, Any]
    ) -> dict[str, Any]:
        result = self._mutation_executor.execute(operation_id, inputs)
        # Mutation guards must observe upstream state, never a pre-write metadata
        # cache entry retained by the shared read client.
        self._metadata_cache.clear()
        return result

    def _current_principal_id(self) -> str | None:
        """Return the shared runtime principal for domain ownership preflight."""

        return self._executor._transport.current_principal_id()


__all__ = ["MutationClientMixin"]
