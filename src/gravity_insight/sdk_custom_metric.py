"""Custom-metric convenience methods for the unified SDK facade."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class CustomMetricSdkMixin:
    @staticmethod
    def custom_metric_mutation_schema() -> dict[str, Any]:
        from .custom_metric_mutation import custom_metric_mutation_schema

        return custom_metric_mutation_schema()

    def custom_metrics(
        self, *, max_pages: int = 1_000, max_items: int = 100_000
    ) -> dict[str, Any]:
        from .custom_metric_mutation import list_custom_metrics

        return list_custom_metrics(
            self.insight, max_pages=max_pages, max_items=max_items
        )

    def custom_metric_mutation(
        self, action: str, inputs: Mapping[str, Any], *, execute: bool = False
    ) -> dict[str, Any]:
        from .custom_metric_mutation import run_custom_metric_mutation

        return run_custom_metric_mutation(
            self.insight, action, inputs, execute=execute
        )

    def create_custom_metric(self, **options: Any) -> dict[str, Any]:
        from .custom_metric_mutation import create_custom_metric

        return create_custom_metric(self.insight, **options)

    def update_custom_metric(self, **options: Any) -> dict[str, Any]:
        from .custom_metric_mutation import update_custom_metric

        return update_custom_metric(self.insight, **options)

    def delete_custom_metric(
        self, metric_id: str, *, execute: bool = False
    ) -> dict[str, Any]:
        from .custom_metric_mutation import delete_custom_metric

        return delete_custom_metric(self.insight, metric_id=metric_id, execute=execute)


__all__ = ["CustomMetricSdkMixin"]
