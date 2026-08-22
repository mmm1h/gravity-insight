"""Governed Insight and SQL SDK for Gravity private APIs.

Public exports are loaded lazily so the CLI can select a business workspace
before any workspace-dependent module is imported.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any


__version__ = "0.3.0"

_EXPORTS = {
    "DEFAULT_METADATA_TTL_SECONDS": (".cache", "DEFAULT_METADATA_TTL_SECONDS"),
    "MetadataCache": (".cache", "MetadataCache"),
    "bypass_metadata_cache": (".cache", "bypass_metadata_cache"),
    "clear_metadata_cache": (".cache", "clear_metadata_cache"),
    "is_metadata_operation": (".cache", "is_metadata_operation"),
    "metadata_cache_stats": (".cache", "metadata_cache_stats"),
    "OperationCatalog": (".catalog", "OperationCatalog"),
    "OperationProbe": (".catalog", "OperationProbe"),
    "GravityInsightClient": (".client", "GravityInsightClient"),
    "GravitySDK": (".sdk", "GravitySDK"),
    "connect": (".sdk", "connect"),
    "JourneyService": (".journey_service", "JourneyService"),
    "CoreSkillRuntime": (".core_skill_runtime", "CoreSkillRuntime"),
    "RuntimeSkillResolver": (".runtime_skill_resolver", "RuntimeSkillResolver"),
    "compile_analysis_result": (
        ".analysis_result_contract", "compile_analysis_result"
    ),
    "compile_execution_snapshot": (
        ".execution_snapshot", "compile_execution_snapshot"
    ),
    "compile_project_skill_overlay": (
        ".project_skill_overlay", "compile_project_skill_overlay"
    ),
    "CapabilityTrustService": (
        ".capability_trust", "CapabilityTrustService"
    ),
    "LocalSkillResolver": (".skill_package", "LocalSkillResolver"),
    "CallableProviderTransport": (
        ".provider_rpc_transport", "CallableProviderTransport"
    ),
    "ExternalContextProvider": (
        ".external_context_provider", "ExternalContextProvider"
    ),
    "ProviderRpcGuard": (".provider_rpc_guard", "ProviderRpcGuard"),
    "subprocess_context_provider": (
        ".external_context_provider", "subprocess_context_provider"
    ),
    "SkillHubClient": (".skill_hub_client", "SkillHubClient"),
    "TrustedPackHubClient": (".trusted_pack_hub", "TrustedPackHubClient"),
    "SemanticRegistry": (".semantic_registry", "SemanticRegistry"),
    "OperatorRegistry": (".operator_registry", "OperatorRegistry"),
    "ModelRegistry": (".model_registry", "ModelRegistry"),
    "RepoContextProvider": (".repo_context_provider", "RepoContextProvider"),
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
    "GravityInsightError": (".error_models", "GravityInsightError"),
    "SqlBatchRequest": (".sql", "SqlBatchRequest"),
    "SqlBatchResult": (".sql", "SqlBatchResult"),
    "build_sql_client": (".sql", "build_sql_client"),
    "PlanAdapter": (".plan", "PlanAdapter"),
    "PlanAdapters": (".plan", "PlanAdapters"),
    "PlanValidationError": (".plan", "PlanValidationError"),
    "execute_plan": (".plan", "execute_plan"),
    "plan_schema": (".plan", "plan_schema"),
    "validate_plan": (".plan", "validate_plan"),
    "assess_host_action": (".host_effects", "assess_host_action"),
    "assess_host_plan": (".host_effects", "assess_host_plan"),
    "compile_host_plan": (".host_effects", "compile_host_plan"),
    "execute_host_plan": (".host_plan_execution", "execute_host_plan"),
    "host_source": (".host_effects", "host_source"),
    "host_effect_schema": (".host_effects", "host_effect_schema"),
    "normalized_host_plan_request": (
        ".host_effects", "normalized_host_plan_request"
    ),
    "host_product_catalog": (".agent_host_catalog", "host_product_catalog"),
    "host_product_selection_schema": (
        ".agent_host_catalog", "host_product_selection_schema"
    ),
    "assess_host_product_selection": (
        ".agent_host_selection", "assess_host_product_selection"
    ),
    "compile_host_product_selection": (
        ".agent_host_selection", "compile_host_product_selection"
    ),
    "resolve_host_product_selection": (
        ".agent_host_selection", "resolve_host_product_selection"
    ),
    "PlanRecipe": (".workspace_plan_recipe", "PlanRecipe"),
    "PlanRecipeError": (".workspace_plan_recipe", "PlanRecipeError"),
    "expand_plan_recipe": (".workspace_plan_recipe", "expand_plan_recipe"),
    "capabilities_many": (".agent_batch", "capabilities_many"),
    "CompiledAnalysisQuery": (".analysis_spec", "CompiledAnalysisQuery"),
    "analysis_query_spec_schema": (".analysis_spec", "analysis_query_spec_schema"),
    "compile_query_spec": (".analysis_spec", "compile_query_spec"),
    "AnalysisCohort": (".analysis_primitives", "AnalysisCohort"),
    "AnalysisFilter": (".analysis_primitives", "AnalysisFilter"),
    "AnalysisMetric": (".analysis_primitives", "AnalysisMetric"),
    "AnalysisSpec": (".analysis_primitives", "AnalysisSpec"),
    "AnalysisStep": (".analysis_primitives", "AnalysisStep"),
    "analysis_query_batch_schema": (
        ".analysis_query_batch", "analysis_query_batch_schema"
    ),
    "analysis_query_multi_app_schema": (
        ".analysis_query_multi_app", "analysis_query_multi_app_schema"
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
    "company_usage": (".company_usage", "company_usage"),
    "title_packages": (".title_package", "title_packages"),
    "fetch_material_asset": (".material_asset", "fetch_material_asset"),
    "custom_audiences": (".custom_audience", "custom_audiences"),
    "dashboard_snapshot": (".dashboard_snapshot", "dashboard_snapshot"),
    "promotion_performance": (
        ".promotion_performance", "promotion_performance"
    ),
    "promotion_performance_input_schema": (
        ".promotion_performance", "promotion_performance_input_schema"
    ),
    "bilibili_account_performance": (
        ".bilibili_account_performance", "bilibili_account_performance"
    ),
    "validate_bilibili_account_request": (
        ".bilibili_account_performance", "validate_bilibili_account_request"
    ),
    "order_split_trace": (".order_trace", "order_split_trace"),
    "validate_order_split_trace_request": (
        ".order_trace", "validate_order_split_trace_request"
    ),
    "order_directory": (".order_directory", "order_directory"),
    "validate_order_directory_request": (
        ".order_directory", "validate_order_directory_request"
    ),
    "monetization_detail": (".monetization_detail", "monetization_detail"),
    "validate_monetization_detail_request": (
        ".monetization_detail", "validate_monetization_detail_request"
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

for _sdk_error_name in (
    "AuthenticationError",
    "CredentialError",
    "InputValidationError",
    "ManifestError",
    "PaginationError",
    "ParentRequiredError",
    "PermissionUnavailableError",
    "PolicyViolation",
    "SemanticRejectedError",
    "TransportError",
    "UnknownOperationError",
    "UpstreamContradictedRequestError",
    "UpstreamError",
):
    _EXPORTS[_sdk_error_name] = (".error_types", _sdk_error_name)

for _sql_error_name in (
    "GravityExportError",
    "SqlResponseError",
    "SqlValidationError",
):
    _EXPORTS[_sql_error_name] = (".error_sql", _sql_error_name)


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
