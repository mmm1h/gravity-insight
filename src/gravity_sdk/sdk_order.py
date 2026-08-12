"""Order-product methods for the unified lazy SDK facade."""

from __future__ import annotations

from typing import Any

from .errors import InputValidationError


class OrderSdkMixin:
    """Expose Order Split Trace without duplicating its execution core."""

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

        if (
            isinstance(app, bool)
            or not isinstance(app, (str, int))
            or isinstance(app, str) and not app.strip()
        ):
            raise InputValidationError(
                "app must reference one workspace App alias or positive id",
                field="app",
            )
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


__all__ = ["OrderSdkMixin"]
