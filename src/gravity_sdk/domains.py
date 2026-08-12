"""Catalog-derived compatibility shortcuts for Gravity Insight domains.

The generic agent surface is search/describe/validate/read.  These structures
only preserve the older domain commands; operation identities come from the
compiled manifests consumed by the canonical SDK.
"""

from __future__ import annotations

import secrets
import string
import time
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from gravity_sdk.domain_catalog import CatalogOperation, load_compiled_catalog


@dataclass(frozen=True)
class LegacyDomainMaps:
    promotion_platforms: dict[str, dict[str, str]]
    promotion_primary_operations: dict[str, str]
    promotion_parent_filter_fields: dict[str, str]
    domain_operations: dict[str, tuple[str, ...]]
    analysis_metadata_operations: tuple[str, ...]
    analysis_query_operations: dict[str, str]
    analysis_segment_operations: dict[str, str]
    analysis_report_config_operations: dict[str, str]
    analysis_dashboard_operations: dict[str, str]
    analysis_value_operations: dict[str, str]
    analysis_directory_operations: dict[str, str]
    analysis_template_operations: dict[str, str]
    analysis_auxiliary_operations: dict[str, str]
    analysis_detail_operations: dict[str, str]
    analysis_paginated_operations: frozenset[str]
    attribution_status_operations: tuple[str, ...]
    multidim_metadata_operations: tuple[str, ...]
    multidim_template_scopes: tuple[str, ...]


@dataclass(frozen=True)
class _AnalysisMaps:
    metadata: tuple[str, ...]
    query: dict[str, str]
    segment: dict[str, str]
    report_config: dict[str, str]
    dashboard: dict[str, str]
    value: dict[str, str]
    directory: dict[str, str]
    template: dict[str, str]
    auxiliary: dict[str, str]
    detail: dict[str, str]
    paginated: frozenset[str]


# The compiled catalog intentionally describes upstream capabilities, not old
# CLI vocabulary or UI-specific filter encoding.  Keep the compatibility facts
# that cannot be inferred from domain/resource/action/platform in one place.
# Values are catalog selectors and public aliases, never operation identities.
LEGACY_CATALOG_EXCEPTIONS: Mapping[str, Any] = {
    "analysis_metadata_resources": (
        "event",
        "user_property",
        "event_property",
        "event_property_group",
    ),
    "analysis_query_alias_order": (
        "event",
        "funnel",
        "retention",
        "scatter",
        "property",
    ),
    "analysis_segment_aliases": {
        "detail": ("segment", "get"),
        "history": ("segment_history_version", "list"),
        "trend": ("segment_uid_result", "list"),
        "members": ("segment_user_detail", "list"),
        "evaluate": ("segment_rule", "query"),
    },
    "analysis_dashboard_aliases": {
        "tree": ("dashboard_tree", "tree"),
        "detail": ("dashboard", "detail"),
        "members": ("dashboard_members", "list"),
        "space-members": ("dashboard_space_members", "list"),
        "favourites": ("dashboard_condition_favourite", "list"),
        "default-favourite": (
            "dashboard_condition_favourite_default",
            "get",
        ),
    },
    "analysis_auxiliary_aliases": {
        "hidden-properties": ("report_hidden_property", "list"),
        "pay-events": ("pay_event_task", "list"),
        "other-events": ("other_event_task", "list"),
    },
    "attribution_status_resources": ("post_backtrack", "postback_mode"),
    "multidim_metadata_resources": (
        "media_enum",
        "metric",
        "custom_metric",
        "metric_tag_category",
        "metric_tag",
    ),
    "promotion_parent_filters": {
        ("kuaishou", "ad_unit"): "advertiser_id",
        ("honor", "campaign"): "advertiser_id",
        ("honor", "ad_group"): "campaign_id",
        ("ubix", "group"): "advertiser_id",
        ("xiaohongshu", "advertiser"): "developer_id",
    },
}


_PRIMARY_RESOURCE_ORDER = (
    "advertiser",
    "group",
    "report",
    "developer",
    "account",
    "campaign",
    "ad_group",
    "project",
    "ad_unit",
)


def _stable(operations: Iterable[CatalogOperation]) -> tuple[CatalogOperation, ...]:
    return tuple(
        operation
        for operation in operations
        if operation.stability == "stable" and operation.executable
    )


