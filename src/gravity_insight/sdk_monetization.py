"""Monetization-product methods for the unified lazy SDK facade."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


class MonetizationSdkMixin:
    """Expose complete registered monetization rows through the unified SDK."""

    def monetization_detail(
        self,
        app: str | int,
        date: str,
        *,
        fields: Sequence[str] | None = None,
        global_conditions: Sequence[Mapping[str, Any]] = (),
        cond_logic: str = "AND",
        local_conditions: Sequence[Mapping[str, Any]] = (),
        local_cond_logic: str = "AND",
        order_by: Sequence[Mapping[str, Any]] = (),
        segment_id: str | int | None = None,
        tmp_segment_id: str | int | None = None,
        max_workers: int = 6,
        max_pages: int = 1_000,
        max_items: int = 100_000,
        workspace: Any | None = None,
    ) -> dict[str, Any]:
        """Read one complete registered daily monetization detail."""

        from .monetization_detail import (
            SAFE_ROW_FIELDS,
            monetization_detail,
            validate_monetization_detail_request,
        )
        from .monetization_query import normalize_monetization_query

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
        query_options = {
            "fields": tuple(fields) if fields is not None else SAFE_ROW_FIELDS,
            "global_conditions": global_conditions,
            "cond_logic": cond_logic,
            "local_conditions": local_conditions,
            "local_cond_logic": local_cond_logic,
            "order_by": order_by,
            "segment_id": segment_id,
            "tmp_segment_id": tmp_segment_id,
        }
        normalize_monetization_query(**query_options)
        validate_monetization_detail_request(1, date, **options)
        selected = self._select_workspace(workspace)
        app_id = self._resolve_app(selected, app)
        canonical = validate_monetization_detail_request(app_id, date, **options)
        return monetization_detail(
            self.insight, canonical[0], canonical[1], **query_options, **options
        )


__all__ = ["MonetizationSdkMixin"]
