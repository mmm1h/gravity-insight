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
        event_name: str | None = None,
        client_lib: str | None = None,
        client_lib_version: str | None = None,
        client_id: str | None = None,
        request_id: str | None = None,
        properties: list[Mapping[str, Any]] | None = None,
        property_fields: tuple[str, ...] | list[str] = (),
        workspace: Any | None = None,
    ) -> dict[str, Any]:
        """Read bounded realtime SDK diagnostics for a workspace App."""

        from .realtime_event_catalog import realtime_event_catalog

        selected = self._select_workspace(workspace)
        return realtime_event_catalog(
            self.insight,
            self._resolve_app(selected, app),
            start=start,
            end=end,
            event_type=event_type,
            event_name=event_name,
            client_lib=client_lib,
            client_lib_version=client_lib_version,
            client_id=client_id,
            request_id=request_id,
            properties=properties,
            property_fields=property_fields,
        )


__all__ = ["RealtimeEventSdkMixin"]