def _one(
    operations: Iterable[CatalogOperation],
    *,
    domain: str,
    resource: str,
    action: str | None = None,
    platform: str | None = None,
) -> CatalogOperation:
    matches = [
        operation
        for operation in operations
        if operation.domain == domain
        and operation.resource == resource
        and (action is None or operation.action == action)
        and (platform is None or operation.platform == platform)
    ]
    if len(matches) != 1:
        selector = f"{domain=}, {resource=}, {action=}, {platform=}"
        raise RuntimeError(
            f"legacy shortcut selector must match one catalog operation: {selector}"
        )
    return matches[0]


def _alias_map(
    operations: Iterable[CatalogOperation],
    aliases: Mapping[str, tuple[str, str]],
) -> dict[str, str]:
    return {
        alias: _one(
            operations,
            domain="analysis",
            resource=resource,
            action=action,
        ).operation_id
        for alias, (resource, action) in aliases.items()
    }


def _multidim_template_routes(
    operations: Iterable[CatalogOperation],
) -> tuple[dict[str, tuple[str, ...]], tuple[str, ...]]:
    routes: dict[str, tuple[str, ...]] = {}
    scopes: list[str] = []
    for operation in operations:
        if operation.domain != "report" or operation.resource != "template":
            continue
        parts = operation.operation_id.split(".")
        try:
            suffix = parts[parts.index("template") + 1 :]
        except ValueError as exc:
            raise RuntimeError(
                f"template operation lacks a template identity segment: {operation.operation_id}"
            ) from exc
        if suffix == ["tree"]:
            scope = "tree"
            key = "multidim.templates.tree"
        elif len(suffix) == 2 and suffix[-1] == "list":
            scope = suffix[0]
            key = f"multidim.templates.{scope}"
        elif len(suffix) == 2 and suffix[-1] == "get":
            key = "multidim.templates.get"
            scope = ""
        else:
            continue
        routes[key] = (operation.operation_id,)
        if scope:
            scopes.append(scope)
    return routes, tuple(scopes)


def _analysis_detail_alias(resource: str) -> str:
    if resource == "user_postback_log":
        resource = resource.removeprefix("user_")
    return resource.removesuffix("_detail").replace("_", "-")


def _derive_promotion_maps(
    operations: tuple[CatalogOperation, ...],
) -> tuple[dict[str, dict[str, str]], dict[str, str], dict[str, str]]:
    promotion_platforms: dict[str, dict[str, str]] = {}
    for operation in operations:
        if operation.domain == "promotion" and operation.platform:
            promotion_platforms.setdefault(operation.platform, {})[
                operation.resource
            ] = operation.operation_id

    promotion_primary_operations: dict[str, str] = {}
    for platform, levels in promotion_platforms.items():
        primary = next((level for level in _PRIMARY_RESOURCE_ORDER if level in levels), None)
        if primary is None:
            raise RuntimeError(f"promotion platform has no primary report: {platform}")
        promotion_primary_operations[platform] = levels[primary]

    parent_filters = LEGACY_CATALOG_EXCEPTIONS["promotion_parent_filters"]
    promotion_parent_filter_fields = {
        _one(
            operations,
            domain="promotion",
            platform=platform,
            resource=resource,
            action="list",
        ).operation_id: field
        for (platform, resource), field in parent_filters.items()
    }
    return (
        promotion_platforms,
        promotion_primary_operations,
        promotion_parent_filter_fields,
    )


def _derive_analysis_alias_maps(
    operations: tuple[CatalogOperation, ...],
) -> tuple[dict[str, str], dict[str, str], dict[str, str], dict[str, str]]:
    query_candidates = {
        operation.resource.removesuffix("_analysis").replace("_", "-"):
            operation.operation_id
        for operation in operations
        if operation.domain == "analysis"
        and operation.action == "query"
        and operation.resource != "segment_rule"
    }
    query = {
        alias: query_candidates[alias]
        for alias in LEGACY_CATALOG_EXCEPTIONS["analysis_query_alias_order"]
    }
    return (
        query,
        _alias_map(operations, LEGACY_CATALOG_EXCEPTIONS["analysis_segment_aliases"]),
        _alias_map(operations, LEGACY_CATALOG_EXCEPTIONS["analysis_dashboard_aliases"]),
        _alias_map(operations, LEGACY_CATALOG_EXCEPTIONS["analysis_auxiliary_aliases"]),
    )


