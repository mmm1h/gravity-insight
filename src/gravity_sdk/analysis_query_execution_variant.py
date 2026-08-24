"""Explicit fixed runners used only by R14-C Characterization evidence."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from .analysis_interpretation import attach_analysis_interpretation
from .errors import InputValidationError
from .execution_variant_contract import (
    DIRECT_VARIANT_URI,
    PLAN_VARIANT_URI,
)
from .field_metadata_override import use_field_metadata_loader
from .metadata_catalog_snapshot import metadata_snapshot_loader
from .plan import AdapterContext
from .plan_analysis_adapter import (
    execute_analysis_query_plan,
    safe_analysis_envelope,
    validate_analysis_query_plan,
)


def execute_fixed_analysis_query_event_variant(
    sdk: Any,
    request: Mapping[str, Any],
    context: AdapterContext,
    variant_uri: str,
) -> dict[str, Any]:
    """Run one of two statically named paths; never choose between them."""

    if request.get("kind") != "event":
        raise InputValidationError(
            "actual value: non-event Analysis Product; allowed value: analysis.query.spec:event",
            field="kind",
            code="EXECUTION_VARIANT_PRODUCT_UNKNOWN",
            next_action="Use the characterized event Analysis Product only.",
        )
    if variant_uri == DIRECT_VARIANT_URI:
        return _execute_direct_product(sdk, request, context)
    if variant_uri == PLAN_VARIANT_URI:
        return execute_analysis_query_plan(sdk, request, context)
    raise InputValidationError(
        "actual value: unknown fixed Execution Variant URI; allowed value: a URI from sdk.execution_variants.list()",
        field="variant_uri",
        code="EXECUTION_VARIANT_UNKNOWN",
        next_action="Inspect the offline Variant registry and use an exact URI.",
    )


def _execute_direct_product(
    sdk: Any, request: Mapping[str, Any], context: AdapterContext
) -> dict[str, Any]:
    expected_operation = validate_analysis_query_plan(
        sdk.insight,
        context.workspace,
        request,
        replace(context, dynamic_targets=()),
    )
    options = {
        "app": request.get("app"),
        "start": request.get("start"),
        "end": request.get("end"),
        "compare_start": request.get("compare_start"),
        "compare_end": request.get("compare_end"),
        "max_workers": 1,
        "workspace": context.workspace,
        "output_fields": context.output_fields or None,
    }
    snapshot = request.get("metadata_snapshot")
    if snapshot is None:
        result = sdk.analysis_query(
            request.get("kind"), request.get("spec"), **options
        )
    else:
        with use_field_metadata_loader(metadata_snapshot_loader(snapshot)):
            result = sdk.analysis_query(
                request.get("kind"), request.get("spec"), **options
            )
    interpreted = attach_analysis_interpretation(
        result, request.get("kind"), request.get("spec")
    )
    return safe_analysis_envelope(
        interpreted, expected_operation=expected_operation
    )


__all__ = ["execute_fixed_analysis_query_event_variant"]
