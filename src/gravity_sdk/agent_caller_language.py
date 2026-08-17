"""Caller-language retrieval fields copied from authoritative product docs.

The strings in this module are product documentation, not recognizer aliases.
Keeping the snapshot in the installed package makes offline retrieval independent
of a source checkout while preserving explicit provenance for review.
"""

from __future__ import annotations

from .agent_app_catalog import APP_CATALOG_SELECTOR
from .agent_app_public_info import APP_PUBLIC_INFO_SELECTOR
from .agent_monetization_aggregate import MONETIZATION_AGGREGATE_SELECTOR


CALLER_LANGUAGE_SOURCES = (
    "docs/analysis-journeys.md",
    "docs/agent-workflow.md",
)


_ANALYSIS_JOURNEY_TITLES: dict[str, tuple[str, ...]] = {
    "analysis.query.spec:event": (
        "看某事件随时间、分组和条件的变化",
        "事件趋势、行为次数与发生量",
    ),
    "analysis.query.spec:funnel": (
        "看多步行为的转化漏斗",
        "转化路径与逐步转化",
    ),
    "analysis.query.spec:retention": (
        "看起始行为后的用户留存",
        "回访与复访",
    ),
    "analysis.query.spec:property": (
        "看用户或事件属性的分布与聚合",
        "用户分布与属性构成",
    ),
    "analysis.query.spec:scatter": (
        "看事件指标之间的散点关系",
        "指标相关关系",
    ),
    "analysis.query.spec": (
        "用同一分析定义比较两个时期",
    ),
    "composite:derived_metrics": (
        "在已有结果上执行调用方绑定的派生算术与声明集合对账",
    ),
    "analysis.segment.rule.spec": (
        "评估一组人群规则命中的人数与占比",
    ),
    "composite:analysis_context": (
        "一次取得构造分析所需的事件、属性、指标和模板上下文",
    ),
    "composite:app_snapshot": (
        "一次查看 App 的容量、角色、权限菜单和实时事件治理快照",
    ),
    "composite:attribution_snapshot": (
        "一次查看 App 已登记的归因配置、映射与回溯设置",
    ),
    "composite:user_journey": (
        "查看单个用户某日的画像、事件时间线和回传记录",
    ),
    "composite:business_pulse": (
        "汇总多个 App 的业务趋势和小时脉搏",
    ),
    "composite:company_usage": (
        "查看公司资源用量趋势",
    ),
    "composite:custom_audience": (
        "查看自定义人群覆盖与状态",
    ),
    "composite:material_performance": (
        "比较已支持平台的素材表现",
    ),
    "composite:order_directory": (
        "读取单日订单目录",
    ),
    "composite:order_split_trace": (
        "按 TraceID 追踪单日订单拆单结果",
    ),
    "composite:monetization_detail": (
        "读取单日完整已登记变现明细",
    ),
    "gap:WORKSPACE_SQL_PRODUCT_NOT_CONFIGURED": (
        "执行 workspace 登记的聚合 SQL 分析产品",
    ),
    "composite:dashboard_snapshot": (
        "查看看板详情、成员和筛选收藏",
    ),
    "composite:dashboard_analysis": (
        "忠实重放看板图表及页面条件",
    ),
    "composite:saved_analysis": (
        "按精确引用重放保存分析",
    ),
    "composite:analysis_template": (
        "按精确引用重放分析模板",
    ),
    "composite:segment_snapshot": (
        "查看分群详情、版本和单日聚合结果",
    ),
    "composite:segment_members": (
        "查看精确分群成员及逐人属性",
    ),
    "composite:multidim": (
        "用显式物理维度、指标和筛选读取多维报表",
    ),
    "composite:semantic_compose": (
        "用版本化语义成员组合已登记指标、维度与时间粒度",
    ),
    "composite:promotion_performance": (
        "按平台和物理指标读取推广表现",
    ),
    "composite:bilibili_account_performance": (
        "查看 B 站账户/产品投放表现",
    ),
    "composite:advertiser_profile": (
        "读取巨量广告主消耗、余额、预算模式和状态",
    ),
    "composite:title_package": (
        "读取巨量普通/标准标题包的标题数、计划数与成本表现",
    ),
    "metadata:search": (
        "离线查找可用于分析的事件、属性、指标和模板名称",
    ),
    "metadata:table_lineage": (
        "查询已同步的数据表版本与变更观察",
    ),
    "export.material.report.start": (
        "创建、轮询并下载素材分析报表",
    ),
    "composite:analysis_default_dictionary": (
        "查询分析默认值字典",
    ),
    "gap:REALTIME_EVENT_CATALOG_CONTRACT_MISSING": (
        "查询实时事件目录",
    ),
    "composite:report_directory": (
        "查找自有、共享和 MasterKey 报表并读取其定义",
    ),
    "composite:report_subscriptions": (
        "查看报表订阅清单",
    ),
    "gap:MEDIA_REPORT_ITEM_SCHEMA_MISSING": (
        "查找可用的媒体报表",
    ),
    "composite:attribution_performance": (
        "查询归因表现聚合",
    ),
    "composite:attribution_user_detail": (
        "下钻单用户归因明细",
    ),
    "gap:CURRENT_TABLE_SCHEMA_PARENT_MISSING": (
        "按表名或 App 查询数据表当前 schema、字段和版本",
    ),
    "gap:NON_BYTEDANCE_HIERARCHY_PARENT_MISSING": (
        "下钻非 Bytedance 平台的计划、组和创意表现",
    ),
    "gap:PLATFORM_SPECIFIC_CREATIVE_CONTRACT_MISSING": (
        "深查各平台专属素材与创意",
    ),
    "gap:ANALYSIS_EXPORT_FILE_CONTRACT_MISSING": (
        "导出事件、分群、用户、付费或变现分析结果",
    ),
    "material.asset.fetch": (
        "按精确平台素材引用预览或下载图片/视频",
    ),
    APP_CATALOG_SELECTOR: (
        "查找当前账号可读的 App 项目",
    ),
    APP_PUBLIC_INFO_SELECTOR: (
        "查看 App 的 OneLink 与公开信息绑定",
    ),
    MONETIZATION_AGGREGATE_SELECTOR: (
        "按平台、广告位和日期汇总变现结果",
        "聚合变现收入，不是逐行明细",
    ),
}


