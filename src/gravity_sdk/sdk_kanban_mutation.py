"""Kanban mutation convenience methods for the unified SDK facade."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class KanbanMutationSdkMixin:
    @staticmethod
    def kanban_mutation_schema() -> dict[str, Any]:
        from .kanban_mutation import kanban_mutation_schema

        return kanban_mutation_schema()

    def kanban_mutation(
        self,
        action: str,
        inputs: Mapping[str, Any],
        *,
        execute: bool = False,
    ) -> dict[str, Any]:
        """Preview or execute one exact Kanban action, including report link/unlink."""

        from .kanban_mutation import run_kanban_mutation

        return run_kanban_mutation(self.insight, action, inputs, execute=execute)


__all__ = ["KanbanMutationSdkMixin"]
