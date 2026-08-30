"""Local derived-metrics route within the Analysis composite family."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .actionable_error_values import actual_value
from .derived_metrics import SCHEMA_VERSION, validate_derived_request
from .errors import InputValidationError
from .plan import AdapterContext
from .plan_adapter_support import validate_exact_targets


DERIVED_METRICS_NAME = "derived_metrics"


def validate_derived_metrics_plan(
    request: Mapping[str, Any], context: AdapterContext
) -> None:
    validate_exact_targets(context, frozenset())
    if context.output_fields:
        raise InputValidationError(
            "derived metrics does not support output_fields; actual value: "
            + actual_value(context.output_fields),
            field="output_fields",
            next_action="Remove output_fields and consume the versioned derived_metrics sub-contract, then retry.",
        )
    validate_derived_request(request)


def execute_derived_metrics_plan(
    sdk: Any, request: Mapping[str, Any], context: AdapterContext
) -> dict[str, Any]:
    del context
    return sdk.derive_metrics(request["source"], request["spec"])


def is_derived_metrics_result(value: Any) -> bool:
    nested = value.get("derived_metrics") if isinstance(value, Mapping) else None
    return isinstance(nested, Mapping) and nested.get("schema_version") == SCHEMA_VERSION


def project_derived_metrics_result(
    value: Any, _fields: tuple[str, ...], _context: AdapterContext
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError("derived metrics result must be an object")
    return dict(value)


__all__ = [
    "DERIVED_METRICS_NAME",
    "execute_derived_metrics_plan",
    "is_derived_metrics_result",
    "project_derived_metrics_result",
    "validate_derived_metrics_plan",
]
