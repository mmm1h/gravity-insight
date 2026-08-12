"""Plan v1 validation and execution for strict saved Analysis replay."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .plan import AdapterContext
from .plan_adapter_support import (
    input_error,
    validate_exact_targets,
    validate_selected_fields,
)


_FIELDS = frozenset({"name", "app", "ref", "mode"})
_TARGETS = frozenset({"/app", "/ref", "/mode"})
_MODES = frozenset({"prepare", "run"})


def validate_saved_analysis(
    request: Mapping[str, Any],
    context: AdapterContext,
    workspace: Any,
    output_fields: frozenset[str],
) -> None:
    """Validate the complete static request without reading its remote artifact."""

    if set(request) - _FIELDS:
        raise input_error(
            "saved_analysis request contains unavailable fields", "request"
        )
    validate_exact_targets(context, _TARGETS)
    dynamic = set(context.dynamic_targets)
    if "/app" not in dynamic:
        try:
            workspace.resolve_app(request.get("app"))
        except (KeyError, TypeError, ValueError):
            raise input_error(
                "saved_analysis app must select a configured workspace App", "app"
            ) from None
    if "/ref" not in dynamic:
        _validate_reference(request.get("ref"))
    mode = request.get("mode", "run")
    if "/mode" not in dynamic and mode not in _MODES:
        raise input_error(
            "saved_analysis mode must be prepare or run", "mode"
        )
    validate_selected_fields(context.output_fields, output_fields, "output_fields")


def execute_saved_analysis_plan(
    sdk: Any, request: Mapping[str, Any], context: AdapterContext
) -> Any:
    """Resolve one explicit reference and either compile or execute it."""

    options = {
        "workspace": context.workspace,
        "max_pages": context.max_pages,
        "max_items": context.max_items,
    }
    if request.get("mode", "run") == "prepare":
        return sdk.prepare_saved_analysis(
            request.get("app"), request.get("ref"), **options
        )
    return sdk.run_saved_analysis(
        request.get("app"), request.get("ref"), **options
    )


def _validate_reference(value: Any) -> None:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise input_error(
            "saved_analysis ref must be an explicit id or exact name", "ref"
        )
    rendered = str(value).strip()
    if not rendered or len(rendered) > 256:
        raise input_error(
            "saved_analysis ref must be a bounded id or exact name", "ref"
        )


__all__ = ["execute_saved_analysis_plan", "validate_saved_analysis"]
