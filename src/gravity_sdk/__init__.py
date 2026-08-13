"""Governed Insight and SQL SDK for Gravity private APIs.

Public exports are loaded lazily so the CLI can select a business workspace
before any workspace-dependent module is imported.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any


__version__ = "0.2.0"

_EXPORTS = {
    "DEFAULT_METADATA_TTL_SECONDS": (".cache", "DEFAULT_METADATA_TTL_SECONDS"),
    "MetadataCache": (".cache", "MetadataCache"),
    "is_metadata_operation": (".cache", "is_metadata_operation"),
    "OperationCatalog": (".catalog", "OperationCatalog"),
    "OperationProbe": (".catalog", "OperationProbe"),
    "GravityInsightClient": (".client", "GravityInsightClient"),
    "GravitySDK": (".sdk", "GravitySDK"),
    "connect": (".sdk", "connect"),
    "CompositeService": (".composite", "CompositeService"),
    "Credential": (".credentials", "Credential"),
    "CredentialConfig": (".credentials", "CredentialConfig"),
    "CredentialProvider": (".credentials", "CredentialProvider"),
    "ExportContractRegistry": (".export_contracts", "ExportContractRegistry"),
    "ExportRouteContract": (".export_contracts", "ExportRouteContract"),
    "ExportCreationRequest": (".export_runtime", "ExportCreationRequest"),
    "ExportJobSnapshot": (".export_runtime", "ExportJobSnapshot"),
    "ExportOrchestrator": (".export_runtime", "ExportOrchestrator"),
    "ExportPollingPolicy": (".export_runtime", "ExportPollingPolicy"),
    "ExportPrivacyContract": (".export_runtime", "ExportPrivacyContract"),
    "ExportResult": (".export_runtime", "ExportResult"),
    "ExportRuntimeError": (".export_runtime", "ExportRuntimeError"),
    "ExportState": (".export_runtime", "ExportState"),
    "GravityClient": (".sql", "GravityClient"),
    "SqlBatchRequest": (".sql", "SqlBatchRequest"),
    "SqlBatchResult": (".sql", "SqlBatchResult"),
    "build_sql_client": (".sql", "build_sql_client"),
    "PlanAdapter": (".plan", "PlanAdapter"),
    "PlanAdapters": (".plan", "PlanAdapters"),
    "PlanValidationError": (".plan", "PlanValidationError"),
    "execute_plan": (".plan", "execute_plan"),
    "plan_schema": (".plan", "plan_schema"),
    "validate_plan": (".plan", "validate_plan"),
    "capabilities_many": (".agent_batch", "capabilities_many"),
    "CompiledAnalysisQuery": (".analysis_spec", "CompiledAnalysisQuery"),
    "analysis_query_spec_schema": (".analysis_spec", "analysis_query_spec_schema"),
    "compile_query_spec": (".analysis_spec", "compile_query_spec"),
    "analysis_query_batch_schema": (
        ".analysis_query_batch", "analysis_query_batch_schema"
    ),
    "execute_analysis_query_batch": (
        ".analysis_query_batch", "execute_analysis_query_batch"
    ),
    "run_analysis_query_batch": (
        ".analysis_query_batch", "run_analysis_query_batch"
    ),
    "validate_analysis_query_batch": (
        ".analysis_query_batch", "validate_analysis_query_batch"
    ),
    "CompiledSegmentSpec": (".segment_spec", "CompiledSegmentSpec"),
    "compile_segment_spec": (".segment_spec", "compile_segment_spec"),
    "prepare_segment_spec": (".segment_spec", "prepare_segment_spec"),
    "segment_rule_spec_schema": (".segment_spec", "segment_rule_spec_schema"),
    "validate_segment_spec": (".segment_spec", "validate_segment_spec"),
    "business_pulse": (".business_pulse", "business_pulse"),
    "dashboard_snapshot": (".dashboard_snapshot", "dashboard_snapshot"),
    "promotion_performance": (
        ".promotion_performance", "promotion_performance"
    ),
    "promotion_performance_input_schema": (
        ".promotion_performance", "promotion_performance_input_schema"
    ),
    "order_split_trace": (".order_trace", "order_split_trace"),
    "validate_order_split_trace_request": (
        ".order_trace", "validate_order_split_trace_request"
    ),
    "order_directory": (".order_directory", "order_directory"),
    "validate_order_directory_request": (
        ".order_directory", "validate_order_directory_request"
    ),
    "compile_saved_analysis_definition": (
        ".saved_analysis", "compile_saved_analysis_definition"
    ),
    "execute_saved_analysis": (".saved_analysis", "execute_saved_analysis"),
    "inspect_saved_analysis": (".saved_analysis", "inspect_saved_analysis"),
    "list_saved_analyses": (".saved_analysis", "list_saved_analyses"),
    "prepare_saved_analysis": (".saved_analysis", "prepare_saved_analysis"),
    "resolve_saved_analysis": (".saved_analysis", "resolve_saved_analysis"),
}

for _error_name in (
    "AuthenticationError",
    "CredentialError",
    "GravityInsightError",
    "GravityExportError",
    "InputValidationError",
    "ManifestError",
    "PaginationError",
    "ParentRequiredError",
    "PermissionUnavailableError",
    "PolicyViolation",
    "SqlResponseError",
    "SqlValidationError",
    "TransportError",
    "UnknownOperationError",
    "UpstreamError",
):
    _EXPORTS[_error_name] = (".errors", _error_name)


def __getattr__(name: str) -> Any:
    try:
        module_name, attribute = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc
    value = getattr(import_module(module_name, __name__), attribute)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted({*globals(), *_EXPORTS})


__all__ = [*_EXPORTS, "__version__"]