def _derive_analysis_pattern_maps(
    operations: tuple[CatalogOperation, ...],
) -> tuple[
    dict[str, str],
    dict[str, str],
    dict[str, str],
    dict[str, str],
    dict[str, str],
]:
    report_config = {
        operation.action: operation.operation_id
        for operation in operations
        if operation.domain == "analysis" and operation.resource == "report_config"
    }
    value = {
        operation.resource.removesuffix("_value").replace("_", "-"):
            operation.operation_id
        for operation in operations
        if operation.domain == "analysis"
        and operation.resource in {"user_property_value", "event_property_value"}
    }
    directory = {
        "users": _one(
            operations,
            domain="analysis",
            resource="account_user",
            action="list",
        ).operation_id
    }
    template = {
        operation.resource.removeprefix("template_").replace("_", "-"):
            operation.operation_id
        for operation in operations
        if operation.domain == "analysis" and operation.resource.startswith("template_")
    }
    detail = {
        _analysis_detail_alias(operation.resource): operation.operation_id
        for operation in operations
        if operation.domain == "analysis"
        and (
            operation.resource.endswith("_detail")
            or operation.resource in {"user_event", "user_postback_log"}
        )
        and not operation.resource.startswith("segment_")
    }
    return report_config, value, directory, template, detail


def _derive_analysis_maps(
    operations: tuple[CatalogOperation, ...],
) -> _AnalysisMaps:
    query, segment, dashboard, auxiliary = _derive_analysis_alias_maps(operations)
    report_config, value, directory, template, detail = _derive_analysis_pattern_maps(
        operations
    )
    metadata_resources = set(LEGACY_CATALOG_EXCEPTIONS["analysis_metadata_resources"])
    metadata = tuple(
        operation.operation_id
        for operation in operations
        if operation.domain == "analysis"
        and operation.resource in metadata_resources
        and operation.action == "list"
    )
    paginated = frozenset(
        operation.operation_id
        for operation in operations
        if operation.domain == "analysis" and operation.paginated
    )
    return _AnalysisMaps(
        metadata=metadata,
        query=query,
        segment=segment,
        report_config=report_config,
        dashboard=dashboard,
        value=value,
        directory=directory,
        template=template,
        auxiliary=auxiliary,
        detail=detail,
        paginated=paginated,
    )


def _derive_domain_operations(
    operations: tuple[CatalogOperation, ...],
    analysis_queries: Mapping[str, str],
    template_routes: Mapping[str, tuple[str, ...]],
) -> dict[str, tuple[str, ...]]:
    return {
        "analysis.segments": (
            _one(operations, domain="analysis", resource="segment", action="list")
            .operation_id,
        ),
        **{
            f"analysis.{alias}": (operation_id,)
            for alias, operation_id in analysis_queries.items()
        },
        "apps.list": (
            _one(operations, domain="app", resource="app", action="list").operation_id,
        ),
        **template_routes,
        "multidim.query": (
            _one(operations, domain="report", resource="adreport").operation_id,
        ),
        "multidim.calc_total": (
            _one(operations, domain="report", resource="adreport_total").operation_id,
        ),
        "business_report.query": (
            _one(operations, domain="report", resource="business_report").operation_id,
        ),
        "objects.list": (
            _one(operations, domain="promotion", resource="object").operation_id,
        ),
        "materials.list": (
            _one(operations, domain="material", resource="local").operation_id,
        ),
        "materials.tags": (
            _one(operations, domain="material", resource="tag").operation_id,
        ),
        "materials.reviews": (
            _one(operations, domain="material", resource="review").operation_id,
        ),
        "attribution.maps": (
            _one(
                operations,
                domain="attribution",
                resource="postback_map_collect",
            ).operation_id,
        ),
    }


