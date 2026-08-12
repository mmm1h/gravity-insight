"""Report-product convenience methods for the unified lazy SDK facade."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .errors import InputValidationError


class ReportSdkMixin:
    """Expose governed report products without duplicating their execution core."""

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
