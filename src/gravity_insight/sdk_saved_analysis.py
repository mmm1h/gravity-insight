"""Saved Analysis read, replay, and governed mutation facade methods."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class SavedAnalysisSdkMixin:
    def saved_analyses(
        self,
        app: str | int | None = None,
        *,
        max_pages: int = 1_000,
        max_items: int = 100_000,
        max_workers: int = 6,
        workspace: Any | None = None,
    ) -> dict[str, Any]:
        """List identities without reading configs; replay remains unchecked."""

        from .saved_analysis import list_saved_analyses
        from .saved_analysis_support import bounds, workers

        selected = self._select_workspace(workspace)
        bounds(max_pages, max_items)
        workers(max_workers)
        app_id = self._resolve_app(selected, app)
        return list_saved_analyses(
            self.insight,
            app_id,
            workspace=selected,
            max_pages=max_pages,
            max_items=max_items,
            max_workers=max_workers,
        )

    def prepare_saved_analysis(
        self,
        app: str | int | None,
        reference: str | int | Mapping[str, Any],
        *,
        start: str | None = None,
        end: str | None = None,
        max_pages: int = 1_000,
        max_items: int = 100_000,
        max_workers: int = 6,
        workspace: Any | None = None,
    ) -> dict[str, Any]:
        from .saved_analysis import prepare_saved_analysis
        from .saved_analysis_artifact import validate_saved_window
        from .saved_analysis_support import bounds, normalize_reference, workers

        normalize_reference(reference)
        bounds(max_pages, max_items)
        workers(max_workers)
        selected = self._select_workspace(workspace)
        validate_saved_window(start, end)
        app_id = self._resolve_app(selected, app)
        return prepare_saved_analysis(
            self.insight,
            app=app_id,
            reference=reference,
            workspace=selected,
            max_pages=max_pages,
            max_items=max_items,
            max_workers=max_workers,
            start=start,
            end=end,
        )

    def get_saved_analysis(
        self,
        app: str | int | None,
        reference: str | int | Mapping[str, Any],
        *,
        start: str | None = None,
        end: str | None = None,
        max_pages: int = 1_000,
        max_items: int = 100_000,
        max_workers: int = 6,
        workspace: Any | None = None,
    ) -> dict[str, Any]:
        from .saved_analysis import inspect_saved_analysis
        from .saved_analysis_artifact import validate_saved_window
        from .saved_analysis_support import bounds, normalize_reference, workers

        normalize_reference(reference)
        bounds(max_pages, max_items)
        workers(max_workers)
        selected = self._select_workspace(workspace)
        validate_saved_window(start, end)
        app_id = self._resolve_app(selected, app)
        return inspect_saved_analysis(
            self.insight,
            reference,
            app_id,
            workspace=selected,
            max_pages=max_pages,
            max_items=max_items,
            max_workers=max_workers,
            start=start,
            end=end,
        )

    def run_saved_analysis(
        self,
        app: str | int | None,
        reference: str | int | Mapping[str, Any],
        *,
        start: str | None = None,
        end: str | None = None,
        max_pages: int = 1_000,
        max_items: int = 100_000,
        max_workers: int = 6,
        workspace: Any | None = None,
    ) -> dict[str, Any]:
        from .saved_analysis import execute_saved_analysis
        from .saved_analysis_artifact import validate_saved_window
        from .saved_analysis_support import bounds, normalize_reference, workers

        normalize_reference(reference)
        bounds(max_pages, max_items)
        workers(max_workers)
        selected = self._select_workspace(workspace)
        validate_saved_window(start, end)
        app_id = self._resolve_app(selected, app)
        return execute_saved_analysis(
            self.insight,
            app=app_id,
            reference=reference,
            workspace=selected,
            max_pages=max_pages,
            max_items=max_items,
            max_workers=max_workers,
            start=start,
            end=end,
        )

    def create_saved_analysis(
        self,
        *,
        app: str | int | None,
        name: str,
        subject: str,
        config: Mapping[str, Any],
        remark: str = "",
        idempotency_key: str | None = None,
        start: str | None = None,
        end: str | None = None,
        execute: bool = False,
        workspace: Any | None = None,
    ) -> dict[str, Any]:
        from .saved_analysis_mutation import create_saved_analysis

        selected = self._select_workspace(workspace)
        app_id = self._resolve_app(selected, app)
        return create_saved_analysis(
            self.insight,
            app_id=app_id,
            name=name,
            subject=subject,
            config=config,
            remark=remark,
            idempotency_key=idempotency_key,
            workspace=selected,
            start=start,
            end=end,
            execute=execute,
        )

    def update_saved_analysis(
        self,
        analysis_id: str | int,
        *,
        app: str | int | None,
        name: str,
        subject: str,
        config: Mapping[str, Any],
        remark: str = "",
        start: str | None = None,
        end: str | None = None,
        execute: bool = False,
        workspace: Any | None = None,
    ) -> dict[str, Any]:
        from .saved_analysis_mutation import update_saved_analysis

        selected = self._select_workspace(workspace)
        app_id = self._resolve_app(selected, app)
        return update_saved_analysis(
            self.insight,
            analysis_id,
            app_id=app_id,
            name=name,
            subject=subject,
            config=config,
            remark=remark,
            workspace=selected,
            start=start,
            end=end,
            execute=execute,
        )

    def delete_saved_analysis(
        self,
        analysis_id: str | int,
        *,
        app: str | int | None,
        execute: bool = False,
        workspace: Any | None = None,
    ) -> dict[str, Any]:
        from .saved_analysis_mutation import delete_saved_analysis

        selected = self._select_workspace(workspace)
        app_id = self._resolve_app(selected, app)
        return delete_saved_analysis(
            self.insight,
            analysis_id,
            app_id=app_id,
            workspace=selected,
            execute=execute,
        )


__all__ = ["SavedAnalysisSdkMixin"]