def _derive_batch_groups(
    operations: tuple[CatalogOperation, ...],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    attribution_resources = set(
        LEGACY_CATALOG_EXCEPTIONS["attribution_status_resources"]
    )
    attribution = tuple(
        operation.operation_id
        for operation in operations
        if operation.domain == "attribution"
        and operation.resource in attribution_resources
    )
    multidim_resources = set(
        LEGACY_CATALOG_EXCEPTIONS["multidim_metadata_resources"]
    )
    multidim = tuple(
        operation.operation_id
        for operation in operations
        if operation.domain == "report"
        and (
            operation.resource in multidim_resources
            or (
                operation.resource == "template"
                and operation.action == "list"
                and not operation.paginated
            )
        )
    )
    return attribution, multidim


def derive_legacy_domain_maps(
    catalog_operations: Iterable[CatalogOperation],
) -> LegacyDomainMaps:
    """Project the compiled catalog into the preserved CLI shortcut surface."""

    operations = _stable(tuple(catalog_operations))
    promotion_platforms, promotion_primary, parent_filters = _derive_promotion_maps(
        operations
    )
    analysis = _derive_analysis_maps(operations)
    template_routes, template_scopes = _multidim_template_routes(operations)
    domain_operations = _derive_domain_operations(
        operations, analysis.query, template_routes
    )
    attribution_status, multidim_metadata = _derive_batch_groups(operations)

    return LegacyDomainMaps(
        promotion_platforms=promotion_platforms,
        promotion_primary_operations=promotion_primary,
        promotion_parent_filter_fields=parent_filters,
        domain_operations=domain_operations,
        analysis_metadata_operations=analysis.metadata,
        analysis_query_operations=analysis.query,
        analysis_segment_operations=analysis.segment,
        analysis_report_config_operations=analysis.report_config,
        analysis_dashboard_operations=analysis.dashboard,
        analysis_value_operations=analysis.value,
        analysis_directory_operations=analysis.directory,
        analysis_template_operations=analysis.template,
        analysis_auxiliary_operations=analysis.auxiliary,
        analysis_detail_operations=analysis.detail,
        analysis_paginated_operations=analysis.paginated,
        attribution_status_operations=attribution_status,
        multidim_metadata_operations=multidim_metadata,
        multidim_template_scopes=template_scopes,
    )


COMPILED_CATALOG_OPERATIONS = load_compiled_catalog()
_DERIVED = derive_legacy_domain_maps(COMPILED_CATALOG_OPERATIONS)

PROMOTION_PLATFORMS = _DERIVED.promotion_platforms
PROMOTION_PRIMARY_OPERATIONS = _DERIVED.promotion_primary_operations
PROMOTION_PARENT_FILTER_FIELDS = _DERIVED.promotion_parent_filter_fields
DOMAIN_OPERATIONS = _DERIVED.domain_operations
ANALYSIS_METADATA_OPERATIONS = _DERIVED.analysis_metadata_operations
ANALYSIS_QUERY_OPERATIONS = _DERIVED.analysis_query_operations
ANALYSIS_SEGMENT_OPERATIONS = _DERIVED.analysis_segment_operations
ANALYSIS_REPORT_CONFIG_OPERATIONS = _DERIVED.analysis_report_config_operations
ANALYSIS_DASHBOARD_OPERATIONS = _DERIVED.analysis_dashboard_operations
ANALYSIS_VALUE_OPERATIONS = _DERIVED.analysis_value_operations
ANALYSIS_DIRECTORY_OPERATIONS = _DERIVED.analysis_directory_operations
ANALYSIS_TEMPLATE_OPERATIONS = _DERIVED.analysis_template_operations
ANALYSIS_AUXILIARY_OPERATIONS = _DERIVED.analysis_auxiliary_operations
ANALYSIS_DETAIL_OPERATIONS = _DERIVED.analysis_detail_operations
ANALYSIS_PAGINATED_OPERATIONS = _DERIVED.analysis_paginated_operations
ATTRIBUTION_STATUS_OPERATIONS = _DERIVED.attribution_status_operations
ATTRIBUTION_SNAPSHOT_OPERATIONS = tuple(
    sorted(
        operation.operation_id
        for operation in COMPILED_CATALOG_OPERATIONS
        if operation.domain == "attribution"
        and operation.stability == "stable"
        and operation.executable
    )
)
ATTRIBUTION_PAGINATED_OPERATIONS = frozenset(
    operation.operation_id
    for operation in COMPILED_CATALOG_OPERATIONS
    if operation.operation_id in ATTRIBUTION_SNAPSHOT_OPERATIONS
    and operation.paginated
)
MULTIDIM_METADATA_OPERATIONS = _DERIVED.multidim_metadata_operations
MULTIDIM_TEMPLATE_SCOPES = _DERIVED.multidim_template_scopes


def new_analysis_query_id() -> str:
    """Create the opaque identifier used by Gravity's analysis pages."""

    milliseconds = f"{time.time_ns() // 1_000_000:013d}"[-13:]
    alphabet = string.ascii_letters + string.digits
    return milliseconds + "".join(secrets.choice(alphabet) for _ in range(19))


# Standard promotion report codecs use the numeric equality operator.  The
# multidimensional report API uses string operators and must stay separate.
PROMOTION_EQUALS_OPERATOR = 1


def promotion_operation(platform: str, level: str | None = None) -> str:
    if platform not in PROMOTION_PLATFORMS:
        raise ValueError(f"unsupported promotion platform: {platform}")
    levels = PROMOTION_PLATFORMS[platform]
    if level is None:
        return PROMOTION_PRIMARY_OPERATIONS[platform]
    if level not in levels:
        raise ValueError(
            f"unsupported level {level!r} for {platform}; choose one of: "
            + ", ".join(levels)
        )
    return levels[level]