_AGENT_WORKFLOW_TASKS: dict[str, tuple[str, ...]] = {
    "analysis.query.spec": ("Analysis 编译/跨期对比",),
    "composite:multidim": ("Multidim 使用物理输入，不新增 Spec",),
    "composite:business_pulse": ("经营概览和趋势",),
    "composite:promotion_performance": (
        "推广表现要求调用方先明确一个 App、日期和平台数组",
    ),
    "composite:custom_audience": ("自定义人群覆盖与状态",),
    "composite:order_directory": ("普通目录",),
    "composite:monetization_detail": ("变现明细",),
    "analysis.segment.rule.spec": ("人群规则只接受显式紧凑 spec",),
    "composite:segment_members": ("分群成员与逐人属性",),
    "composite:analysis_default_dictionary": ("Analysis 默认值字典",),
    "composite:saved_analysis": (
        "保存分析已知稳定 ID/精确名称和日期窗",
    ),
    "metadata:search": ("离线元数据与 Analysis 词汇",),
}


def caller_language_fields(selector: str) -> tuple[str, ...]:
    """Return deterministic, deduplicated caller-language fields for a selector."""

    return tuple(dict.fromkeys(
        (*_ANALYSIS_JOURNEY_TITLES.get(selector, ()),
         *_AGENT_WORKFLOW_TASKS.get(selector, ()))
    ))


__all__ = ["CALLER_LANGUAGE_SOURCES", "caller_language_fields"]
