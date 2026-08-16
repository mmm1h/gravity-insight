"""Report-product convenience methods for the unified lazy SDK facade."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .errors import InputValidationError


class ReportSdkMixin:
    """Expose governed report products without duplicating their execution core."""

    @staticmethod
    def semantic_compose_input_schema() -> dict[str, Any]:
        """Return the registered semantic composition contract offline."""

        from .semantic_compose import semantic_compose_input_schema

        return semantic_compose_input_schema()

    def prepare_semantic_compose(
        self,
        inputs: Mapping[str, Any],
        *,
        app: str | int | None,
        workspace: Any | None = None,
    ) -> dict[str, Any]:
        """Resolve App scope and deterministically compile without a client."""

        from .semantic_compose import compile_semantic_compose

        selected = self._select_workspace(workspace)
        app_id = self._resolve_app(selected, app)
        return compile_semantic_compose(inputs, app_id=app_id)

    def semantic_compose(
        self,
        inputs: Mapping[str, Any],
        *,
        app: str | int | None,
        max_pages: int = 1_000,
        max_items: int = 100_000,
        workspace: Any | None = None,
    ) -> dict[str, Any]:
        """Execute one compiled semantic definition through Multidim."""

        from .semantic_compose import run_semantic_compose

        selected = self._select_workspace(workspace)
        app_id = self._resolve_app(selected, app)
        _validate_limits(max_pages, max_items, 1)
        return run_semantic_compose(
            self.insight,
            inputs,
            app_id=app_id,
            max_pages=max_pages,
            max_items=max_items,
        )

    @staticmethod
    def multidim_input_schema() -> dict[str, Any]:
        """Return the closed Multidim product input contract entirely offline."""

        from .multidim_product import multidim_input_schema

        return multidim_input_schema()

    def prepare_multidim_query(
        self,
        inputs: Mapping[str, Any],
        *,
        app: str | int | None,
        workspace: Any | None = None,
    ) -> dict[str, Any]:
        """Normalize, bind, and validate one Multidim request without a client."""

        from .multidim_product import (
            bind_multidim_app,
            normalize_multidim_inputs,
            prepare_multidim_query,
        )

        selected = self._select_workspace(workspace)
        app_id = self._resolve_app(selected, app)
        normalized = normalize_multidim_inputs(inputs)
        bound = bind_multidim_app(normalized, app_id)
        return prepare_multidim_query(None, bound, app_id=app_id)

    def validate_multidim_query(
        self,
        inputs: Mapping[str, Any],
        *,
        app: str | int | None,
        workspace: Any | None = None,
    ) -> dict[str, Any]:
        """Compatibility spelling for the zero-network product preflight."""

        return self.prepare_multidim_query(inputs, app=app, workspace=workspace)

    def multidim_query(
        self,
        inputs: Mapping[str, Any],
        *,
        app: str | int | None,
        include_total: bool = False,
        read_all: bool = False,
        max_pages: int = 1_000,
        max_items: int = 100_000,
        max_workers: int = 6,
        workspace: Any | None = None,
    ) -> dict[str, Any]:
        """Execute one App-bound Multidim product through the shared core."""

        from .multidim_product import (
            bind_multidim_app,
            normalize_multidim_inputs,
            run_multidim_query,
        )

        selected = self._select_workspace(workspace)
        app_id = self._resolve_app(selected, app)
        _validate_limits(max_pages, max_items, max_workers)
        _boolean(include_total, "include_total")
        _boolean(read_all, "read_all")
        normalized = normalize_multidim_inputs(inputs)
        bound = bind_multidim_app(normalized, app_id)
        insight = self.insight
        return run_multidim_query(
            insight,
            bound,
            app_id=app_id,
            include_total=include_total,
            read_all=read_all,
            max_pages=max_pages,
            max_items=max_items,
            max_workers=max_workers,
        )

    def company_usage(
        self,
        *,
        max_pages: int = 1_000,
        max_items: int = 100_000,
    ) -> dict[str, Any]:
        """Read the complete company-level daily resource-usage trend."""

        from .company_usage import company_usage

        _validate_limits(max_pages, max_items, 1)
        return company_usage(
            self.insight,
            max_pages=max_pages,
            max_items=max_items,
        )

    def report_directory(
        self, *, max_pages: int = 1_000, max_items: int = 100_000,
        max_workers: int = 6,
    ) -> dict[str, Any]:
        """Read all owned reports and their definitions."""

        from .report_products import report_directory

        _validate_limits(max_pages, max_items, max_workers)
        return report_directory(
            self.insight, max_pages=max_pages, max_items=max_items,
            max_workers=max_workers,
        )

    def report_subscriptions(
        self, *, max_pages: int = 1_000, max_items: int = 100_000,
    ) -> dict[str, Any]:
        """Read the complete bounded report-subscription list."""

        from .report_products import report_subscriptions

        _validate_limits(max_pages, max_items, 1)
        return report_subscriptions(
            self.insight, max_pages=max_pages, max_items=max_items,
        )

    def create_report(self, **options: Any) -> dict[str, Any]:
        """Preview or explicitly create one marked report."""

        from .report_mutation import create_report

        return create_report(self.insight, **options)

    def delete_report(self, report_id: int, *, execute: bool = False) -> dict[str, Any]:
        """Preview or explicitly delete one marked report."""

        from .report_mutation import delete_report

        return delete_report(self.insight, report_id, execute=execute)

    def create_report_subscription(self, **options: Any) -> dict[str, Any]:
        """Preview or explicitly create one disabled marked subscription."""

        from .report_mutation import create_subscription

        return create_subscription(self.insight, **options)

    def delete_report_subscription(
        self, subscription_id: int, *, execute: bool = False,
    ) -> dict[str, Any]:
        """Preview or explicitly delete one marked subscription."""

        from .report_mutation import delete_subscription

        return delete_subscription(self.insight, subscription_id, execute=execute)


def _validate_limits(max_pages: Any, max_items: Any, max_workers: Any) -> None:
    for field, value, maximum in (
        ("max_pages", max_pages, 1_000),
        ("max_items", max_items, 100_000),
        ("max_workers", max_workers, 24),
    ):
        if type(value) is not int or not 1 <= value <= maximum:
            raise InputValidationError(
                f"{field} must be between 1 and {maximum}", field=field
            )


def _boolean(value: Any, field: str) -> None:
    if not isinstance(value, bool):
        raise InputValidationError(f"{field} must be a boolean", field=field)


__all__ = ["ReportSdkMixin"]
