"""Attribution convenience methods for the unified SDK facade."""

from __future__ import annotations

from typing import Any


class AttributionSdkMixin:
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

    def attribution_performance(
        self,
        app: str | int | None,
        *,
        start: str,
        end: str,
        max_workers: int = 4,
        max_pages: int = 1,
        max_items: int = 100_000,
        workspace: Any | None = None,
    ) -> dict[str, Any]:
        """Read the four governed attribution-performance panels."""

        from .attribution import attribution_performance

        selected = self._select_workspace(workspace)
        return attribution_performance(
            self.insight,
            self._resolve_app(selected, app),
            start,
            end,
            max_workers=max_workers,
            max_pages=max_pages,
            max_items=max_items,
        )

    def attribution_user_detail(
        self,
        app: str | int | None,
        device_id: str | int,
        *,
        workspace: Any | None = None,
    ) -> dict[str, Any]:
        """Read one caller-selected registered testing-device attribution detail."""

        from .attribution import attribution_user_detail

        selected = self._select_workspace(workspace)
        return attribution_user_detail(
            self.insight,
            self._resolve_app(selected, app),
            device_id,
        )


__all__ = ["AttributionSdkMixin"]
