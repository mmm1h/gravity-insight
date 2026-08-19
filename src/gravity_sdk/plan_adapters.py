"""Default controlled adapters for the dependency-injected Plan v1 engine."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

from .plan import AdapterContext, PlanAdapter, PlanAdapters
from . import plan_analysis_adapter as analysis_plan
from . import plan_segment_composites as segment_plan
from . import plan_user_journey_adapter as user_journey_plan
from . import plan_dashboard_adapter as dashboard_plan
from . import plan_fixed_composite_adapter as fixed_plan
from . import plan_order_adapter as order_plan
from . import plan_report_adapter as report_plan
from .plan_saved_analysis_adapter import (
    execute_saved_analysis_plan,
    is_saved_analysis_result,
    project_saved_analysis_result,
    validate_saved_analysis,
)
from .plan_multidim_adapter import (
    MULTIDIM_NAME,
    is_multidim_result,
    project_multidim_result,
    validate_multidim_plan,
)
from . import plan_semantic_compose_adapter as semantic_plan
from .plan_material_performance_adapter import (
    MATERIAL_PERFORMANCE_NAME,
    execute_material_performance_plan,
    is_material_performance_result,
    project_material_performance_result,
    validate_material_performance_plan,
)
from .plan_title_package_adapter import (
    TITLE_PACKAGE_NAME,
    execute_title_package_plan,
    validate_title_package_plan,
)
from . import plan_promotion_performance_adapter as promotion_plan
from . import plan_bilibili_account_performance_adapter as bilibili_plan
from .plan_metadata_adapter import execute_metadata_plan, validate_metadata_plan
from .plan_receipt_adapter import execute_receipt_query, validate_receipt_query
from . import plan_mutation_adapter as mutation_plan
from .plan_adapter_support import (
    bounded_optional as _bounded_optional,
    composite_projection as _composite_projection,
    identity_projection as _identity_projection,
    input_error as _input,
    metadata_projection as _metadata_projection,
    request_object as _request_object,
    sql_projection as _sql_projection,
    validate_exact_targets as _validate_exact_targets,
    validate_selected_fields as _validate_selected_fields,
)
from .plan_run_sql_adapter import validate_run_plan, validate_sql_plan
from .actionable_error_values import actual_value


_COMPOSITE_FIELDS = frozenset(
    {
        "name", "app", "apps", "ref", "mode", "start", "end", "platforms", "include_hourly",
        "inputs", "include_total", "read_all", "metadata_inputs", "metrics",
        "input_schema_version", "max_charts",
        "package_kind",
        "device_id",
    }
)
_COMPOSITES = frozenset(
    {
        *fixed_plan.COMPOSITE_NAMES,
        *report_plan.COMPOSITE_NAMES, "saved_analysis", MULTIDIM_NAME, MATERIAL_PERFORMANCE_NAME,
        semantic_plan.SEMANTIC_COMPOSE_NAME,
        TITLE_PACKAGE_NAME,
        promotion_plan.PROMOTION_PERFORMANCE_NAME,
        bilibili_plan.BILIBILI_ACCOUNT_PERFORMANCE_NAME,
        analysis_plan.ANALYSIS_QUERY_NAME,
        *segment_plan.COMPOSITE_NAMES,
        user_journey_plan.USER_JOURNEY_NAME,
        *dashboard_plan.COMPOSITE_NAMES,
        *mutation_plan.NAMES,
    }
)
_COMPOSITE_OUTPUT_FIELDS = frozenset(
    {
        "app_count", "app_id", "components", "coverage", "date_range",
        "include_hourly", "operation_count", "platforms",
        "paginated_operation_count", "query", "results", "scopes", "source_count",
        "total", "validation", "items", "item_count", "saved_analysis", "source", "sources", "truncated", "kind",
        "profiles",
        "data", "device_id",
        "operation_id", "definition_network_called", "query_executed", "result",
    }
)


def build_plan_adapters(
    sdk: Any,
    *,
    workspace: Any | None = None,
    metadata_database: str | Path | None = None,
) -> PlanAdapters:
    """Bind the five Plan v1 kinds to one existing SDK facade and workspace."""

    workspace = sdk.workspace if workspace is None else workspace
    insight = sdk.insight
    stable_operations = frozenset(
        str(item["operation_id"])
        for item in insight.operations(stability="stable")
        if isinstance(item, Mapping) and item.get("operation_id")
    )
    database = Path(metadata_database) if metadata_database is not None else None

    def validate_run(request: Mapping[str, Any], context: AdapterContext) -> None:
        validate_run_plan(request, context, insight, workspace, stable_operations)

    def execute_run(request: Mapping[str, Any], context: AdapterContext) -> Any:
        validate_run(request, replace(context, dynamic_targets=()))
        inputs = request.get("inputs", request.get("input", {}))
        result = sdk.run(
            str(request["selector"]),
            inputs,
            parameters=request.get("parameters"),
            workspace=context.workspace,
            app=request.get("app"),
            start=request.get("start"),
            end=request.get("end"),
            all_pages=bool(request.get("all_pages", False)),
            max_pages=context.max_pages,
            max_items=context.max_items,
            max_workers=1,
            metadata_database=database,
            output_fields=context.output_fields or None,
        )
        if isinstance(result, Mapping) and result.get("ok") is not False:
            native = result.get("result")
            return dict(native) if isinstance(native, Mapping) else result
        return result

    def validate_sql(request: Mapping[str, Any], context: AdapterContext) -> None:
        validate_sql_plan(request, context, workspace)

    def execute_sql(request: Mapping[str, Any], context: AdapterContext) -> Any:
        validate_sql(request, replace(context, dynamic_targets=()))
        return sdk.query_sql_products(
            request, max_workers=1, workspace=context.workspace
        )

    def validate_metadata(request: Mapping[str, Any], context: AdapterContext) -> None:
        validate_metadata_plan(request, context)

    def execute_metadata(request: Mapping[str, Any], _context: AdapterContext) -> Any:
        return execute_metadata_plan(request, _context, database=database)

    def validate_composite(request: Mapping[str, Any], context: AdapterContext) -> None:
        _validate_composite(request, context, insight, workspace)

    def execute_composite(request: Mapping[str, Any], context: AdapterContext) -> Any:
        validate_composite(request, replace(context, dynamic_targets=()))
        return _execute_composite(sdk, request, context, database)

    def validate_receipts(request: Mapping[str, Any], context: AdapterContext) -> None:
        validate_receipt_query(request, context)

    def execute_receipts(request: Mapping[str, Any], context: AdapterContext) -> Any:
        return execute_receipt_query(request, context)

    return PlanAdapters(
        run=PlanAdapter(execute_run, validate_run, _identity_projection),
        sql_product=PlanAdapter(execute_sql, validate_sql, _sql_projection),
        metadata_search=PlanAdapter(
            execute_metadata, validate_metadata, _metadata_projection
        ),
        composite=PlanAdapter(
            execute_composite, validate_composite, _project_composite,
            preserve_partial=True,
        ),
        receipt_query=PlanAdapter(
            execute_receipts,
            validate_receipts,
            preserve_partial=True,
            preserve_capability_gap=True,
        ),
    )


def _validate_composite(
    request: Mapping[str, Any],
    context: AdapterContext,
    insight: Any,
    workspace: Any,
) -> None:
    name = request.get("name")
    if mutation_plan.accepts(name):
        mutation_plan.validate_mutation_plan(request, context)
        return
    if analysis_plan.is_analysis_composite(name):
        analysis_plan.validate_analysis_plan(
            insight, workspace, request, context
        )
        return
    if segment_plan.is_segment_composite(name):
        segment_plan.validate_segment_composite(
            insight, workspace, request, context
        )
        return
    if name == user_journey_plan.USER_JOURNEY_NAME:
        user_journey_plan.validate_user_journey_plan(request, context, workspace)
        return
    if dashboard_plan.is_dashboard_composite(name):
        dashboard_plan.validate_dashboard_plan(request, context, workspace)
        return
    if order_plan.is_order_composite(name):
        order_plan.validate_order_plan(request, context, workspace)
        return
    _request_object(request, _COMPOSITE_FIELDS, "composite")
    if name not in _COMPOSITES:
        raise _input(
            f"actual value: {actual_value(name)}; "
            "composite name must be one of the allowlisted Plan composites",
            "name",
        )
    if report_plan.is_report_composite(name):
        report_plan.validate_report_composite(
            request, context, workspace, _COMPOSITE_OUTPUT_FIELDS
        )
        return
    if name == "saved_analysis":
        validate_saved_analysis(
            request, context, workspace, _COMPOSITE_OUTPUT_FIELDS
        )
        return
    if name == MULTIDIM_NAME:
        validate_multidim_plan(insight, workspace, request, context)
        return
    if name == semantic_plan.SEMANTIC_COMPOSE_NAME:
        semantic_plan.validate_semantic_compose_plan(workspace, request, context)
        return
    if name == MATERIAL_PERFORMANCE_NAME:
        validate_material_performance_plan(request, context, workspace)
        return
    if name == TITLE_PACKAGE_NAME:
        validate_title_package_plan(request, context, workspace)
        return
    if name in {
        promotion_plan.PROMOTION_PERFORMANCE_NAME,
        bilibili_plan.BILIBILI_ACCOUNT_PERFORMANCE_NAME,
    }:
        {
            promotion_plan.PROMOTION_PERFORMANCE_NAME: promotion_plan.validate_promotion_performance_plan,
            bilibili_plan.BILIBILI_ACCOUNT_PERFORMANCE_NAME: bilibili_plan.validate_bilibili_account_performance_plan,
        }[name](request, context, workspace)
        return
    _validate_exact_targets(context, frozenset({"/app"}))
    _validate_selected_fields(context.output_fields, _COMPOSITE_OUTPUT_FIELDS, "output_fields")
    fixed_plan.validate_fixed_composite(request, context, str(name))


def _execute_composite(
    sdk: Any, request: Mapping[str, Any], context: AdapterContext, database: Path | None
) -> Any:
    name = str(request["name"])
    if mutation_plan.accepts(name):
        return mutation_plan.execute_mutation_plan(sdk, request, context)
    if fixed_plan.is_fixed_composite(name):
        return fixed_plan.execute_fixed_composite(sdk, request, context, database=database)
    if report_plan.is_report_composite(name):
        return report_plan.execute_report_composite(sdk, request, context)
    if name == "saved_analysis":
        return execute_saved_analysis_plan(sdk, request, context)
    if name in {MULTIDIM_NAME, semantic_plan.SEMANTIC_COMPOSE_NAME}:
        return semantic_plan.execute_multidim_or_semantic(sdk, request, context)
    if name == MATERIAL_PERFORMANCE_NAME:
        return execute_material_performance_plan(sdk, request, context)
    if name == TITLE_PACKAGE_NAME:
        return execute_title_package_plan(sdk, request, context)
    if name == promotion_plan.PROMOTION_PERFORMANCE_NAME:
        return promotion_plan.execute_promotion_performance_plan(sdk, request, context)
    if name == bilibili_plan.BILIBILI_ACCOUNT_PERFORMANCE_NAME:
        return bilibili_plan.execute_bilibili_account_performance_plan(sdk, request, context)
    if analysis_plan.is_analysis_composite(name):
        return analysis_plan.execute_analysis_plan(sdk, request, context)
    if segment_plan.is_segment_composite(name):
        return segment_plan.execute_segment_composite(sdk, request, context)
    if name == user_journey_plan.USER_JOURNEY_NAME:
        return user_journey_plan.execute_user_journey_plan(sdk, request, context)
    if dashboard_plan.is_dashboard_composite(name):
        return dashboard_plan.execute_dashboard_plan(sdk, request, context)
    if order_plan.is_order_composite(name):
        return order_plan.execute_order_plan(sdk, request, context)
    raise RuntimeError("validated composite routing omitted an executor")


def _project_composite(
    result: Any, fields: tuple[str, ...], context: AdapterContext
) -> Any:
    if mutation_plan.is_mutation_result(result):
        return mutation_plan.project_mutation_result(result, fields, context)
    if analysis_plan.is_analysis_result(result):
        return analysis_plan.project_analysis_result(result, fields, context)
    if segment_plan.is_segment_result(result):
        return segment_plan.project_segment_result(result, fields, context)
    if user_journey_plan.is_user_journey_result(result):
        return user_journey_plan.project_user_journey_result(result, fields, context)
    if dashboard_plan.is_dashboard_result(result):
        return dashboard_plan.project_dashboard_result(result, fields, context)
    if order_plan.is_order_result(result):
        return order_plan.project_order_result(result, fields, context)
    if is_saved_analysis_result(result):
        return project_saved_analysis_result(result, fields, context)
    if is_multidim_result(result):
        return project_multidim_result(result, fields, context)
    if semantic_plan.is_semantic_compose_result(result):
        return semantic_plan.project_semantic_compose_result(result, fields, context)
    if is_material_performance_result(result):
        return project_material_performance_result(result, fields, context)
    if promotion_plan.is_promotion_performance_result(result):
        return promotion_plan.project_promotion_performance_result(result, fields, context)
    if bilibili_plan.is_bilibili_account_performance_result(result):
        return bilibili_plan.project_bilibili_account_performance_result(result, fields, context)
    return _composite_projection(result, fields, context)


__all__ = ["build_plan_adapters"]
