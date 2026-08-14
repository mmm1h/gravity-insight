"""Promotion-product methods for the unified lazy SDK facade."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from .errors import InputValidationError


class PromotionSdkMixin:
    """Expose Promotion Performance without duplicating its core."""

    def promotion_performance(
        self,
        app: str | int,
        start: str,
        end: str,
        *,
        platforms: Sequence[str],
        metrics: Sequence[str],
        max_workers: int = 6,
        max_pages: int = 1_000,
        max_items: int = 100_000,
        workspace: Any | None = None,
    ) -> dict[str, Any]:
        """Read requested physical metrics with platform-level concurrency."""

        from .promotion_performance import (
            promotion_performance,
            validate_promotion_performance_request,
        )

        # Reject every closed product input before workspace/client construction.
        if (
            isinstance(app, bool)
            or not isinstance(app, (str, int))
            or isinstance(app, str) and not app.strip()
        ):
            raise InputValidationError(
                "app must reference one workspace App alias or positive id",
                field="app",
            )
        validate_promotion_performance_request(
            1,
            start,
            end,
            platforms=platforms,
            metrics=metrics,
            max_workers=max_workers,
            max_pages=max_pages,
            max_items=max_items,
        )
        selected = self._select_workspace(workspace)
        app_id = self._resolve_app(selected, app)
        validate_promotion_performance_request(
            app_id,
            start,
            end,
            platforms=platforms,
            metrics=metrics,
            max_workers=max_workers,
            max_pages=max_pages,
            max_items=max_items,
        )
        return promotion_performance(
            self.insight,
            app_id,
            start,
            end,
            platforms=platforms,
            metrics=metrics,
            max_workers=max_workers,
            max_pages=max_pages,
            max_items=max_items,
        )

    def advertiser_profile(
        self,
        start: str,
        end: str,
        *,
        max_pages: int = 1_000,
        max_items: int = 100_000,
    ) -> dict[str, Any]:
        """Read the complete governed Bytedance advertiser account directory."""

        from .advertiser_profile import advertiser_profile
        from .composite_batch import validate_composite_bounds
        from .promotion_performance_request import normalize_promotion_window

        normalize_promotion_window(start, end)
        validate_composite_bounds(max_pages, max_items, minimum_items=1)
        return advertiser_profile(
            self.insight,
            start,
            end,
            max_pages=max_pages,
            max_items=max_items,
        )


__all__ = ["PromotionSdkMixin"]
