"""Plan v1 boundary for the title-package family product."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .agent_title_package import TITLE_PACKAGE_NAME
from .plan import AdapterContext
from .plan_adapter_support import input_error, validate_exact_targets
from .title_package import normalize_package_kind
from .actionable_error_values import actual_value


TITLE_PACKAGE_FIELDS = frozenset({"name", "app", "package_kind"})
TITLE_PACKAGE_OUTPUT_FIELDS = frozenset({
    "app_id", "failure_count", "operation_id", "package_kind", "results",
    "returned_items", "source_count", "success_count", "total_count",
})


def validate_title_package_plan(
    request: Mapping[str, Any], context: AdapterContext, workspace: Any
) -> None:
    if set(request) - TITLE_PACKAGE_FIELDS:
        raise input_error(f"actual value: {actual_value(sorted(set(request) - TITLE_PACKAGE_FIELDS))}; title_package request contains unavailable fields; must use only available fields; remove extras", "request")
    if request.get("name") != TITLE_PACKAGE_NAME:
        raise input_error(f"actual value: {actual_value(request.get('name'))}; title_package name is invalid; must match the documented composite name", "name")
    validate_exact_targets(context, frozenset({"/app", "/package_kind"}))
    dynamic = set(context.dynamic_targets)
    if "/app" not in dynamic:
        try:
            workspace.resolve_app(request.get("app"))
        except (KeyError, TypeError, ValueError):
            raise input_error(
                f"actual value: {actual_value(request.get('app'))}; " + ("title_package app must select a configured workspace App"), "app"
            ) from None
    if "/package_kind" not in dynamic:
        try:
            normalize_package_kind(request.get("package_kind"))
        except (TypeError, ValueError):
            raise input_error(
                f"actual value: {actual_value(request.get('package_kind'))}; " + ("title_package package_kind must be regular or standard"),
                "package_kind",
            ) from None
    if context.max_items < 1:
        raise input_error(f"actual value: {actual_value(context.max_items)}; " + ("title_package requires one source item"), "limits.max_items")
    unknown = set(context.output_fields) - TITLE_PACKAGE_OUTPUT_FIELDS
    if unknown:
        raise input_error(
            f"actual value: {actual_value(sorted(unknown))}; title_package output_fields contain unavailable fields; must stay inside the adapter contract; remove extras", "output_fields"
        )


def execute_title_package_plan(
    sdk: Any, request: Mapping[str, Any], context: AdapterContext
) -> dict[str, Any]:
    return sdk.title_packages(
        request["app"],
        request["package_kind"],
        max_pages=context.max_pages,
        max_items=context.max_items,
        workspace=context.workspace,
    )


__all__ = [
    "TITLE_PACKAGE_NAME",
    "execute_title_package_plan",
    "validate_title_package_plan",
]
