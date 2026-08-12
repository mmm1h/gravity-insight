from __future__ import annotations

import copy
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

from .io import read_json, write_json
from .normalize import comparison_path, normalize_path


MODULES = ("分析", "推广平台", "资产", "素材", "报表", "App 与账号", "归因", "元数据", "其它")
PLATFORMS = (
    "bytedance",
    "tencent",
    "kuaishou",
    "oppo",
    "bilibili",
    "baidu",
    "vivo",
    "iqiyi",
    "weibo",
    "apple",
    "asa",
    "uc",
    "huawei_store",
    "huawei",
    "honor",
    "ubix",
    "xiaohongshu",
    "xiaomi",
    "qihu360",
    "360",
    "sigmob",
    "youdao",
    "huya",
    "alipay",
    "bing",
    "wechat_video",
    "taptap",
)
LEVEL_RULES = (
    ("账户", ("account", "advertiser", "developer")),
    ("项目", ("project",)),
    ("计划", ("campaign", "ad_plan")),
    ("广告组", ("ad_group", "adgroup", "unit", "ad_unit", "group")),
    ("广告/创意", ("creative", "/ad/", "advertisement")),
    ("素材", ("material", "asset")),
    ("报表", ("report", "stat", "data")),
)
PROMOTION_LEVELS = tuple(label for label, _ in LEVEL_RULES) + ("其它",)


