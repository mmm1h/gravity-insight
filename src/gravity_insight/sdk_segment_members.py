"""Segment member convenience method for the unified SDK facade."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any


class SegmentMembersSdkMixin:
    def segment_members(
        self,
        app: str | int | None,
        ref: str | int,
        *,
        fields: Sequence[str] | None = None,
        segment_version_id: str | int | None = None,
        max_workers: int = 6,
        max_pages: int = 1_000,
        max_items: int = 100_000,
        workspace: Any | None = None,
    ) -> dict[str, Any]:
        """Return complete member rows for one exact Segment."""

        from .segment_members import segment_members, validate_segment_members_request

        selected = self._select_workspace(workspace)
        app_id = self._resolve_app(selected, app)
        validate_segment_members_request(
            app_id, ref, fields=fields, segment_version_id=segment_version_id,
            max_workers=max_workers, max_pages=max_pages, max_items=max_items,
        )
        insight = self.insight
        return segment_members(
            insight, app_id, ref, fields=fields,
            segment_version_id=segment_version_id, max_workers=max_workers,
            max_pages=max_pages, max_items=max_items,
        )


__all__ = ["SegmentMembersSdkMixin"]
