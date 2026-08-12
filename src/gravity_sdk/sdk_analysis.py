"""Analysis and snapshot convenience methods for the unified SDK facade."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


class AnalysisSdkMixin:
    """Keep Analysis product helpers cohesive without growing the core facade."""

    def saved_analyses(
        self,
        app: str | int | None = None,
        *,
        max_pages: int = 1_000,
        max_items: int = 100_000,
        workspace: Any | None = None,
    ) -> dict[str, Any]:
        """List safe saved-Analysis identities without fetching opaque configs."""

        from .saved_analysis import list_saved_analyses

        selected = self._select_workspace(workspace)
        return list_saved_analyses(
            self.insight,
            app,
            workspace=selected,
            max_pages=max_pages,
            max_items=max_items,
        )

    def prepare_saved_analysis(
        self,
        app: str | int | None,
        reference: str | int | Mapping[str, Any],
        *,
        max_pages: int = 1_000,
        max_items: int = 100_000,
        workspace: Any | None = None,
    ) -> dict[str, Any]:
        """Resolve and strictly compile one saved definition without running it."""

        from .saved_analysis import prepare_saved_analysis

        selected = self._select_workspace(workspace)
        return prepare_saved_analysis(
            self.insight,
            app=app,
            reference=reference,
            workspace=selected,
            max_pages=max_pages,
            max_items=max_items,
        )

    def get_saved_analysis(
        self,
        app: str | int | None,
        reference: str | int | Mapping[str, Any],
        *,
        max_pages: int = 1_000,
        max_items: int = 100_000,
        workspace: Any | None = None,
    ) -> dict[str, Any]:
        """Inspect replay eligibility without returning opaque configuration."""

        from .saved_analysis import inspect_saved_analysis

        selected = self._select_workspace(workspace)
        return inspect_saved_analysis(
            self.insight,
            reference,
            app,
            workspace=selected,
            max_pages=max_pages,
            max_items=max_items,
        )

    def run_saved_analysis(
        self,
        app: str | int | None,
        reference: str | int | Mapping[str, Any],
        *,
        max_pages: int = 1_000,
        max_items: int = 100_000,
        workspace: Any | None = None,
    ) -> dict[str, Any]:
        """Resolve, strictly compile, and execute one saved Analysis reference."""

        from .saved_analysis import execute_saved_analysis

        selected = self._select_workspace(workspace)
        return execute_saved_analysis(
            self.insight,
            app=app,
            reference=reference,
            workspace=selected,
            max_pages=max_pages,
            max_items=max_items,
        )

    def compile_analysis_query(
        self,
        kind: str,
        spec: Mapping[str, Any],
        *,
        app: str | int | None = None,
        start: str | None = None,
        end: str | None = None,
        workspace: Any | None = None,
    ) -> dict[str, Any]:
        from .analysis_spec import prepare_query_spec

        return prepare_query_spec(
            self.insight,
            kind,
            spec,
            workspace=self._select_workspace(workspace),
            app=app,
            start=start,
            end=end,
        )

    def analysis_query(
        self,
        kind: str,
        spec: Mapping[str, Any],
        *,
        app: str | int | None = None,
        start: str | None = None,
        end: str | None = None,
        workspace: Any | None = None,
        output_fields: Sequence[str] | None = None,
    ) -> dict[str, Any]:
        from .analysis_spec import validate_query_spec

        compiled, _validation = validate_query_spec(
            self.insight,
            kind,
            spec,
            workspace=self._select_workspace(workspace),
            app=app,
            start=start,
            end=end,
        )
        return self.read(
            compiled.operation_id, compiled.inputs, output_fields=output_fields
        )

    def prepare_segment_evaluation(
        self,
        spec: Mapping[str, Any],
        *,
        app: str | int | None = None,
        start: str | None = None,
        end: str | None = None,
        workspace: Any | None = None,
    ) -> dict[str, Any]:
        """Compile and validate a compact Segment Rule Spec without evaluation."""

        from .segment_spec import prepare_segment_spec

        return prepare_segment_spec(
            self.insight,
            spec,
            workspace=self._select_workspace(workspace),
            app=app,
            start=start,
            end=end,
        )

    def segment_evaluate(
        self,
        spec: Mapping[str, Any],
        *,
        app: str | int | None = None,
        start: str | None = None,
        end: str | None = None,
        workspace: Any | None = None,
        output_fields: Sequence[str] | None = None,
    ) -> dict[str, Any]:
        """Estimate aggregate population/ratio from one explicit compact rule."""

        from .segment_spec import compile_segment_spec

        compiled = compile_segment_spec(
            spec,
            workspace=self._select_workspace(workspace),
            app=app,
            start=start,
            end=end,
        )
        return self.read(
            compiled.operation_id,
            compiled.inputs,
            output_fields=output_fields,
        )

    def business_pulse(
        self,
        apps: str | int | Sequence[str | int],
        start: str,
        end: str,
        *,
        platforms: Sequence[str] = ("bytedance", "tencent", "kuaishou"),
        include_hourly: bool = False,
        max_workers: int = 6,
        max_pages: int = 1_000,
        max_items: int = 100_000,
        workspace: Any | None = None,
    ) -> dict[str, Any]:
        from .business_pulse import business_pulse

        selected = self._select_workspace(workspace)
        values = [apps] if isinstance(apps, (str, int)) else list(apps)
        app_ids = [self._resolve_app(selected, value) for value in values]
        return business_pulse(
            self.insight,
            app_ids,
            start,
            end,
            platforms=platforms,
            include_hourly=include_hourly,
            max_workers=max_workers,
            max_pages=max_pages,
            max_items=max_items,
        )

    def analysis_context(
        self,
        app: str | int | None = None,
        *,
        max_workers: int = 6,
        max_pages: int = 1_000,
        max_items: int = 100_000,
        workspace: Any | None = None,
    ) -> dict[str, Any]:
        from .analysis_context import analysis_context

        selected = self._select_workspace(workspace)
        return analysis_context(
            self.insight,
            self._resolve_app(selected, app),
            max_workers=max_workers,
            max_pages=max_pages,
            max_items=max_items,
        )

    def app_snapshot(
        self,
        app: str | int | None = None,
        *,
        max_workers: int = 6,
        max_pages: int = 1_000,
        max_items: int = 100_000,
        workspace: Any | None = None,
    ) -> dict[str, Any]:
        from .app_snapshot import app_snapshot

        selected = self._select_workspace(workspace)
        return app_snapshot(
            self.insight,
            self._resolve_app(selected, app),
            max_workers=max_workers,
            max_pages=max_pages,
            max_items=max_items,
        )

    def attribution_snapshot(
        self,
        app: str | int | None = None,
        *,
        max_workers: int = 6,
        max_pages: int = 1_000,
        max_items: int = 100_000,
        workspace: Any | None = None,
    ) -> dict[str, Any]:
        from .attribution import attribution_snapshot

        selected = self._select_workspace(workspace)
        return attribution_snapshot(
            self.insight,
            self._resolve_app(selected, app),
            concurrency=max_workers,
            max_pages=max_pages,
            max_items=max_items,
        )


__all__ = ["AnalysisSdkMixin"]
