"""Static route semantics used by Census coverage accounting."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Mapping
from typing import Any, Callable, Iterable


PLATFORMS = (
    "bytedance", "tencent", "kuaishou", "oppo", "bilibili", "baidu", "vivo",
    "iqiyi", "weibo", "apple", "asa", "uc", "huawei_store", "huawei",
    "honor", "ubix", "xiaohongshu", "xiaomi", "qihu360", "360", "sigmob",
    "youdao", "huya", "alipay", "bing", "wechat_video", "taptap",
)


def _contains_any(value: str, tokens: Iterable[str]) -> bool:
    return any(token in value for token in tokens)


def _contains_action(value: str, actions: Iterable[str]) -> bool:
    return any(
        re.search(rf"(?:^|[/_]){re.escape(action)}(?:[/_]|$)", value) is not None
        for action in actions
    )


def _classify_read_signal(
    method: str,
    path: str,
    evidence: str,
    confidence: str,
    confirmed_read_routes: set[tuple[str, str]],
) -> tuple[str, str, list[str]]:
    if method in {"GET", "HEAD", "OPTIONS"}:
        return "uncovered_read", confidence, [evidence]
    if method == "POST":
        if (method, path) in confirmed_read_routes:
            return "uncovered_read", "reviewed", ["probe_read_confirmation", evidence]
        return "unsafe_unknown", "unverified", [evidence]
    return "static_read_candidate", confidence, [evidence]


def classify_route_semantics(
    method: str,
    path: str,
    classification: Mapping[str, Any] | None,
    confirmed_read_routes: set[tuple[str, str]],
) -> tuple[str, str, list[str]]:
    if not classification:
        return classify_semantics(method, path, confirmed_read_routes)
    name = str(classification["classification"])
    evidence = f"route_registry:{classification['reason_code']}"
    if name == "read":
        return _classify_read_signal(
            method, path, evidence, "registered", confirmed_read_routes
        )
    status = {
        "write": "uncovered_write",
        "export": "uncovered_export",
        "auth": "uncovered_auth_or_proxy",
        "proxy": "uncovered_auth_or_proxy",
        "non_api": "unsupported_non_api",
    }[name]
    return status, "registered", [evidence]


def classify_route_accounting(
    *,
    covered: bool,
    reserved: bool,
    nonstable_stability: str | None,
    registered: bool,
    status: str,
) -> tuple[str, str]:
    if covered:
        return "covered_executable", "executable"
    if reserved:
        return "accounted_blocked_write", "contract_only"
    if nonstable_stability:
        accounting = {
            "blocked_write": "accounted_blocked_write",
            "blocked_privacy": "accounted_blocked_privacy",
            "permission_unavailable": "accounted_permission_unavailable",
            "deprecated": "accounted_deprecated",
            "experimental": "accounted_experimental",
        }.get(nonstable_stability, "accounted_nonstable")
        return accounting, "catalog_only"
    if registered and status not in {
        "uncovered_read", "static_read_candidate", "unsafe_unknown"
    }:
        return "accounted_unsupported", "unsupported"
    if status in {"uncovered_read", "static_read_candidate"}:
        return (
            "accounted_read_candidate"
            if status == "uncovered_read"
            else "accounted_static_read_candidate",
            "candidate",
        )
    if status == "unsafe_unknown":
        return "accounted_unsafe_unknown", "blocked"
    if status == "uncovered_export":
        return "accounted_export_candidate", "candidate"
    return "unaccounted", "unclassified"


def classify_semantics(
    method: str,
    path: str,
    confirmed_read_routes: set[tuple[str, str]] | None = None,
) -> tuple[str, str, list[str]]:
    confirmed_read_routes = confirmed_read_routes or set()
    lower = path.lower()
    if _contains_any(
        lower,
        (
            "/auth", "login", "logout", "oauth", "sso/", "token/", "captcha",
            "/proxy/", "/gateway/", "callback", "/post/api/", "/query_api/",
        ),
    ):
        return "uncovered_auth_or_proxy", "high", ["auth_or_proxy_path_token"]
    if _contains_action(lower, ("delete", "remove", "clear")):
        return "uncovered_write", "high", ["destructive_action_path_token"]
    if _contains_any(
        lower, ("export", "download", "/excel", "/csv", "/xlsx", "file_download")
    ):
        return "uncovered_export", "high", ["export_path_token"]
    if method in {"PUT", "PATCH", "DELETE"}:
        return "uncovered_write", "high", ["mutating_http_method"]
    write_actions = (
        "create", "add", "update", "edit", "delete", "remove", "save", "upload",
        "import", "copy", "move", "bind", "unbind", "enable", "disable", "submit",
        "approve", "execute", "cancel", "start", "stop", "sync", "reset", "push",
        "share", "collect", "clear", "kill", "terminate",
    )
    if _contains_action(lower, write_actions):
        return "uncovered_write", "medium", ["write_action_path_token"]
    read_tokens = (
        "/list", "/get", "/detail", "/query", "/search", "/tree", "/info",
        "/status", "/count", "/stat", "/trend", "/preview", "/check", "/validate",
        "/evaluate", "/calc", "/enums", "/options", "/report/", "/filters",
        "/components", "/favorites", "/campaigns", "/ad_groups", "/batch_options",
        "_detail/", "_list/", "_get/", "_info/",
    )
    if method in {"GET", "HEAD", "OPTIONS"}:
        return "uncovered_read", "high", ["safe_http_method"]
    if _contains_any(lower, read_tokens):
        return _classify_read_signal(
            method, path, "read_action_path_token", "medium", confirmed_read_routes
        )
    return "unclassified", "low", ["insufficient_semantic_evidence"]


def _replace_platform(path: str) -> str:
    value = path.lower().replace("/huawei/store/", "/{platform}/")
    value = value.replace("/wechat/video/", "/{platform}/")
    for platform in sorted(PLATFORMS, key=len, reverse=True):
        value = re.sub(rf"(?<=/){re.escape(platform)}(?=/)", "{platform}", value)
    return value


def _replace_level(path: str) -> str:
    return re.sub(
        r"(?<=/)(?:advertiser|account|developer|project|campaign|ad_plan|plan|"
        r"ad_group|adgroup|ad_unit|unit|group|creative|creativity|advertisement|ad|"
        r"material|asset|report|stat|data)(?=/)",
        "{level}",
        path.lower(),
    )


def _family_candidates(
    reads: list[dict[str, Any]],
    kind: str,
    signature_fn: Callable[[dict[str, Any]], tuple[Any, ...]],
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in reads:
        groups[signature_fn(row)].append(row)
    for signature, members in groups.items():
        unique_members = sorted({(item["method"], item["path"]) for item in members})
        if len(unique_members) < 2:
            continue
        candidates.append(
            {
                "family_kind": kind,
                "signature": " | ".join(str(item) for item in signature),
                "members": [
                    {"method": method, "path": path} for method, path in unique_members
                ],
                "member_count": len(unique_members),
            }
        )
    return candidates


def _assign_contract_families(
    rows: list[dict[str, Any]], candidates: list[dict[str, Any]]
) -> None:
    memberships: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for family in candidates:
        for member in family["members"]:
            memberships[(member["method"], member["path"])].append(family)
    for row in rows:
        families = memberships.get((row["method"], row["path"]), [])
        primary = min(
            families,
            key=lambda item: (-item["member_count"], item["family_kind"], item["family_id"]),
            default=None,
        )
        row["contract_family"] = (
            {
                "family_id": primary["family_id"],
                "family_kind": primary["family_kind"],
                "member_count": primary["member_count"],
            }
            if primary
            else None
        )
        row["contract_family_alternates"] = [
            item["family_id"] for item in families if item is not primary
        ]


def identify_contract_families(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    reads = [
        row
        for row in rows
        if row["status"] == "uncovered_read" and row["business_module"] == "推广平台"
    ]
    candidates = _family_candidates(
        reads,
        "same_level_cross_platform",
        lambda row: (row["method"], _replace_platform(row["path"])),
    ) + _family_candidates(
        reads,
        "same_platform_cross_level",
        lambda row: (row["method"], row["promotion_platform"], _replace_level(row["path"])),
    )
    candidates.sort(
        key=lambda item: (item["family_kind"], item["signature"], item["member_count"])
    )
    for index, family in enumerate(candidates, 1):
        family["family_id"] = f"promotion.family.{index:03d}"
    _assign_contract_families(rows, candidates)
    return candidates


def _api_tail(path: str, comparison_path: Callable[[str], str]) -> str:
    parts = comparison_path(path).strip("/").split("/")
    for index, part in enumerate(parts):
        if re.fullmatch(r"v\d+(?:\.\d+)?", part):
            return "/".join(parts[index + 1 :])
    return "/".join(parts)


def _reconciliation_category(
    operation: dict[str, Any],
    exact: set[tuple[str, str]],
    normalized: set[tuple[str, str]],
    baseline_normalized: set[tuple[str, str]],
    normalize_path: Callable[[str], str],
    comparison_path: Callable[[str], str],
) -> str:
    exact_key = (operation["method"], normalize_path(operation["path"]))
    normalized_key = (operation["method"], comparison_path(operation["path"]))
    if normalized_key in baseline_normalized:
        return "previously_covered"
    if exact_key in exact:
        return "newly_covered_from_previously_unfetched_chunk"
    if normalized_key in normalized:
        return "normalization_false_gap_fixed"
    return "manifest_route_absent_from_frontend"


def _reconciliation_row(
    operation: dict[str, Any],
    routes: list[dict[str, Any]],
    category: str,
    comparison_path: Callable[[str], str],
) -> dict[str, Any]:
    similar = sorted(
        {
            (route["method"], route["path"])
            for route in routes
            if _api_tail(route["path"], comparison_path)
            == _api_tail(operation["path"], comparison_path)
            and comparison_path(route["path"]) != comparison_path(operation["path"])
        }
    )
    return {
        "operation_id": operation["operation_id"],
        "method": operation["method"],
        "path": operation["path"],
        "manifest_file": operation["manifest_file"],
        "category": category,
        "similar_frontend_routes": [
            {"method": method, "path": path} for method, path in similar[:50]
        ]
        if category == "manifest_route_absent_from_frontend"
        else [],
    }


def reconcile_stable_operations(
    operations: list[dict[str, Any]],
    routes: list[dict[str, Any]],
    baseline_routes: list[dict[str, Any]] | None,
    *,
    normalize_path: Callable[[str], str],
    comparison_path: Callable[[str], str],
) -> dict[str, Any]:
    stable = [item for item in operations if item["stability"] == "stable"]
    exact = {(item["method"], normalize_path(item["path"])) for item in routes}
    normalized = {(item["method"], comparison_path(item["path"])) for item in routes}
    baseline_normalized = {
        (item["method"], comparison_path(item["path"])) for item in (baseline_routes or [])
    }
    rows = []
    for operation in stable:
        category = _reconciliation_category(
            operation,
            exact,
            normalized,
            baseline_normalized,
            normalize_path,
            comparison_path,
        )
        rows.append(_reconciliation_row(operation, routes, category, comparison_path))
    counts = Counter(item["category"] for item in rows)
    return {
        "baseline_supplied": baseline_routes is not None,
        "stable_operations": len(stable),
        "summary": dict(sorted(counts.items())),
        "previously_missing_breakdown": {
            "a_previously_unfetched_chunk": counts[
                "newly_covered_from_previously_unfetched_chunk"
            ],
            "b_normalization_false_gap_fixed": counts["normalization_false_gap_fixed"],
            "c_manifest_route_absent_from_frontend": counts[
                "manifest_route_absent_from_frontend"
            ],
        },
        "operations": sorted(rows, key=lambda item: item["operation_id"]),
    }


__all__ = [
    "PLATFORMS",
    "classify_route_accounting",
    "classify_route_semantics",
    "classify_semantics",
    "identify_contract_families",
    "reconcile_stable_operations",
]
