"""Realtime-event mutation convenience methods for the unified SDK facade."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class RealtimeEventSdkMixin:
    @staticmethod
    def realtime_event_mutation_schema() -> dict[str, Any]:
        from .realtime_event_mutation import realtime_event_mutation_schema

        return realtime_event_mutation_schema()

    def realtime_event_mutation(
        self, inputs: Mapping[str, Any], *, execute: bool = False
    ) -> dict[str, Any]:
        from .realtime_event_mutation import run_realtime_event_mutation

        return run_realtime_event_mutation(self.insight, inputs, execute=execute)

    def realtime_event_catalog(
        self,
        app: str | int | None = None,
        *,
        start: str,
        end: str,
        event_type: str = "profile",
        workspace: Any | None = None,
    ) -> dict[str, Any]:
        """Read one first page of the realtime-event catalog for a workspace App."""

        from .realtime_event_catalog import realtime_event_catalog

        selected = self._select_workspace(workspace)
        return realtime_event_catalog(
            self.insight,
            self._resolve_app(selected, app),
            start=start,
            end=end,
            event_type=event_type,
        )


__all__ = ["RealtimeEventSdkMixin"]
