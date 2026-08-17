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


__all__ = ["RealtimeEventSdkMixin"]