def load_manifest_operations(manifest_dir: Path) -> list[dict[str, Any]]:
    operations: list[dict[str, Any]] = []
    for path in sorted(manifest_dir.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        items = payload.get("operations") if isinstance(payload, dict) else None
        if not isinstance(items, list):
            raise ValueError(f"manifest has no operations list: {path}")
        for item in items:
            if not isinstance(item, dict):
                raise ValueError(f"manifest operation is not an object: {path}")
            operations.append(
                {
                    "operation_id": str(item.get("operation_id", "")),
                    "method": str(item.get("upstream_method", "")).upper(),
                    "path": normalize_path(str(item.get("path_template", ""))),
                    "stability": str(item.get("stability", "")),
                    "domain": str(item.get("domain", "")),
                    "platform": str(item.get("platform", "")),
                    "manifest_file": path.name,
                    "executable": bool(item.get("executable", True)),
                    "block_reason": item.get("block_reason"),
                    "source_type": "manifest",
                }
            )
    return operations


def load_write_reservations(reservation_dir: Path) -> list[dict[str, Any]]:
    reservations: list[dict[str, Any]] = []
    seen_routes: set[tuple[str, str]] = set()
    if not reservation_dir.is_dir():
        return reservations
    for path in sorted(reservation_dir.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        operation = payload.get("operation") if isinstance(payload, dict) else None
        metadata = payload.get("reservation") if isinstance(payload, dict) else None
        if not isinstance(operation, dict) or not isinstance(metadata, dict):
            raise ValueError(f"reservation has no operation/reservation object: {path}")
        if operation.get("effect") != "mutation":
            raise ValueError(f"reservation effect is not mutation: {path}")
        if operation.get("stability") != "blocked_write" or operation.get("executable") is not False:
            raise ValueError(f"reservation is not non-executable blocked_write: {path}")
        if operation.get("block_reason") != "mutation_sdk_not_implemented":
            raise ValueError(f"reservation has an unexpected block reason: {path}")
        reservation = {
                "operation_id": str(operation.get("operation_id", "")),
                "method": str(operation.get("upstream_method", "")).upper(),
                "path": normalize_path(str(operation.get("path_template", ""))),
                "stability": "blocked_write",
                "domain": str(operation.get("domain", "")),
                "platform": str(operation.get("platform", "")),
                "manifest_file": None,
                "source_file": path.name,
                "executable": False,
                "block_reason": "mutation_sdk_not_implemented",
                "source_type": "reservation",
            }
        key = (reservation["method"], reservation["path"])
        if key in seen_routes:
            raise ValueError(f"duplicate write reservation route: {key[0]} {key[1]}")
        seen_routes.add(key)
        reservations.append(reservation)
    return reservations


def load_route_classifications(registry_path: Path) -> list[dict[str, Any]]:
    if not registry_path.is_file():
        return []
    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != (
        "gravity-insight.route-classification.v1"
    ):
        raise ValueError(f"invalid route classification registry: {registry_path}")
    routes = payload.get("routes")
    if not isinstance(routes, list):
        raise ValueError(f"route classification registry has no routes array: {registry_path}")
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in routes:
        if not isinstance(item, dict):
            raise ValueError(f"route classification is not an object: {registry_path}")
        normalized = dict(item)
        normalized["method"] = str(item.get("method", "")).upper()
        normalized["path"] = normalize_path(str(item.get("path", "")))
        key = (normalized["method"], normalized["path"])
        if key in seen:
            raise ValueError(f"duplicate route classification: {key[0]} {key[1]}")
        seen.add(key)
        result.append(normalized)
    return result


def _contains_any(value: str, tokens: Iterable[str]) -> bool:
    return any(token in value for token in tokens)


def _contains_action(value: str, actions: Iterable[str]) -> bool:
    return any(
        re.search(rf"(?:^|[/_]){re.escape(action)}(?:[/_]|$)", value) is not None
        for action in actions
    )


def classify_semantics(method: str, path: str) -> tuple[str, str, list[str]]:
    lower = path.lower()
    if _contains_any(lower, ("/auth", "login", "logout", "oauth", "sso/", "token/", "captcha", "/proxy/", "/gateway/", "callback", "/post/api/", "/query_api/")):
        return "uncovered_auth_or_proxy", "high", ["auth_or_proxy_path_token"]
    if _contains_action(lower, ("delete", "remove", "clear")):
        return "uncovered_write", "high", ["destructive_action_path_token"]
    if _contains_any(lower, ("export", "download", "/excel", "/csv", "/xlsx", "file_download")):
        return "uncovered_export", "high", ["export_path_token"]
    if method in {"PUT", "PATCH", "DELETE"}:
        return "uncovered_write", "high", ["mutating_http_method"]
    write_actions = (
        "create",
        "add",
        "update",
        "edit",
        "delete",
        "remove",
        "save",
        "upload",
        "import",
        "copy",
        "move",
        "bind",
        "unbind",
        "enable",
        "disable",
        "submit",
        "approve",
        "execute",
        "cancel",
        "start",
        "stop",
        "sync",
        "reset",
        "push",
        "share",
        "collect",
        "clear",
        "kill",
        "terminate",
    )
    if _contains_action(lower, write_actions):
        return "uncovered_write", "medium", ["write_action_path_token"]
    read_tokens = (
        "/list",
        "/get",
        "/detail",
        "/query",
        "/search",
        "/tree",
        "/info",
        "/status",
        "/count",
        "/stat",
        "/trend",
        "/preview",
        "/check",
        "/validate",
        "/evaluate",
        "/calc",
        "/enums",
        "/options",
        "/report/",
        "/filters",
        "/components",
        "/favorites",
        "/campaigns",
        "/ad_groups",
        "/batch_options",
        "_detail/",
        "_list/",
        "_get/",
        "_info/",
    )
    if method in {"GET", "HEAD", "OPTIONS"}:
        return "uncovered_read", "high", ["safe_http_method"]
    if _contains_any(lower, read_tokens):
        return "uncovered_read", "medium", ["read_action_path_token"]
    return "unclassified", "low", ["insufficient_semantic_evidence"]


def classify_module(path: str) -> str:
    lower = path.lower()
    if _contains_any(lower, ("attribution", "postback", "click_url", "track_link", "tracking_link")):
        return "归因"
    if _contains_any(lower, ("material", "creative", "image", "video", "media_library")) and not re.search(r"/wechat(?:_|/)video/report/", lower):
        return "素材"
    if _contains_any(lower, ("/asset/", "promoted_object", "product_library", "audience_package")):
        return "资产"
    if _contains_any(lower, ("dataanalysis", "/analysis/", "funnel", "retention", "segment", "kanban", "user_behavior", "event_analysis", "/openapi/api/v1/event/")):
        return "分析"
    if _contains_any(lower, PLATFORMS) or _contains_any(
        lower, ("advertiser", "ad_group", "ad_unit", "campaign", "promotion", "adcreate", "ad_create")
    ):
        return "推广平台"
    if _contains_any(lower, ("adreport", "business_report", "conftemplate", "confmetric", "/report/")):
        return "报表"
    if _contains_any(lower, ("metadata", "meta_data", "dictionary", "enum", "metric", "property", "event_dim")):
        return "元数据"
    if _contains_any(lower, ("account_center", "/app/", "/user/", "/member/", "/dept/", "/role/", "/company/")):
        return "App 与账号"
    return "其它"


def promotion_dimensions(path: str) -> tuple[str, str]:
    lower = path.lower()
    platform = "通用/未知"
    platform_aliases = {
        "huawei_store": ("/huawei/store/", "/huawei_store/"),
        "wechat_video": ("/wechat/video/", "/wechat_video/"),
    }
    for candidate, aliases in platform_aliases.items():
        if any(alias in lower for alias in aliases):
            platform = candidate
            break
    for candidate in PLATFORMS:
        if platform != "通用/未知":
            break
        if re.search(rf"(?:/|_|-){re.escape(candidate)}(?:/|_|-|$)", lower):
            platform = "qihu360" if candidate == "360" else candidate
            break
    level = "其它"
    for label, tokens in LEVEL_RULES:
        if _contains_any(lower, tokens):
            level = label
            break
    return platform, level


def estimate_read_cost(route: dict[str, Any]) -> tuple[str, str, str]:
    path = str(route["path"]).lower()
    method = str(route["method"]).upper()
    evidence_kinds = set(route.get("route_evidence_kinds", []))
    if "proxy_query_api_value" in evidence_kinds:
        return "高", "proxy target requires a dynamic upstream request envelope", "medium"
    if "{" in path or _contains_any(
        path,
        (
            "/query",
            "/search",
            "/calc",
            "/evaluate",
            "/analysis/",
            "/adreport/",
            "/report/",
            "/metric",
            "/filter",
            "/trend",
            "/stat",
        ),
    ):
        return "高", "dynamic path or complex query/report semantics", "medium"
    _, level = promotion_dimensions(path)
    if level in {"项目", "计划", "广告组", "广告/创意", "素材"}:
        return "中", f"{level} lookup normally depends on a parent account or campaign", "medium"
    if method == "POST" and _contains_any(path, ("/detail", "/tree", "/options", "/components")):
        return "中", "POST read requires a parent or structured selector", "low"
    return "低", "flat list/detail lookup with no evident parent dependency", "medium"


def _replace_platform(path: str) -> str:
    value = path.lower()
    value = value.replace("/huawei/store/", "/{platform}/")
    value = value.replace("/wechat/video/", "/{platform}/")
    for platform in sorted(PLATFORMS, key=len, reverse=True):
        value = re.sub(
            rf"(?<=/){re.escape(platform)}(?=/)", "{platform}", value
        )
    return value


def _replace_level(path: str) -> str:
    return re.sub(
        r"(?<=/)(?:advertiser|account|developer|project|campaign|ad_plan|plan|"
        r"ad_group|adgroup|ad_unit|unit|group|creative|creativity|advertisement|ad|"
        r"material|asset|report|stat|data)(?=/)",
        "{level}",
        path.lower(),
    )


def identify_contract_families(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    reads = [
        row
        for row in rows
        if row["status"] == "uncovered_read" and row["business_module"] == "推广平台"
    ]
    candidates: list[dict[str, Any]] = []
    for kind, signature_fn in (
        ("same_level_cross_platform", lambda row: (row["method"], _replace_platform(row["path"]))),
        (
            "same_platform_cross_level",
            lambda row: (row["method"], row["promotion_platform"], _replace_level(row["path"])),
        ),
    ):
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
    candidates.sort(
        key=lambda item: (item["family_kind"], item["signature"], item["member_count"])
    )
    for index, family in enumerate(candidates, 1):
        family["family_id"] = f"promotion.family.{index:03d}"
    memberships: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for family in candidates:
        for member in family["members"]:
            memberships[(member["method"], member["path"])].append(family)
    for row in rows:
        families = memberships.get((row["method"], row["path"]), [])
        if families:
            primary = sorted(
                families,
                key=lambda item: (-item["member_count"], item["family_kind"], item["family_id"]),
            )[0]
            row["contract_family"] = {
                "family_id": primary["family_id"],
                "family_kind": primary["family_kind"],
                "member_count": primary["member_count"],
            }
            row["contract_family_alternates"] = [
                item["family_id"] for item in families if item is not primary
            ]
        else:
            row["contract_family"] = None
            row["contract_family_alternates"] = []
    return candidates


def reconcile_stable_operations(
    operations: list[dict[str, Any]],
    routes: list[dict[str, Any]],
    baseline_routes: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    def api_tail(path: str) -> str:
        parts = comparison_path(path).strip("/").split("/")
        for index, part in enumerate(parts):
            if re.fullmatch(r"v\d+(?:\.\d+)?", part):
                return "/".join(parts[index + 1 :])
        return "/".join(parts)

    stable = [item for item in operations if item["stability"] == "stable"]
    exact = {(item["method"], normalize_path(item["path"])) for item in routes}
    normalized = {(item["method"], comparison_path(item["path"])) for item in routes}
    baseline_normalized = {
        (item["method"], comparison_path(item["path"])) for item in (baseline_routes or [])
    }
    rows: list[dict[str, Any]] = []
    for operation in stable:
        exact_key = (operation["method"], normalize_path(operation["path"]))
        normalized_key = (operation["method"], comparison_path(operation["path"]))
        baseline_match = normalized_key in baseline_normalized
        if baseline_match:
            category = "previously_covered"
        elif exact_key in exact:
            category = "newly_covered_from_previously_unfetched_chunk"
        elif normalized_key in normalized:
            category = "normalization_false_gap_fixed"
        else:
            category = "manifest_route_absent_from_frontend"
        similar = sorted(
            {
                (route["method"], route["path"])
                for route in routes
                if api_tail(route["path"]) == api_tail(operation["path"])
                and comparison_path(route["path"]) != comparison_path(operation["path"])
            }
        )
        rows.append(
            {
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
        )
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


def build_coverage(
    routes_document: dict[str, Any],
    operations: list[dict[str, Any]],
    baseline_routes_document: dict[str, Any] | None = None,
    reservations: list[dict[str, Any]] | None = None,
    route_classifications: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    reservations = reservations or []
    route_classifications = route_classifications or []
    stable_exact: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    stable_normalized: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    any_exact: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    path_only: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for operation in operations:
        key = (operation["method"], operation["path"])
        any_exact[key].append(operation)
        path_only[comparison_path(operation["path"])].append(operation)
        if operation["stability"] == "stable":
            stable_exact[key].append(operation)
            stable_normalized[(operation["method"], comparison_path(operation["path"]))].append(operation)
    reservation_exact: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for reservation in reservations:
        reservation_exact[(reservation["method"], reservation["path"])].append(reservation)
    classification_exact = {
        (item["method"], item["path"]): item for item in route_classifications
    }

    rows: list[dict[str, Any]] = []
    for route in routes_document.get("routes", []):
        method = str(route.get("method", "UNKNOWN")).upper()
        path = normalize_path(str(route.get("path", "")))
        exact = stable_exact.get((method, path), [])
        normalized = stable_normalized.get((method, comparison_path(path)), []) if not exact else []
        nonstable = [
            item for item in any_exact.get((method, path), []) if item["stability"] != "stable"
        ]
        reserved = reservation_exact.get((method, path), [])
        classification = classification_exact.get((method, path))
        candidates = exact or normalized or nonstable or reserved
        if exact or normalized:
            status = "covered"
            semantic_confidence = "certain"
            semantic_evidence = ["stable_manifest_exact" if exact else "stable_manifest_normalized"]
            match_kind = "exact_stable" if exact else "normalization_equivalent_stable"
        else:
            if classification:
                classification_name = str(classification["classification"])
                status = {
                    "read": "uncovered_read",
                    "write": "uncovered_write",
                    "export": "uncovered_export",
                    "auth": "uncovered_auth_or_proxy",
                    "proxy": "uncovered_auth_or_proxy",
                    "non_api": "unsupported_non_api",
                }[classification_name]
                semantic_confidence = "registered"
                semantic_evidence = [f"route_registry:{classification['reason_code']}"]
            else:
                status, semantic_confidence, semantic_evidence = classify_semantics(method, path)
            if reserved:
                match_kind = "exact_reservation"
            elif nonstable:
                match_kind = "exact_nonstable"
            elif method == "UNKNOWN" and path_only.get(comparison_path(path)):
                candidates = path_only[comparison_path(path)]
                match_kind = "path_only_method_unresolved"
            else:
                match_kind = "none"
        if exact or normalized:
            route_accounting = "covered_executable"
            callability = "executable"
        elif reserved:
            route_accounting = "accounted_blocked_write"
            callability = "contract_only"
        elif nonstable:
            stability = str(nonstable[0]["stability"])
            route_accounting = {
                "blocked_write": "accounted_blocked_write",
                "blocked_privacy": "accounted_blocked_privacy",
                "permission_unavailable": "accounted_permission_unavailable",
                "deprecated": "accounted_deprecated",
                "experimental": "accounted_experimental",
            }.get(stability, "accounted_nonstable")
            callability = "catalog_only"
        elif classification:
            route_accounting = "accounted_unsupported"
            callability = "unsupported"
        elif status == "uncovered_read":
            route_accounting = "accounted_read_candidate"
            callability = "candidate"
        elif status == "uncovered_export":
            route_accounting = "accounted_export_candidate"
            callability = "candidate"
        else:
            route_accounting = "unaccounted"
            callability = "unclassified"
        module = classify_module(path)
        platform, level = promotion_dimensions(path) if module == "推广平台" else (None, None)
        cost_tier, cost_reason, cost_confidence = estimate_read_cost(
            {
                "method": method,
                "path": path,
                "route_evidence_kinds": route.get("route_evidence_kinds", []),
            }
        )
        rows.append(
            {
                "method": method,
                "path": path,
                "status": status,
                "route_accounting": route_accounting,
                "callability": callability,
                "semantic_confidence": semantic_confidence,
                "semantic_evidence": semantic_evidence,
                "method_certainty": route.get("method_certainty", "low"),
                "method_evidence": route.get("method_evidence", []),
                "route_evidence_kinds": route.get("route_evidence_kinds", []),
                "manifest_match_kind": match_kind,
                "manifest_operations": [
                    {
                        "operation_id": item["operation_id"],
                        "stability": item["stability"],
                        "method": item["method"],
                        "path": item["path"],
                        "source_type": item.get("source_type", "manifest"),
                    }
                    for item in sorted(candidates, key=lambda item: item["operation_id"])
                ],
                "route_classification": copy.deepcopy(classification)
                if classification
                else None,
                "business_module": module,
                "promotion_platform": platform,
                "promotion_level": level,
                "occurrences": route.get("occurrences", 0),
                "raw_paths": route.get("raw_paths", []),
                "callers": route.get("callers", []),
                "ui_texts": route.get("ui_texts", []),
                "first_occurrence": route.get("first_occurrence", {}),
                "estimated_implementation_cost": cost_tier
                if status == "uncovered_read"
                else None,
                "cost_reason": cost_reason if status == "uncovered_read" else None,
                "cost_confidence": cost_confidence if status == "uncovered_read" else None,
            }
        )
    rows.sort(key=lambda item: (item["path"], item["method"]))
    contract_families = identify_contract_families(rows)
    status_counts = Counter(item["status"] for item in rows)
    accounting_counts = Counter(item["route_accounting"] for item in rows)
    callability_counts = Counter(item["callability"] for item in rows)
    unaccounted = accounting_counts["unaccounted"]
    accounted = len(rows) - unaccounted
    module_summary = []
    for module in MODULES:
        items = [item for item in rows if item["business_module"] == module]
        module_summary.append(
            {
                "module": module,
                "covered": sum(item["status"] == "covered" for item in items),
                "uncovered": sum(item["status"] != "covered" for item in items),
                "uncovered_read": sum(item["status"] == "uncovered_read" for item in items),
                "total": len(items),
            }
        )
    promotion_counter = Counter(
        (item["promotion_platform"], item["promotion_level"], item["status"])
        for item in rows
        if item["business_module"] == "推广平台"
    )
    promotion_matrix = []
    for platform in sorted({key[0] for key in promotion_counter}):
        levels = {}
        for level in PROMOTION_LEVELS:
            status_counts_for_cell = {
                status: promotion_counter[(platform, level, status)]
                for status in (
                    "covered",
                    "uncovered_read",
                    "uncovered_write",
                    "uncovered_export",
                    "uncovered_auth_or_proxy",
                    "unclassified",
                )
            }
            status_counts_for_cell["total"] = sum(status_counts_for_cell.values())
            levels[level] = status_counts_for_cell
        promotion_matrix.append({"platform": platform, "levels": levels})
    read_cost_summary = Counter(
        item["estimated_implementation_cost"]
        for item in rows
        if item["status"] == "uncovered_read"
    )
    family_covered_routes = sum(
        item["status"] == "uncovered_read" and item["contract_family"] is not None
        for item in rows
    )
    uncovered_read_total = status_counts["uncovered_read"]
    manifest_reconciliation = reconcile_stable_operations(
        operations,
        rows,
        baseline_routes_document.get("routes", []) if baseline_routes_document else None,
    )
    return {
        "schema_version": 1,
        "source": routes_document.get("source", {}),
        "manifest_summary": {
            "operations": len(operations),
            "stable_operations": sum(item["stability"] == "stable" for item in operations),
            "manifest_files": len({item["manifest_file"] for item in operations}),
        },
        "reservation_summary": {
            "blocked_write_operations": len(reservations),
            "route_classifications": len(route_classifications),
        },
        "classification_policy": {
            "status_precedence": [
                "stable manifest match -> covered",
                "exact blocked_write reservation -> accounted, contract-only",
                "exact unsupported route registry decision -> accounted, unsupported",
                "auth/proxy path token",
                "export/download path token",
                "PUT/PATCH/DELETE or explicit write action token",
                "GET/HEAD/OPTIONS or explicit read action token",
                "otherwise unclassified",
            ],
            "warning": "Accounting and callability are independent. Reservations and unsupported decisions never increase callable coverage.",
        },
        "scope_boundary": {
            "proven": "all JS reachable from the current public entry static graph was resolved while the entry HTML stayed stable",
            "not_proven": "modules delivered only after login, tenant permissions, server feature flags, or a different entry document",
            "needed_to_expand_scope": "authorized authenticated captures for each role/tenant/flag combination, followed by the same static-graph crawl and diff",
        },
        "summary": {
            "total_routes": len(rows),
            "covered": status_counts["covered"],
            "uncovered_read": status_counts["uncovered_read"],
            "uncovered_write": status_counts["uncovered_write"],
            "uncovered_export": status_counts["uncovered_export"],
            "uncovered_auth_or_proxy": status_counts["uncovered_auth_or_proxy"],
            "unclassified": status_counts["unclassified"],
            "unsupported_non_api": status_counts["unsupported_non_api"],
            "accounted": accounted,
            "callable_covered": callability_counts["executable"],
            "unaccounted": unaccounted,
            "accounting_complete": unaccounted == 0,
        },
        "accounting_summary": dict(sorted(accounting_counts.items())),
        "callability_summary": dict(sorted(callability_counts.items())),
        "module_summary": module_summary,
        "promotion_gap_matrix": promotion_matrix,
        "manifest_reconciliation": manifest_reconciliation,
        "contract_families": contract_families,
        "family_summary": {
            "families": len(contract_families),
            "uncovered_read_routes_with_family": family_covered_routes,
            "uncovered_read_routes": uncovered_read_total,
            "coverage_ratio": round(family_covered_routes / uncovered_read_total, 6)
            if uncovered_read_total
            else 0.0,
        },
        "read_cost_summary": {
            tier: read_cost_summary[tier] for tier in ("低", "中", "高")
        },
        "routes": rows,
    }


def render_report(document: dict[str, Any]) -> str:
    summary = document["summary"]
    reconciliation = document["manifest_reconciliation"]
    breakdown = reconciliation["previously_missing_breakdown"]
    lines = [
        "# Gravity frontend route coverage",
        "",
        "> Generated by `python -m gravity_sdk.census coverage`. Do not edit by hand.",
        "",
        "## Scope and certainty",
        "",
        f"- Bundle complete: `{str(document.get('source', {}).get('bundle_complete', False)).lower()}`",
        f"- Routes classified: **{summary['total_routes']}**",
        f"- Public-entry static graph boundary: {document['scope_boundary']['proven']}.",
        f"- Not proven: {document['scope_boundary']['not_proven']}.",
        "- `covered` requires a stable manifest method+path match. Read/write/export/auth labels are heuristic and carry per-route confidence.",
        "- POST is not automatically classified as write; action tokens and nearby route semantics decide it.",
        "",
        "## Coverage summary",
        "",
        "| status | routes |",
        "| --- | ---: |",
    ]
    for key in (
        "covered",
        "uncovered_read",
        "uncovered_write",
        "uncovered_export",
        "uncovered_auth_or_proxy",
        "unsupported_non_api",
        "unclassified",
    ):
        lines.append(f"| `{key}` | {summary[key]} |")
    lines.extend(
        [
            "",
            "## Route accounting vs callability",
            "",
            f"- Accounted routes: **{summary['accounted']}**",
            f"- Callable covered routes: **{summary['callable_covered']}**",
            f"- Unaccounted routes: **{summary['unaccounted']}**",
            "",
            "| accounting state | routes |",
            "| --- | ---: |",
        ]
    )
    for key, value in document["accounting_summary"].items():
        lines.append(f"| `{key}` | {value} |")
    lines.extend(["", "| callability | routes |", "| --- | ---: |"])
    for key, value in document["callability_summary"].items():
        lines.append(f"| `{key}` | {value} |")
    lines.extend(
        [
            "",
            "## Stable manifest reconciliation",
            "",
            "| category | stable operations |",
            "| --- | ---: |",
            f"| Previously covered | {reconciliation['summary'].get('previously_covered', 0)} |",
            f"| (a) Found in previously unfetched chunks | {breakdown['a_previously_unfetched_chunk']} |",
            f"| (b) Normalization false gap fixed | {breakdown['b_normalization_false_gap_fixed']} |",
            f"| (c) Manifest route absent from frontend | {breakdown['c_manifest_route_absent_from_frontend']} |",
            "",
            "### Manifest routes absent from frontend",
            "",
            "| operation | method | manifest path | similar frontend routes |",
            "| --- | --- | --- | --- |",
        ]
    )
    for item in reconciliation["operations"]:
        if item["category"] != "manifest_route_absent_from_frontend":
            continue
        similar = "; ".join(
            f"{candidate['method']} {candidate['path']}"
            for candidate in item["similar_frontend_routes"]
        ) or "None"
        lines.append(
            f"| `{item['operation_id']}` | `{item['method']}` | `{item['path']}` | `{similar}` |"
        )
    lines.extend(
        [
            "",
            "## Business module read gaps",
            "",
            "| module | covered | uncovered read | all uncovered | total |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for item in document["module_summary"]:
        lines.append(
            f"| {item['module']} | {item['covered']} | {item['uncovered_read']} | {item['uncovered']} | {item['total']} |"
        )
    lines.extend(
        [
            "",
            "## Promotion platform x level uncovered reads",
            "",
            "| platform | 账户 | 项目 | 计划 | 广告组 | 广告/创意 | 素材 | 报表 | 其它 | total |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for item in document["promotion_gap_matrix"]:
        values = [item["levels"][level]["uncovered_read"] for level in PROMOTION_LEVELS]
        lines.append(
            f"| {item['platform']} | " + " | ".join(str(value) for value in values) + f" | {sum(values)} |"
        )
    family_summary = document["family_summary"]
    lines.extend(
        [
            "",
            "## Contract families",
            "",
            f"- Families: **{family_summary['families']}**",
            f"- Uncovered reads assigned to a family: **{family_summary['uncovered_read_routes_with_family']} / {family_summary['uncovered_read_routes']} ({family_summary['coverage_ratio']:.1%})**",
            "",
            "| family | kind | members | signature |",
            "| --- | --- | ---: | --- |",
        ]
    )
    for family in document["contract_families"]:
        signature = family["signature"].replace("|", "\\|")
        lines.append(
            f"| `{family['family_id']}` | `{family['family_kind']}` | {family['member_count']} | `{signature}` |"
        )
    costs = document["read_cost_summary"]
    lines.extend(
        [
            "",
            "## Estimated implementation cost",
            "",
            "| tier | uncovered reads | rule |",
            "| --- | ---: | --- |",
            f"| 低 | {costs['低']} | Flat list/detail with no evident parent dependency |",
            f"| 中 | {costs['中']} | Parent-resource dependency or structured selector |",
            f"| 高 | {costs['高']} | Complex query/report body, proxy envelope, or dynamic path |",
            "",
            "Cost is a scheduling heuristic, not an observed implementation duration.",
        ]
    )
    by_module: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in document["routes"]:
        if item["status"] == "uncovered_read":
            by_module[item["business_module"]].append(item)
    lines.extend(["", "## Complete uncovered read route list", ""])
    for module in MODULES:
        items = by_module[module]
        lines.extend([f"### {module} ({len(items)})", ""])
        if not items:
            lines.extend(["None.", ""])
            continue
        lines.extend(
            [
                "| confidence | method | path | family | cost |",
                "| --- | --- | --- | --- | --- |",
            ]
        )
        for item in items:
            escaped = item["path"].replace("|", "\\|")
            family = item["contract_family"]["family_id"] if item["contract_family"] else "singleton"
            lines.append(
                f"| `{item['semantic_confidence']}` | `{item['method']}` | `{escaped}` | `{family}` | `{item['estimated_implementation_cost']}` |"
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def coverage_files(
    routes_path: Path,
    manifest_dir: Path,
    output_path: Path,
    report_path: Path,
    baseline_routes_path: Path | None = None,
    reservation_dir: Path | None = None,
    route_registry_path: Path | None = None,
) -> dict[str, Any]:
    contract_root = manifest_dir.parent / "contracts"
    selected_reservation_dir = reservation_dir or contract_root / "reservations"
    selected_registry_path = route_registry_path or contract_root / "routes" / "registry.json"
    document = build_coverage(
        read_json(routes_path),
        load_manifest_operations(manifest_dir),
        read_json(baseline_routes_path) if baseline_routes_path else None,
        load_write_reservations(selected_reservation_dir),
        load_route_classifications(selected_registry_path),
    )
    write_json(output_path, document)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_report(document), encoding="utf-8", newline="\n")
    return document
