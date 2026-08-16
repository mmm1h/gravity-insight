"""SDK facade for the guided first-event-analysis bootstrap."""

from __future__ import annotations

from typing import Any


class BootstrapSdkMixin:
    def bootstrap_event_analysis(self, **options: Any) -> dict[str, Any]:
        """Return one reviewed, metadata-pinned Analysis Plan."""

        from .analysis_bootstrap import bootstrap_event_analysis

        return bootstrap_event_analysis(self, **options)


__all__ = ["BootstrapSdkMixin"]
