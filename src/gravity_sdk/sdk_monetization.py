"""Monetization-product methods for the unified lazy SDK facade."""

from __future__ import annotations

from typing import Any


class MonetizationSdkMixin:
    """Expose the identifier-free monetization product without widening Analysis."""

    def monetization_detail(
        self,
        app: str | int,
        date: str,
        *,
        max_workers: int = 6,
        max_pages: int = 1_000,
        max_items: int = 100_000,
        workspace: Any | None = None,
    ) -> dict[str, Any]:
        """Read one complete identifier-free daily monetization detail."""

        from .monetization_detail import (
            monetization_detail,
            validate_monetization_detail_request,
        )

        if (
            isinstance(app, bool)
            or not isinstance(app, (str, int))
            or type(app) is int and (app <= 0 or app.bit_length() > 512)
            or isinstance(app, str) and (not app.strip() or len(app) > 128)
        ):
            raise ValueError("app must reference one workspace App alias or positive id")
        options = {
            "max_workers": max_workers,
            "max_pages": max_pages,
            "max_items": max_items,
        }
        validate_monetization_detail_request(1, date, **options)
        selected = self._select_workspace(workspace)
        app_id = self._resolve_app(selected, app)
        canonical = validate_monetization_detail_request(app_id, date, **options)
        return monetization_detail(
            self.insight, canonical[0], canonical[1], **options
        )


__all__ = ["MonetizationSdkMixin"]
