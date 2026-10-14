"""Field-policy binding for dynamic material report columns."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from .actionable_error_values import actual_value
from .errors import InputValidationError
from .material_metrics import (
    DEFAULT_GRAVITY_METRICS,
    DEFAULT_MEDIA_METRICS,
    validate_report_metrics,
)


_FIELDS = frozenset(
    {
        "metrics_list",
        "gravity_metrics_list",
        "data_dims",
        "relate_dims",
        "stat_list",
    }
)


def validate_material_dynamic_fields(
    requested: Mapping[str, Sequence[str]], inputs: Mapping[str, Any]
) -> None:
    unknown = set(requested) - _FIELDS
    if unknown:
        raise InputValidationError(
            f"actual value: {actual_value(sorted(unknown))}; material dynamic fields "
            "must use the registered request columns",
            field="dynamic_response_fields",
        )
    platform = str(inputs.get("platform", ""))
    metrics = inputs.get("metrics_list", DEFAULT_MEDIA_METRICS.get(platform, ()))
    gravity = inputs.get("gravity_metrics_list", DEFAULT_GRAVITY_METRICS)
    validate_report_metrics(platform, metrics, gravity)


__all__ = ["validate_material_dynamic_fields"]
