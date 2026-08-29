"""Closed CT01 category and migration decisions."""

from __future__ import annotations

from typing import Any


SOURCE_CATEGORY_ORDER = (
    "付费分析",
    "游戏分析",
    "用户分析",
    "数据分析",
    "异常诊断",
    "舆情分析",
    "数据工程",
    "数据采集",
    "运营分析",
    "Agent",
    "知识库管理",
)
CATEGORY_POSITION = {
    category: position for position, category in enumerate(SOURCE_CATEGORY_ORDER)
}
TAXONOMY = {
    "付费分析": "taxonomy://gravity/monetization@1",
    "游戏分析": "taxonomy://gravity/gameplay@1",
    "用户分析": "taxonomy://gravity/user@1",
    "数据分析": "taxonomy://gravity/analysis@1",
    "异常诊断": "taxonomy://gravity/diagnostics@1",
    "舆情分析": "taxonomy://gravity/community@1",
    "数据工程": "taxonomy://gravity/data-engineering@1",
    "数据采集": "taxonomy://gravity/data-collection@1",
    "运营分析": "taxonomy://gravity/operations@1",
    "Agent": "taxonomy://gravity/agent@1",
    "知识库管理": "taxonomy://gravity/knowledge@1",
}

# New identities are deliberately absent until their mapping and license state are
# reviewed. Historical identities remain here even after a later source removal.
VENDOR_SOURCE_IDS = frozenset(
    {
        "ae-agent-resource-management",
        "ae-agent-team-management",
        "ae-analysis",
        "ae-analysis-global",
        "ae-analysis-intent",
        "ae-community",
        "ae-dataops",
        "ae-engage",
        "ae-knowledge-base-management",
        "ae-tracking-code-generation",
        "ae-tracking-plan-generation",
        "te-analysis-model-selection",
        "te-report-data-mismatch-diagnosis",
        "te-user-id-binding-diagnosis",
    }
)
SQL_ALTERNATIVE_SOURCE_IDS = frozenset({"generate-sql-query"})
GENERIC_SOURCE_IDS = frozenset(
    {
        "ad-delivery-analysis",
        "analysis-metric-definition-alignment",
        "app-device-performance-analysis",
        "channel-quality-analysis",
        "churn-user-identification-persona",
        "community-comment-analysis",
        "community-daily-report",
        "community-hot-topic-analysis",
        "community-weekly-report",
        "dashboard-no-data-diagnosis",
        "data-access-assistant",
        "data-integration-assistant",
        "filter-result-bias-diagnosis",
        "first-purchase-analysis",
        "funnel-analysis-misunderstanding-diagnosis",
        "game-campaign-effect-evaluation",
        "game-revenue-forecast",
        "gift-package-push-strategy",
        "gift-penetration-optimization",
        "level-churn-diagnosis",
        "lt-prediction",
        "ltv-analysis-monitoring",
        "ltv-curve-fitting-segmented-calculation",
        "ltv-dashboard-setup",
        "ltv-payback-period-prediction",
        "new-hero-launch-insight",
        "operation-journey-canvas-creation",
        "payment-attribution-analysis",
        "payment-conversion-funnel",
        "payment-funnel-setup",
        "payment-rate-anomaly-diagnosis",
        "product-pricing-optimization",
        "pvp-win-rate-analysis",
        "repurchase-analysis",
        "retention-analysis-data-verification",
        "single-user-behavior-analysis",
        "sql-performance-optimization",
        "system-field-reference-guide",
        "trino-metadata-query-analysis",
        "user-tag-system-design",
    }
)
MAPPED_SOURCE_IDS = VENDOR_SOURCE_IDS | SQL_ALTERNATIVE_SOURCE_IDS | GENERIC_SOURCE_IDS

RAW_ROOT_FIELDS = {
    "observed_at",
    "root_url",
    "robots_status",
    "category_counts",
    "pagination_urls",
    "sitemap_skill_count",
    "sitemap_orphans",
    "missing_from_sitemap",
    "items",
}
RAW_ITEM_FIELDS = {
    "source_id",
    "canonical_url",
    "title",
    "source_categories",
    "http_status",
    "final_url",
    "content_sha256",
    "h1",
    "declared_canonical_url",
}
PROTECTED_SOURCE_FIELDS = {
    "body",
    "content",
    "description",
    "example",
    "examples",
    "html",
    "raw_html",
    "image",
    "images",
    "chart",
    "charts",
    "customer",
    "customers",
    "case",
    "cases",
    "effect",
    "effect_number",
    "marketing",
}
DIFF_FIELDS = (
    "source_url",
    "source_title",
    "source_categories",
    "gravity_taxonomy_ids",
    "source_content_sha256",
    "specification_state",
    "mapping_kind",
    "future_skill_uri",
    "alternative_reason_code",
    "license_review",
    "independent_authorship",
    "distribution_allowed",
)
DIFF_STATES = ("added", "changed", "removed", "redirect", "unchanged")


def mapping_decision(source_id: str) -> dict[str, Any] | None:
    if source_id in GENERIC_SOURCE_IDS:
        return {
            "mapping_kind": "future_skill",
            "future_skill_uri": f"skill://gravity.game/{source_id}@1.0.0",
            "alternative_reason_code": None,
            "license_review": "approved",
            "independent_authorship": "required",
        }
    if source_id in VENDOR_SOURCE_IDS:
        return {
            "mapping_kind": "out_of_scope_alternative",
            "future_skill_uri": None,
            "alternative_reason_code": "THINKINGAI_VENDOR_SPECIFIC_OPERATION",
            "license_review": "blocked",
            "independent_authorship": "not_applicable",
        }
    if source_id in SQL_ALTERNATIVE_SOURCE_IDS:
        return {
            "mapping_kind": "out_of_scope_alternative",
            "future_skill_uri": None,
            "alternative_reason_code": "AUTOMATIC_TEXT_TO_SQL_OUT_OF_SCOPE",
            "license_review": "approved",
            "independent_authorship": "required",
        }
    return None


__all__ = [
    "CATEGORY_POSITION",
    "DIFF_FIELDS",
    "DIFF_STATES",
    "MAPPED_SOURCE_IDS",
    "PROTECTED_SOURCE_FIELDS",
    "RAW_ITEM_FIELDS",
    "RAW_ROOT_FIELDS",
    "SOURCE_CATEGORY_ORDER",
    "TAXONOMY",
    "mapping_decision",
]
