"""Static field evidence for the five governed Dashboard chart families."""

from __future__ import annotations


SUBJECT_KINDS = {
    "analysis_event": "event",
    "analysis_funnel": "funnel",
    "analysis_retention": "retention",
    "analysis_user_property": "property",
    "analysis_scatter": "scatter",
}

UI_FIELDS = {
    "event": frozenset({
        "aggregate_config", "calculateBody", "checkIndexList", "compareList",
        "currentSelectCompare", "customQueryItemList", "date_extra_data",
        "date_list", "getDateConfig", "groupBy", "groupByCreateTime",
        "isDateTotal", "isHandelHeader", "isShowSum", "queryItemList",
        "seriesType", "stageSumSetting", "tableShowType", "tableType",
        "tempSettingList",
    }),
    "property": frozenset({"calculateBody", "groupBy", "queryItem", "seriesType"}),
    "retention": frozenset({
        "calculateBody", "cascaderInput", "cascaderValue", "currentView",
        "date_extra_data", "displaySettingNums", "echartShowType", "getDateConfig",
        "group_by_list", "is_total_calc", "onlyShowSameData", "queryItemList",
        "sameTimeShowData", "sameTimeShowFormulaData", "showEchartsNumber",
        "total_calc_type", "week_first_day",
    }),
    "funnel": frozenset({
        "calculateBody", "checkIndexList", "date_extra_data", "getDateConfig",
        "getSelectQueryList", "groupBy", "queryItemList", "selectedSteps",
        "seriesType", "showEchartsNumber", "tableShowType",
    }),
    "scatter": frozenset({
        "calculateBody", "checkValue", "date_extra_data", "getDateConfig",
        "groupBy", "groupByCreateTime", "queryItemList", "seriesType",
    }),
}

BODY_FIELDS = {
    "event": frozenset({
        "custom_query_item_list", "extra_data", "global_cond_logic",
        "global_conditions", "group_by_list", "query_item_list", "split_event",
        "user_filtering",
    }),
    "property": frozenset({
        "group_by_list", "order_by_list", "property_condition", "query_item",
        "user_cond_logic", "user_filtering", "user_re_attribute_filtering",
    }),
    "retention": frozenset({
        "custom_before_method", "group_by_list", "period_calc_method",
        "property_condition", "query_item_before_after", "query_item_list",
        "user_cond_logic", "user_filtering", "user_re_attribute_filtering",
    }),
    "funnel": frozenset({
        "global_cond_logic", "global_conditions", "group_by_list",
        "query_item_list", "stat_time_window",
    }),
    "scatter": frozenset({"extra_data", "group_by_list", "query_item_list"}),
}


__all__ = ["BODY_FIELDS", "SUBJECT_KINDS", "UI_FIELDS"]
