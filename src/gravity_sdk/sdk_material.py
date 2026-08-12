"""Material-product methods for the unified lazy SDK facade."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from .errors import InputValidationError


class MaterialSdkMixin:
    """Expose governed material analysis without duplicating its core."""

    def material_performance(
        self,
        apps: str | int | Sequence[str | int],
        start: str,
        end: str,
        *,
        platforms: Sequence[str] = (
            "bytedance", "tencent", "kuaishou", "bilibili"
        ),
        max_workers: int = 6,
        max_pages: int = 1_000,
        max_items: int = 100_000,
        workspace: Any | None = None,
    ) -> dict[str, Any]:
        """Read selected platforms with one shared platform-level worker pool."""

        from .material_performance import (
            material_performance,
            validate_material_performance_request,
        )

        selected = self._select_workspace(workspace)
        if isinstance(apps, (str, int)):
            values = [apps]
        elif isinstance(apps, Sequence):
            values = list(apps)
        else:
            raise InputValidationError(
                "material performance apps must be a non-empty array",
                field="apps",
            )
        app_ids = [self._resolve_app(selected, value) for value in values]
        validate_material_performance_request(
            app_ids,
            start,
            end,
            platforms=platforms,
            max_workers=max_workers,
            max_pages=max_pages,
            max_items=max_items,
        )
        return material_performance(
            self.insight,
            app_ids,
            start,
            end,
            platforms=platforms,
            max_workers=max_workers,
            max_pages=max_pages,
            max_items=max_items,
        )


__all__ = ["MaterialSdkMixin"]
