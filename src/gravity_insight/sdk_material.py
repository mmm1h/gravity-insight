"""Material-product methods for the unified lazy SDK facade."""

from __future__ import annotations

from collections.abc import Sequence
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .errors import InputValidationError
from .actionable_error_values import actual_value


class MaterialSdkMixin:
    """Expose governed material analysis without duplicating its core."""

    def material_game_performance(
        self, app: str | int, material_ids: Sequence[str | int], platform: str, *,
        start: str | None = None, end: str | None = None, as_of: str | None = None,
        lookback_days: int = 30, metrics: Mapping[str, Any] | None = None,
        object_type: str = "material", max_report_pages: int = 100,
        max_user_pages: int = 1_000, max_user_items: int = 100_000,
        max_days: int = 90, max_workers: int = 6, workspace: Any | None = None,
    ) -> dict[str, Any]:
        """Compose bounded material discovery and registration-day aggregates."""
        from .material_game_contract import normalize_request
        from .material_game_performance import material_game_performance

        selected = self._select_workspace(workspace)
        app_id = self._resolve_app(selected, app)
        options = {
            "start": start, "end": end, "as_of": as_of, "lookback_days": lookback_days,
            "metrics": metrics, "object_type": object_type, "max_report_pages": max_report_pages,
            "max_user_pages": max_user_pages, "max_user_items": max_user_items,
            "max_days": max_days, "max_workers": max_workers,
        }
        normalize_request(app_id, material_ids, platform, **options)
        return material_game_performance(self.insight, app_id, material_ids, platform, **options)

    def material_performance(
        self,
        apps: str | int | Sequence[str | int],
        start: str,
        end: str,
        *,
        platforms: Sequence[str] = (
            "bytedance", "tencent", "kuaishou", "bilibili"
        ),
        metrics: Mapping[str, Sequence[str]] | None = None,
        gravity_metrics: Sequence[str] = (
            "AppRealRegisterCnt", "AppGamePayUserCntStandardAtv"
        ),
        date_grain: str = "total",
        data_dimension: str = "material",
        relate_dimensions: Sequence[str] = (),
        statistics: Sequence[str] = (),
        order_by: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
        decimal_point: int | None = None,
        time_lines: Mapping[str, str] | None = None,
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
        elif isinstance(apps, Sequence) and not isinstance(
            apps, (bytes, bytearray, memoryview)
        ):
            values = list(apps)
        else:
            raise InputValidationError(
                f"actual value: {actual_value(apps)}; " + ("material performance apps must be a non-empty array"),
                field="apps",
            )
        app_ids = [self._resolve_app(selected, value) for value in values]
        validate_material_performance_request(
            app_ids,
            start,
            end,
            platforms=platforms,
            metrics=metrics,
            gravity_metrics=gravity_metrics,
            date_grain=date_grain,
            data_dimension=data_dimension,
            relate_dimensions=relate_dimensions,
            statistics=statistics,
            order_by=order_by,
            decimal_point=decimal_point,
            time_lines=time_lines,
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
            metrics=metrics,
            gravity_metrics=gravity_metrics,
            date_grain=date_grain,
            data_dimension=data_dimension,
            relate_dimensions=relate_dimensions,
            statistics=statistics,
            order_by=order_by,
            decimal_point=decimal_point,
            time_lines=time_lines,
            max_workers=max_workers,
            max_pages=max_pages,
            max_items=max_items,
        )

    def title_packages(
        self,
        app: str | int,
        package_kind: str,
        *,
        max_pages: int = 1_000,
        max_items: int = 100_000,
        workspace: Any | None = None,
    ) -> dict[str, Any]:
        """Read regular or standard Bytedance title-package summaries."""

        from .title_package import title_packages

        selected = self._select_workspace(workspace)
        app_id = self._resolve_app(selected, app)
        return title_packages(
            self.insight,
            app_id,
            package_kind,
            max_pages=max_pages,
            max_items=max_items,
        )

    def fetch_material_asset(
        self,
        source: str,
        source_input: Mapping[str, Any],
        ref_field: str,
        ref: str | int,
        role: str,
        destination: str | Path,
        *,
        output_root: str | Path | None = None,
    ) -> dict[str, Any]:
        """Fetch one allowlisted asset while keeping its fresh source URL private."""

        from .material_asset import fetch_material_asset

        return fetch_material_asset(
            self.insight,
            source,
            source_input,
            ref_field,
            ref,
            role,
            destination,
            output_root=output_root,
        )


__all__ = ["MaterialSdkMixin"]
