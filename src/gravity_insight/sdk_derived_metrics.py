"""Local arithmetic convenience method for the unified SDK facade."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class DerivedMetricsSdkMixin:
    def derive_metrics(
        self,
        source: Mapping[str, Any],
        spec: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Add caller-bound local arithmetic to an existing result envelope."""

        from .derived_metrics import derive_metrics

        return derive_metrics(source, spec)


__all__ = ["DerivedMetricsSdkMixin"]
