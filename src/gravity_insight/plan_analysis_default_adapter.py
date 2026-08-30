"""Plan v1 boundary for the Analysis default-value dictionary."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from .analysis_default_dictionary import SCHEMA_VERSION
from .errors import ErrorCode, ErrorDetail, exit_code_for_error
from .plan import AdapterContext
from .plan_adapter_support import (
    has_dynamic,
    request_object,
    validate_exact_targets,
    validate_selected_fields,
)
from .workspace_app import resolve_workspace_app
from .result_source import GOVERNED_PRODUCT, result_source


ANALYSIS_DEFAULT_DICTIONARY_NAME = "analysis_default_dictionary"
REQUEST_FIELDS = frozenset({"name", "app"})
OUTPUT_FIELDS = frozenset(
    {"operation_id", "app_id", "dictionary_count", "value_count", "data"}
)
_STRUCTURAL_FIELDS = frozenset(
    {"schema_version", "result_source", "ok", "status", "exit_code", "error", "result_audit"}
)
_SAFE_FIELDS = _STRUCTURAL_FIELDS | OUTPUT_FIELDS


def validate_analysis_default_dictionary_plan(
    request: Mapping[str, Any], context: AdapterContext, workspace: Any
) -> None:
    request_object(request, REQUEST_FIELDS, ANALYSIS_DEFAULT_DICTIONARY_NAME)
    validate_exact_targets(context, frozenset({"/app"}))
    if not has_dynamic(context, "/app"):
        resolve_workspace_app(workspace, request.get("app"))
    validate_selected_fields(context.output_fields, OUTPUT_FIELDS, "output_fields")


def execute_analysis_default_dictionary_plan(
    sdk: Any, request: Mapping[str, Any], context: AdapterContext
) -> dict[str, Any]:
    return safe_analysis_default_dictionary_envelope(
        sdk.analysis_default_dictionary(
            request.get("app"), workspace=context.workspace
        )
    )


def project_analysis_default_dictionary_result(
    result: Any, fields: tuple[str, ...], _context: AdapterContext
) -> dict[str, Any]:
    validate_selected_fields(fields, OUTPUT_FIELDS, "output_fields")
    selected = safe_analysis_default_dictionary_envelope(result)
    return {
        key: copy.deepcopy(value)
        for key, value in selected.items()
        if key in _STRUCTURAL_FIELDS or key in fields
    }


def safe_analysis_default_dictionary_envelope(result: Any) -> dict[str, Any]:
    if not isinstance(result, Mapping) or result.get("schema_version") != SCHEMA_VERSION:
        detail = ErrorDetail.create(
            ErrorCode.CONTRACT_CHANGED,
            "Analysis default dictionary result contract changed.",
        )
        return {
            "schema_version": SCHEMA_VERSION,
            "result_source": result_source(GOVERNED_PRODUCT),
            "ok": False,
            "status": "contract_changed",
            "exit_code": exit_code_for_error(detail),
            "error": detail.to_dict(),
        }
    return {
        key: copy.deepcopy(value) for key, value in result.items() if key in _SAFE_FIELDS
    }


def is_analysis_default_dictionary_result(result: Any) -> bool:
    return isinstance(result, Mapping) and result.get("schema_version") == SCHEMA_VERSION


__all__ = [
    "ANALYSIS_DEFAULT_DICTIONARY_NAME",
    "OUTPUT_FIELDS",
    "execute_analysis_default_dictionary_plan",
    "is_analysis_default_dictionary_result",
    "project_analysis_default_dictionary_result",
    "safe_analysis_default_dictionary_envelope",
    "validate_analysis_default_dictionary_plan",
]
