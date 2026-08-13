"""Order-product methods for the unified lazy SDK facade."""

from __future__ import annotations

from typing import Any

from .errors import InputValidationError


class OrderSdkMixin:
    """Expose bounded order products without duplicating their execution cores."""

    def order_directory(
        self,
        app: str | int,
        date: str,
        *,
        max_workers: int = 6,
        max_pages: int = 1_000,
        max_items: int = 100_000,
        workspace: Any | None = None,
    ) -> dict[str, Any]:
        """Read one complete identifier-free daily order directory."""

        from .order_directory import order_directory, validate_order_directory_request

        _validate_app_reference(app)
        options = {
            "max_workers": max_workers,
            "max_pages": max_pages,
            "max_items": max_items,
        }
        validate_order_directory_request(1, date, **options)
        selected = self._select_workspace(workspace)
        app_id = self._resolve_app(selected, app)
        canonical = validate_order_directory_request(app_id, date, **options)
        return order_directory(self.insight, canonical[0], canonical[1], **options)

    def order_split_trace(
        self,
        app: str | int,
        date: str,
        trace_id: str,
        *,
        max_workers: int = 6,
        max_pages: int = 1_000,
        max_items: int = 100_000,
        workspace: Any | None = None,
    ) -> dict[str, Any]:
        """Read one exact split-order trace through the fixed parent-child chain."""

        from .order_trace import (
            order_split_trace,
            validate_order_split_trace_request,
        )

        _validate_app_reference(app)
        options = {
            "max_workers": max_workers,
            "max_pages": max_pages,
            "max_items": max_items,
        }
        validate_order_split_trace_request(1, date, trace_id, **options)
        selected = self._select_workspace(workspace)
        app_id = self._resolve_app(selected, app)
        canonical = validate_order_split_trace_request(
            app_id, date, trace_id, **options
        )
        return order_split_trace(
            self.insight, canonical[0], canonical[1], canonical[2], **options
        )


def _validate_app_reference(app: Any) -> None:
    if (
        isinstance(app, bool)
        or not isinstance(app, (str, int))
        or type(app) is int and (app <= 0 or app.bit_length() > 512)
        or isinstance(app, str) and (not app.strip() or len(app) > 128)
    ):
        raise InputValidationError(
            "app must reference one workspace App alias or positive id", field="app"
        )


__all__ = ["OrderSdkMixin"]
