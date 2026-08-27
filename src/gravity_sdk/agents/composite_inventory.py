"""Value-free inventory for built-in Agent composite capabilities."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from . import report_directory as report_agent
from .advertiser_profile import ADVERTISER_PROFILE_CAPABILITY
from .analysis_default_dictionary import ANALYSIS_DEFAULT_DICTIONARY_CAPABILITY
from .realtime_event_catalog import REALTIME_EVENT_CATALOG_CAPABILITY
from .attribution_performance import ATTRIBUTION_PERFORMANCE_CAPABILITY
from .attribution_user_detail import ATTRIBUTION_USER_DETAIL_CAPABILITY
from .bilibili_account_performance import BILIBILI_ACCOUNT_PERFORMANCE_CAPABILITY
from .business_pulse import BUSINESS_PULSE_CAPABILITY
from .company_usage import COMPANY_USAGE_CAPABILITY
from .custom_audience import CUSTOM_AUDIENCE_CAPABILITY
from .dashboard import DASHBOARD_ANALYSIS_CAPABILITY
from .derived_metrics import DERIVED_METRICS_CAPABILITY
from .material_performance import MATERIAL_PERFORMANCE_CAPABILITY
from .monetization_guard import MONETIZATION_DETAIL_CAPABILITY
from .multidim import MULTIDIM_CAPABILITY
from .order_directory import ORDER_DIRECTORY_CAPABILITY
from .order_trace import ORDER_SPLIT_TRACE_CAPABILITY
from .promotion_performance import PROMOTION_PERFORMANCE_CAPABILITY
from .saved_analysis import SAVED_ANALYSIS_CAPABILITY
from .segment_members import SEGMENT_MEMBERS_CAPABILITY
from .segment_snapshot import SEGMENT_SNAPSHOT_CAPABILITY
from .semantic_compose import SEMANTIC_COMPOSE_CAPABILITY
from .title_package import TITLE_PACKAGE_CAPABILITY
from ..template_replay_surface import ANALYSIS_TEMPLATE_CAPABILITY


COMPOSITE_CAPABILITIES: tuple[Mapping[str, Any], ...] = (
    {
        "name": "analysis_context",
        "domain": "analysis",
        "aliases": (
            "analysis context",
            "analysis metadata",
            "analysis vocabulary",
            "分析上下文",
            "分析元数据",
        ),
        "description": (
            "并发读取事件、事件属性、用户属性、指标和报表模板的固定分析上下文。"
        ),
        "boundaries": (
            "不执行分析查询。",
            "不用于 App 治理快照或单用户旅程。",
        ),
        "required_inputs": ("app",),
        "input_schema": {
            "app": {"type": "string", "required": True, "nullable": False},
        },
    },
    DASHBOARD_ANALYSIS_CAPABILITY,
    MONETIZATION_DETAIL_CAPABILITY,
    SEGMENT_SNAPSHOT_CAPABILITY,
    SEGMENT_MEMBERS_CAPABILITY,
    ANALYSIS_DEFAULT_DICTIONARY_CAPABILITY,
    REALTIME_EVENT_CATALOG_CAPABILITY,
    SAVED_ANALYSIS_CAPABILITY,
    {
        **ANALYSIS_TEMPLATE_CAPABILITY,
        "boundaries": (
            "只对 compact Analysis Spec v1 或已证明的 Dashboard Web artifact 执行，其他 config 逐字段隔离报告。",
            "用于 template scope + template reference，不接受保存分析 ID/名称。",
        ),
    },
    DERIVED_METRICS_CAPABILITY,
    {
        "name": "dashboard_snapshot",
        "domain": "analysis",
        "accepted_domains": ("analysis", "report"),
        "aliases": (
            "dashboard snapshot",
            "dashboard context",
            "dashboard control context",
            "dashboard details members filters",
            "analyze dashboard details members filters",
            "inspect dashboard members and saved filters",
            "show dashboard members and favourites",
            "get dashboard details members and default favourite",
            "看板快照",
            "看板详情成员筛选",
            "分析看板详情成员筛选",
            "请查看看板成员和筛选收藏",
            "帮我检查看板成员和筛选收藏",
            "帮我获取看板详情和默认收藏",
        ),
        "intent_terms": (
            "dashboard snapshot",
            "dashboard_snapshot",
            "dashboard context",
            "dashboard control context",
            "dashboard details",
            "dashboard member",
            "dashboard filter",
            "dashboard favourite",
            "dashboard favorite",
            "看板快照",
            "看板详情",
            "看板成员",
            "看板筛选",
            "看板收藏",
        ),
        "description": (
            "按精确 ID 或精确名称解析一个 Analysis 看板，并发读取详情、成员、"
            "空间成员、筛选收藏和默认收藏；只返回控制面快照，不执行图表。"
        ),
        "boundaries": (
            "只返回控制面快照，不执行图表。",
        ),
        "required_inputs": ("app", "ref"),
        "input_schema": {
            "app": {
                "type": "string|integer",
                "required": True,
                "nullable": False,
            },
            "ref": {
                "type": "string|integer",
                "required": True,
                "nullable": False,
                "description": "Exact dashboard id or exact dashboard name.",
            },
        },
    },
    {
        "name": "app_snapshot",
        "domain": "app",
        "aliases": (
            "app snapshot",
            "application snapshot",
            "app governance",
            "应用快照",
            "应用治理",
        ),
        "description": (
            "并发读取 App 详情、实时事件、容量、权限菜单、角色和模板的治理快照。"
        ),
        "boundaries": (
            "不用于账号可读 App 项目清单。",
            "不执行分析查询。",
        ),
        "required_inputs": ("app",),
        "input_schema": {
            "app": {"type": "string", "required": True, "nullable": False},
        },
    },
    {
        "name": "attribution_snapshot",
        "domain": "attribution",
        "aliases": (
            "attribution snapshot",
            "attribution configuration",
            "归因快照",
            "归因配置",
        ),
        "description": "并发读取已登记归因映射、回溯与采集配置的固定快照。",
        "boundaries": (
            "只读已登记归因配置，不返回归因表现或单用户明细。",
        ),
        "required_inputs": ("app",),
        "input_schema": {
            "app": {"type": "string", "required": True, "nullable": False},
        },
    },
    MULTIDIM_CAPABILITY,
    SEMANTIC_COMPOSE_CAPABILITY,
    MATERIAL_PERFORMANCE_CAPABILITY,
    TITLE_PACKAGE_CAPABILITY,
    ORDER_DIRECTORY_CAPABILITY,
    ORDER_SPLIT_TRACE_CAPABILITY,
    PROMOTION_PERFORMANCE_CAPABILITY,
    ATTRIBUTION_PERFORMANCE_CAPABILITY,
    ATTRIBUTION_USER_DETAIL_CAPABILITY,
    BUSINESS_PULSE_CAPABILITY,
    COMPANY_USAGE_CAPABILITY,
    report_agent.REPORT_DIRECTORY_CAPABILITY,
    report_agent.REPORT_SUBSCRIPTIONS_CAPABILITY,
    CUSTOM_AUDIENCE_CAPABILITY,
    BILIBILI_ACCOUNT_PERFORMANCE_CAPABILITY,
    ADVERTISER_PROFILE_CAPABILITY,
)
