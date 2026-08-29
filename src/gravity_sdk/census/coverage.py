from __future__ import annotations

import copy
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

from gravity_sdk.prober.read_semantics import confirmation_keys

from .io import read_json, render_coverage_report as _render_report, write_json
from .normalize import comparison_path, normalize_path
from .semantics import (
    PLATFORMS,
    classify_route_accounting,
    classify_route_semantics,
    classify_semantics,
    identify_contract_families,
    reconcile_stable_operations,
)


MODULES = ("分析", "推广平台", "资产", "素材", "报表", "App 与账号", "归因", "元数据", "其它")
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


def _coverage_indexes(
    operations: list[dict[str, Any]],
    reservations: list[dict[str, Any]],
    route_classifications: list[dict[str, Any]],
) -> dict[str, Any]:
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
    return {
        "stable_exact": stable_exact,
        "stable_normalized": stable_normalized,
        "any_exact": any_exact,
        "path_only": path_only,
        "reservation_exact": reservation_exact,
        "classification_exact": {
            (item["method"], item["path"]): item for item in route_classifications
        },
    }


def _route_match(
    route: dict[str, Any], indexes: dict[str, Any], confirmed_reads: set[tuple[str, str]]
) -> dict[str, Any]:
    method = str(route.get("method", "UNKNOWN")).upper()
    path = normalize_path(str(route.get("path", "")))
    key = (method, path)
    exact = indexes["stable_exact"].get(key, [])
    normalized = indexes["stable_normalized"].get((method, comparison_path(path)), []) if not exact else []
    nonstable = [item for item in indexes["any_exact"].get(key, []) if item["stability"] != "stable"]
    reserved = indexes["reservation_exact"].get(key, [])
    classification = indexes["classification_exact"].get(key)
    candidates = exact or normalized or nonstable or reserved
    if exact or normalized:
        status = "covered"
        confidence = "certain"
        evidence = ["stable_manifest_exact" if exact else "stable_manifest_normalized"]
        match_kind = "exact_stable" if exact else "normalization_equivalent_stable"
    else:
        status, confidence, evidence = classify_route_semantics(
            method, path, classification, confirmed_reads
        )
        if reserved:
            match_kind = "exact_reservation"
        elif nonstable:
            match_kind = "exact_nonstable"
        elif method == "UNKNOWN" and indexes["path_only"].get(comparison_path(path)):
            candidates = indexes["path_only"][comparison_path(path)]
            match_kind = "path_only_method_unresolved"
        else:
            match_kind = "none"
    return {
        "method": method, "path": path, "exact": exact, "normalized": normalized,
        "nonstable": nonstable, "reserved": reserved, "classification": classification,
        "candidates": candidates, "status": status, "confidence": confidence,
        "evidence": evidence, "match_kind": match_kind,
    }


def _manifest_matches(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "operation_id": item["operation_id"], "stability": item["stability"],
            "method": item["method"], "path": item["path"],
            "source_type": item.get("source_type", "manifest"),
        }
        for item in sorted(candidates, key=lambda item: item["operation_id"])
    ]


def _coverage_route(
    route: dict[str, Any], indexes: dict[str, Any], confirmed_reads: set[tuple[str, str]]
) -> dict[str, Any]:
    match = _route_match(route, indexes, confirmed_reads)
    status = match["status"]
    accounting, callability = classify_route_accounting(
        covered=bool(match["exact"] or match["normalized"]),
        reserved=bool(match["reserved"]),
        nonstable_stability=str(match["nonstable"][0]["stability"]) if match["nonstable"] else None,
        registered=bool(match["classification"]),
        status=status,
    )
    path = match["path"]
    module = classify_module(path)
    platform, level = promotion_dimensions(path) if module == "推广平台" else (None, None)
    cost_tier, cost_reason, cost_confidence = estimate_read_cost(
        {"method": match["method"], "path": path,
         "route_evidence_kinds": route.get("route_evidence_kinds", [])}
    )
    return {
        "method": match["method"], "path": path, "status": status,
        "route_accounting": accounting, "callability": callability,
        "semantic_confidence": match["confidence"], "semantic_evidence": match["evidence"],
        "method_certainty": route.get("method_certainty", "low"),
        "method_evidence": route.get("method_evidence", []),
        "route_evidence_kinds": route.get("route_evidence_kinds", []),
        "manifest_match_kind": match["match_kind"],
        "manifest_operations": _manifest_matches(match["candidates"]),
        "route_classification": copy.deepcopy(match["classification"]) if match["classification"] else None,
        "business_module": module, "promotion_platform": platform, "promotion_level": level,
        "occurrences": route.get("occurrences", 0), "raw_paths": route.get("raw_paths", []),
        "callers": route.get("callers", []), "ui_texts": route.get("ui_texts", []),
        "first_occurrence": route.get("first_occurrence", {}),
        "estimated_implementation_cost": cost_tier if status == "uncovered_read" else None,
        "cost_reason": cost_reason if status == "uncovered_read" else None,
        "cost_confidence": cost_confidence if status == "uncovered_read" else None,
    }


