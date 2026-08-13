"""Analysis and snapshot convenience methods for the unified SDK facade."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


class AnalysisSdkMixin:
    """Keep Analysis product helpers cohesive without growing the core facade."""

    def analysis_queries(
        self,
        payload: Mapping[str, Any],
        *,
        max_workers: int = 6,
        workspace: Any | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Validate or execute up to 32 compact Analysis queries through Plan v1."""

        from .analysis_query_batch import run_analysis_query_batch

        return run_analysis_query_batch(
            self,
            payload,
            workspace=self._select_workspace(workspace),
            max_workers=max_workers,
            dry_run=dry_run,
        )

    def user_journey(
        self,
        client_id: str,
        *,
        app: str | int | None = None,
        date: str | None = None,
        start: str | None = None,
        end: str | None = None,
        page: int = 1,
        page_size: int = 20,
        fields: Sequence[str] = (),
        events: Sequence[str] = (),
        max_workers: int = 3,
        max_items: int = 200,
        workspace: Any | None = None,
    ) -> dict[str, Any]:
        """Read one user's profile, event timeline, and postbacks concurrently."""

        from .user_journey import user_journey

        selected = self._select_workspace(workspace)
        app_id = self._resolve_app(selected, app)
        return user_journey(
            self.insight,
            app_id,
            client_id,
            date_value=date,
            start=start,
            end=end,
            page=page,
            page_size=page_size,
            fields=fields,
            events=events,
            max_workers=max_workers,
            max_items=max_items,
        )

    def saved_analyses(
        self,
        app: str | int | None = None,
        *,
        max_pages: int = 1_000,
        max_items: int = 100_000,
        max_workers: int = 6,
        workspace: Any | None = None,
    ) -> dict[str, Any]:
        """List safe saved-Analysis identities without fetching opaque configs."""

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
        """Resolve and strictly compile one saved definition without running it."""

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
        """Inspect replay eligibility without returning opaque configuration."""

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
        """Resolve, strictly compile, and execute one saved Analysis reference."""

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
        compare_start: str | None = None,
        compare_end: str | None = None,
        max_workers: int = 2,
        workspace: Any | None = None,
        output_fields: Sequence[str] | None = None,
    ) -> dict[str, Any]:
        if (compare_start is None) != (compare_end is None):
            from .errors import InputValidationError

            raise InputValidationError(
                "compare_start and compare_end must be provided together",
                field="compare_start/compare_end",
            )
        if compare_start is not None:
            if output_fields:
                from .errors import InputValidationError

                raise InputValidationError(
                    "period compare does not accept single-window output_fields",
                    field="output_fields",
                )
            from .analysis_period_compare import compare_analysis_periods

            return compare_analysis_periods(
                self.insight,
                kind,
                spec,
                workspace=self._select_workspace(workspace),
                app=app,
                current_start=start,
                current_end=end,
                baseline_start=compare_start,
                baseline_end=compare_end,
                max_workers=max_workers,
            )
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

    def dashboard_snapshot(
        self,
        app: str | int | None,
        ref: str | int,
        *,
        max_workers: int = 5,
        max_pages: int = 1_000,
        max_items: int = 100_000,
        workspace: Any | None = None,
    ) -> dict[str, Any]:
        """Resolve one dashboard and read its bounded control-plane snapshot."""

        from .dashboard_snapshot import dashboard_snapshot

        selected = self._select_workspace(workspace)
        app_id = self._resolve_app(selected, app)
        insight = self.insight
        return dashboard_snapshot(
            insight,
            app_id,
            ref,
            max_workers=max_workers,
            max_pages=max_pages,
            max_items=max_items,
        )

    def segment_snapshot(
        self,
        app: str | int | None,
        ref: str | int,
        *,
        date: str,
        max_workers: int = 3,
        max_pages: int = 1_000,
        max_items: int = 100_000,
        workspace: Any | None = None,
    ) -> dict[str, Any]:
        """Inspect one exact Segment's definition, history, and daily result."""

        from .segment_snapshot import (
            segment_snapshot,
            validate_segment_snapshot_request,
        )

        selected = self._select_workspace(workspace)
        app_id = self._resolve_app(selected, app)
        validate_segment_snapshot_request(
            app_id,
            ref,
            date=date,
            max_workers=max_workers,
            max_pages=max_pages,
            max_items=max_items,
        )
        insight = self.insight
        return segment_snapshot(
            insight,
            app_id,
            ref,
            date=date,
            max_workers=max_workers,
            max_pages=max_pages,
            max_items=max_items,
        )

    def prepare_dashboard_analysis(
        self,
        app: str | int | None,
        ref: str | int,
        *,
        start: str,
        end: str,
        max_charts: int = 32,
        max_items: int = 100_000,
        workspace: Any | None = None,
    ) -> dict[str, Any]:
        """Compile supported charts from one exact dashboard without running them."""

        from .dashboard_analysis import prepare_dashboard_analysis

        selected = self._select_workspace(workspace)
        app_id = self._resolve_app(selected, app)
        insight = self.insight
        return prepare_dashboard_analysis(
            insight,
            app_id,
            ref,
            start=start,
            end=end,
            max_charts=max_charts,
            max_items=max_items,
        )

    def run_dashboard_analysis(
        self,
        app: str | int | None,
        ref: str | int,
        *,
        start: str,
        end: str,
        max_workers: int = 6,
        max_charts: int = 32,
        max_items: int = 100_000,
        workspace: Any | None = None,
    ) -> dict[str, Any]:
        """Compile and execute supported dashboard charts in declaration order."""

        from .dashboard_analysis import run_dashboard_analysis

        selected = self._select_workspace(workspace)
        app_id = self._resolve_app(selected, app)
        insight = self.insight
        return run_dashboard_analysis(
            insight,
            app_id,
            ref,
            start=start,
            end=end,
            max_workers=max_workers,
            max_charts=max_charts,
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
