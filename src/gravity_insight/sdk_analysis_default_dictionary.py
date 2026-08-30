"""Unified SDK surface for the Analysis default-value dictionary."""

from __future__ import annotations

from typing import Any


class AnalysisDefaultDictionarySdkMixin:
    def analysis_default_dictionary(
        self,
        app: str | int | None = None,
        *,
        workspace: Any | None = None,
    ) -> dict[str, Any]:
        """Read registered Analysis SDK default values for one workspace App."""

        from .analysis_default_dictionary import analysis_default_dictionary

        selected = self._select_workspace(workspace)
        return analysis_default_dictionary(
            self.insight, self._resolve_app(selected, app)
        )


__all__ = ["AnalysisDefaultDictionarySdkMixin"]