def _module_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for module in MODULES:
        items = [item for item in rows if item["business_module"] == module]
        statuses = Counter(item["status"] for item in items)
        result.append({
            "module": module, "covered": statuses["covered"],
            "uncovered": len(items) - statuses["covered"],
            "uncovered_read": statuses["uncovered_read"], "total": len(items),
        })
    return result


def _promotion_matrix(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counter = Counter(
        (item["promotion_platform"], item["promotion_level"], item["status"])
        for item in rows if item["business_module"] == "推广平台"
    )
    statuses = (
        "covered", "uncovered_read", "uncovered_write", "uncovered_export",
        "uncovered_auth_or_proxy", "static_read_candidate", "unsafe_unknown", "unclassified",
    )
    result = []
    for platform in sorted({key[0] for key in counter}):
        levels = {}
        for level in PROMOTION_LEVELS:
            cell = {status: counter[(platform, level, status)] for status in statuses}
            cell["total"] = sum(cell.values())
            levels[level] = cell
        result.append({"platform": platform, "levels": levels})
    return result


def _coverage_document(
    routes_document: dict[str, Any],
    operations: list[dict[str, Any]],
    reservations: list[dict[str, Any]],
    route_classifications: list[dict[str, Any]],
    baseline_routes_document: dict[str, Any] | None,
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    contract_families = identify_contract_families(rows)
    status_counts = Counter(item["status"] for item in rows)
    accounting_counts = Counter(item["route_accounting"] for item in rows)
    callability_counts = Counter(item["callability"] for item in rows)
    unaccounted = accounting_counts["unaccounted"]
    read_costs = Counter(
        item["estimated_implementation_cost"] for item in rows if item["status"] == "uncovered_read"
    )
    family_covered = sum(
        item["status"] == "uncovered_read" and item["contract_family"] is not None for item in rows
    )
    uncovered_reads = status_counts["uncovered_read"]
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
                "auth/proxy path token", "export/download path token",
                "PUT/PATCH/DELETE or explicit write action token",
                "GET/HEAD/OPTIONS, or exact reviewed POST read confirmation",
                "unknown method plus a read signal -> static read candidate",
                "unconfirmed POST plus a read signal -> unsafe unknown", "otherwise unclassified",
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
            **{status: status_counts[status] for status in (
                "covered", "uncovered_read", "uncovered_write", "uncovered_export",
                "uncovered_auth_or_proxy", "static_read_candidate", "unsafe_unknown",
                "unclassified", "unsupported_non_api",
            )},
            "accounted": len(rows) - unaccounted,
            "callable_covered": callability_counts["executable"],
            "unaccounted": unaccounted, "accounting_complete": unaccounted == 0,
        },
        "accounting_summary": dict(sorted(accounting_counts.items())),
        "callability_summary": dict(sorted(callability_counts.items())),
        "module_summary": _module_summary(rows),
        "promotion_gap_matrix": _promotion_matrix(rows),
        "manifest_reconciliation": reconcile_stable_operations(
            operations, rows,
            baseline_routes_document.get("routes", []) if baseline_routes_document else None,
            normalize_path=normalize_path, comparison_path=comparison_path,
        ),
        "contract_families": contract_families,
        "family_summary": {
            "families": len(contract_families),
            "uncovered_read_routes_with_family": family_covered,
            "uncovered_read_routes": uncovered_reads,
            "coverage_ratio": round(family_covered / uncovered_reads, 6) if uncovered_reads else 0.0,
        },
        "read_cost_summary": {tier: read_costs[tier] for tier in ("低", "中", "高")},
        "routes": rows,
    }


def build_coverage(
    routes_document: dict[str, Any],
    operations: list[dict[str, Any]],
    baseline_routes_document: dict[str, Any] | None = None,
    reservations: list[dict[str, Any]] | None = None,
    route_classifications: list[dict[str, Any]] | None = None,
    confirmed_read_routes: set[tuple[str, str]] | None = None,
) -> dict[str, Any]:
    reservations = reservations or []
    route_classifications = route_classifications or []
    confirmed_read_routes = confirmed_read_routes or set()
    indexes = _coverage_indexes(operations, reservations, route_classifications)
    rows = [
        _coverage_route(route, indexes, confirmed_read_routes)
        for route in routes_document.get("routes", [])
    ]
    rows.sort(key=lambda item: (item["path"], item["method"]))
    return _coverage_document(
        routes_document, operations, reservations, route_classifications,
        baseline_routes_document, rows,
    )


def render_report(document: dict[str, Any]) -> str:
    return _render_report(document, MODULES, PROMOTION_LEVELS)


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
    confirmations_path = contract_root / "routes" / "probe-read-confirmations.json"
    confirmed_read_routes = (
        confirmation_keys(confirmations_path) if confirmations_path.is_file() else set()
    )
    document = build_coverage(
        read_json(routes_path),
        load_manifest_operations(manifest_dir),
        read_json(baseline_routes_path) if baseline_routes_path else None,
        load_write_reservations(selected_reservation_dir),
        load_route_classifications(selected_registry_path),
        confirmed_read_routes,
    )
    write_json(output_path, document)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_report(document), encoding="utf-8", newline="\n")
    return document
