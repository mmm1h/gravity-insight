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

    def custom_audiences(
        self,
        *,
        max_pages: int = 1_000,
        max_items: int = 100_000,
    ) -> dict[str, Any]:
        """Read all governed custom audiences and their delivery status."""

        from .custom_audience import custom_audiences
        from .sdk_report import _validate_limits

        _validate_limits(max_pages, max_items, 1)
        return custom_audiences(
            self.insight,
            max_pages=max_pages,
            max_items=max_items,
        )

    def bilibili_account_performance(
        self,
        start: str,
        end: str,
        *,
        max_workers: int = 6,
        max_pages: int = 1_000,
        max_items: int = 100_000,
    ) -> dict[str, Any]:
        """Read Bilibili account/product metrics without App or metric selection."""

        from .bilibili_account_performance import (
            bilibili_account_performance,
            validate_bilibili_account_request,
        )

        validate_bilibili_account_request(
            start,
            end,
            max_workers=max_workers,
            max_pages=max_pages,
            max_items=max_items,
        )
        return bilibili_account_performance(
            self.insight,
            start,
            end,
            max_workers=max_workers,
            max_pages=max_pages,
            max_items=max_items,
        )


__all__ = ["PromotionSdkMixin"]
