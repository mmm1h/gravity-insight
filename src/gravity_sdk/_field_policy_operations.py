"""Operation-to-validation bindings for the Gravity Insight field policy."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


def _operation(*parts: str) -> str:
    return ".".join(parts)


ANALYSIS_EVENT_QUERY = _operation("analysis", "event", "query")
ANALYSIS_FUNNEL_QUERY = _operation("analysis", "funnel", "query")
ANALYSIS_RETENTION_QUERY = _operation("analysis", "retention", "query")
ANALYSIS_SCATTER_QUERY = _operation("analysis", "scatter", "query")
ANALYSIS_PROPERTY_QUERY = _operation("analysis", "property", "query")
ANALYSIS_ORDER_DETAIL = _operation("analysis", "order_detail", "list")
ANALYSIS_MONETIZATION_DETAIL = _operation("analysis", "monetization_detail", "list")
ANALYSIS_USER_DETAIL = _operation("analysis", "user_detail", "list")
ANALYSIS_USER_EVENT = _operation("analysis", "user_event", "list")
ANALYSIS_SEGMENT_USER_DETAIL = _operation("analysis", "segment", "user_detail", "list")
ANALYSIS_ACCOUNT_USER = _operation("analysis", "account_user", "list")
ANALYSIS_DASHBOARD_FAVOURITE = _operation(
    "analysis", "dashboard", "condition_favourite", "list"
)
ANALYSIS_REPORT_CONFIG = _operation("analysis", "report_config", "list")
ANALYSIS_TEMPLATE_OWN = _operation("analysis", "template", "own", "list")
ANALYSIS_TEMPLATE_SHARE = _operation("analysis", "template", "share", "list")
ANALYSIS_TEMPLATE_INTERNAL = _operation("analysis", "template", "internal", "list")
ANALYSIS_SEGMENT_EVALUATE = _operation("analysis", "segment", "evaluate_percent")
ANALYSIS_USER_PROPERTY_VALUE = _operation("analysis", "user_property_value", "list")
ANALYSIS_EVENT_PROPERTY_VALUE = _operation("analysis", "event_property_value", "list")
ANALYSIS_USER_PROPERTY = _operation("analysis", "user_property", "list")
ANALYSIS_EVENT = _operation("analysis", "event", "list")
ANALYSIS_EVENT_PROPERTY = _operation("analysis", "event_property", "list")
ANALYSIS_SEGMENT = _operation("analysis", "segment", "list")
ANALYSIS_SEGMENT_HISTORY = _operation("analysis", "segment", "history_version", "list")
ANALYSIS_EVENT_INFO = _operation("analysis", "event", "info")
ANALYSIS_TASK_OTHER_EVENT = _operation("analysis", "task", "other_event", "list")
PROMOTION_METRIC = _operation("promotion", "metric", "list")
REPORT_BUSINESS_QUERY = _operation("report", "business", "query")
REPORT_BUSINESS_METRIC = _operation("report", "business", "metric", "list")
REPORT_MULTIDIM_QUERY = _operation("report", "multidim", "query")
REPORT_MULTIDIM_TOTAL = _operation("report", "multidim", "calc_total")
REPORT_MULTIDIM_METRIC = _operation("report", "multidim", "metric", "list")
REPORT_MULTIDIM_CUSTOM_METRIC = _operation("report", "multidim", "custom_metric", "list")
REPORT_MULTIDIM_SHARED_METRIC = _operation(
    "report", "multidim", "custom_metric", "shared", "list"
)


@dataclass(frozen=True)
class OperationRule:
    request_kind: str = "standard"
    query_kind: str | None = None
    exact_filter_profile: Mapping[str, frozenset[str | int]] | None = None
    exact_filter_values: str | None = None


_ACCOUNT_FILTERS = {
    "dept_id": frozenset({6}),
    "role_id": frozenset({6}),
}
_DASHBOARD_FILTERS = {
    "dashboard_id": frozenset({1}),
    "default_to_one": frozenset({1}),
    "default_to_all": frozenset({1}),
    "name": frozenset({8}),
}
_REPORT_CONFIG_FILTERS = {
    "subject": frozenset({1}),
    "name": frozenset({8}),
}
_TEMPLATE_FILTERS = {
    "template_type": frozenset({1}),
    "name": frozenset({8}),
}
_OTHER_EVENT_FILTERS = {
    "create_time": frozenset({"RANGE_IN"}),
    "create_user_id": frozenset({"IN"}),
    "task_status": frozenset({"EQUALS"}),
    "client_id": frozenset({"IN"}),
}


OPERATION_RULES: Mapping[str, OperationRule] = {
    ANALYSIS_EVENT_QUERY: OperationRule("analysis_query", "event"),
    ANALYSIS_FUNNEL_QUERY: OperationRule("analysis_query", "funnel"),
    ANALYSIS_RETENTION_QUERY: OperationRule("analysis_query", "retention"),
    ANALYSIS_SCATTER_QUERY: OperationRule("analysis_query", "scatter"),
    ANALYSIS_PROPERTY_QUERY: OperationRule("analysis_query", "property"),
    ANALYSIS_ORDER_DETAIL: OperationRule("analysis_detail"),
    ANALYSIS_MONETIZATION_DETAIL: OperationRule("analysis_detail"),
    ANALYSIS_USER_DETAIL: OperationRule("analysis_detail"),
    ANALYSIS_USER_EVENT: OperationRule("analysis_detail"),
    ANALYSIS_SEGMENT_USER_DETAIL: OperationRule("analysis_detail"),
    ANALYSIS_SEGMENT_EVALUATE: OperationRule("analysis_segment"),
    ANALYSIS_USER_PROPERTY_VALUE: OperationRule("property_values", "user"),
    ANALYSIS_EVENT_PROPERTY_VALUE: OperationRule("property_values", "event"),
    ANALYSIS_ACCOUNT_USER: OperationRule(
        exact_filter_profile=_ACCOUNT_FILTERS,
        exact_filter_values="account",
    ),
    ANALYSIS_DASHBOARD_FAVOURITE: OperationRule(
        exact_filter_profile=_DASHBOARD_FILTERS,
        exact_filter_values="dashboard",
    ),
    ANALYSIS_REPORT_CONFIG: OperationRule(
        exact_filter_profile=_REPORT_CONFIG_FILTERS,
    ),
    ANALYSIS_TEMPLATE_OWN: OperationRule(
        exact_filter_profile=_TEMPLATE_FILTERS,
        exact_filter_values="template",
    ),
    ANALYSIS_TEMPLATE_SHARE: OperationRule(
        exact_filter_profile=_TEMPLATE_FILTERS,
        exact_filter_values="template",
    ),
    ANALYSIS_TEMPLATE_INTERNAL: OperationRule(
        exact_filter_profile=_TEMPLATE_FILTERS,
        exact_filter_values="template",
    ),
    ANALYSIS_TASK_OTHER_EVENT: OperationRule(
        exact_filter_profile=_OTHER_EVENT_FILTERS,
    ),
    PROMOTION_METRIC: OperationRule("promotion_metadata"),
    REPORT_BUSINESS_QUERY: OperationRule("business_query"),
    REPORT_MULTIDIM_QUERY: OperationRule("multidim_query"),
    REPORT_MULTIDIM_TOTAL: OperationRule("multidim_query"),
}


def operation_rule(operation_id: str) -> OperationRule:
    return OPERATION_RULES.get(operation_id, OperationRule())
