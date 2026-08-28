"""Generate conservative, non-executable contracts from census evidence."""

from __future__ import annotations

import copy
import hashlib
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

from .core import (
    CONTRACT_ROOT, COVERAGE_PATH, DRAFT_ROOT, OPERATION_ROOT, REPO_ROOT,
    canonical_fingerprint, display_path, now_utc, read_json, write_json,
)


PLATFORMS = frozenset(
    {
        "alipay", "apple", "baidu", "bilibili", "bing", "bytedance", "honor",
        "huawei", "huya", "iqiyi", "kuaishou", "oppo", "qihu360", "sigmob",
        "taptap", "tencent", "ubix", "uc", "vivo", "wechat_video", "weibo",
        "xiaohongshu", "xiaomi", "youdao",
    }
)

DEFAULT_REDACT_FIELDS = [
    "authorization", "access_token", "token", "cookie", "password", "secret",
    "refresh_token", "session_token", "operator", "operator_id", "operator_name",
    "creator", "creator_id", "user_name", "dept", "department", "callback_url",
    "click_url", "postback_url", "uid", "user_id", "device_id", "phone",
    "mobile", "email", "idfa", "idfv", "imei", "oaid", "android_id", "order_id",
    "ip", "ip_address", "openid", "open_id", "unionid", "client_id", "trace_id",
]

TARGET_MANIFESTS = {
    "analysis": "analysis.json", "material": "other.json",
    "promotion": "promotion.json", "report": "report.json",
}

BULK_REPORT_ROOT = REPO_ROOT / "tmp" / "codex" / "gi-bulk-draft"

DOMAIN_BY_MODULE = {
    "App 与账号": "app",
    "元数据": "metadata",
    "分析": "analysis",
    "归因": "attribution",
    "报表": "report",
    "推广平台": "promotion",
    "素材": "material",
    "资产": "material",
}

RESERVATION_ROOT = CONTRACT_ROOT / "reservations"
ROUTE_REGISTRY_PATH = CONTRACT_ROOT / "routes" / "registry.json"
WRITE_REPORT_ROOT = REPO_ROOT / "tmp" / "codex" / "gi-write-registry"

_NON_API_UNCLASSIFIED_PATHS = frozenset(
    {
        "/event_center/api/v1/openapi/",
        "/open_api/v3.0/tools/micro_${e===De.DouyinMiniGame",
        "/open_api/v3.0/tools/micro_${e===je.DouyinMiniGame",
        "/turbo_engine/api/v2/",
        "/turbo_engine/api/v2/material",
        "/turbo_engine/api/v2/report",
    }
)

_READ_UNCLASSIFIED_PATHS = frozenset(
    {
        "/apprank/api/v1/rank/competition_trends/",
        "/open_api/2/dpa/product/availables/",
        "/open_api/2/tools/interest_action/id2word/",
        "/open_api/2/tools/interest_action/keyword/suggest/",
        "/open_api/2/tools/interest_action/{toLowerCase}/category/",
        "/open_api/2/tools/interest_action/{toLowerCase}/keyword/",
        "/open_api/launch/cpc/meta_data/account/brand_info",
        "/open_api/launch/cpc/meta_data/corp/mid",
        "/open_api/launch/cpc/meta_data/launch/wechat/mini_game",
        "/open_api/launch/cpc/meta_data/resource/app/drop_box",
        "/open_api/launch/cpc/meta_data/resource/biligame_list",
        "/open_api/launch/cpc/meta_data/resource/business_category",
        "/open_api/launch/cpc/meta_data/v2/comment_conversion_component/mgk_page",
        "/open_api/launch/cpc/meta_data/v2/story/component/button",
        "/open_api/v3.0/sugg_words/",
        "/openapi/api/v1/material/id_map/",
        "/turbo_engine/api/v1/bytedance/std/project/material_report/",
        "/turbo_engine/api/v1/bytedance/video/async/num/",
        "/turbo_engine/api/v1/tencent/asset/monitor/distinct/",
        "/turbo_engine/api/v1/tencent/asset/monitor/used/",
        "/turbo_engine/api/v1/user/device_white/testing_tool/attribution_history/",
        "/turbo_engine/api/v1/user/device_white/testing_tool/attribution_query/",
    }
)

_ACTION_TOKENS = frozenset(
    {
        "add", "append", "approve", "async", "batch", "bind", "cancel",
        "change", "clear", "clone", "collect", "copy", "create", "debug",
        "delete", "disable", "distinct", "dl", "edit",
        "enable", "execute", "generate", "import", "kill", "manage", "mark",
        "modify", "move", "opt", "override", "push", "register", "remove", "rename",
        "reset", "restore", "save", "send", "set", "share", "start", "stop",
        "submit", "sync", "terminate", "transfer", "unbind", "undelete",
        "unbinding", "update", "upload", "use",
    }
)

_MUTATION_KIND_RULES = (
    ("delete", frozenset({"clear", "kill", "terminate", "delete", "remove", "dl"})),
    ("approve", frozenset({"approve", "audit", "examine", "review"})),
    ("upload", frozenset({"upload"})),
    ("import", frozenset({"import"})),
    ("sync", frozenset({"sync", "async", "handsel"})),
    ("state_change", frozenset({"enable", "disable", "start", "stop", "cancel", "switch", "status", "change"})),
    ("bind", frozenset({"bind", "unbind", "binding", "unbinding", "auth2user"})),
    ("copy", frozenset({"copy", "clone"})),
    ("move", frozenset({"move", "transfer"})),
    ("share", frozenset({"share"})),
    ("execute", frozenset({"submit", "execute", "push", "send", "test", "debug"})),
    ("create", frozenset({"create", "add", "append", "register", "generate"})),
    ("update", frozenset({
        "update", "edit", "modify", "save", "manage", "setting", "config",
        "set", "reset", "rename", "opt", "override", "collect", "distinct",
        "mark", "use", "undelete", "restore",
    })),
)


def existing_operations(operation_root: Path) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    if not operation_root.is_dir():
        return result
    for path in sorted(operation_root.glob("*.json")):
        source = read_json(path)
        operation = source.get("operation") if isinstance(source, Mapping) else None
        if isinstance(operation, Mapping) and isinstance(operation.get("operation_id"), str):
            result[str(operation["operation_id"])] = source
    return result


def route_family_id(route: Mapping[str, Any]) -> str | None:
    family = route.get("contract_family")
    if isinstance(family, Mapping) and isinstance(family.get("family_id"), str):
        return str(family["family_id"])
    if isinstance(family, str):
        return family
    return None


def select_routes(
    coverage: Mapping[str, Any], *, paths: Sequence[str] = (),
    families: Sequence[str] = (), business_modules: Sequence[str] = (),
    costs: Sequence[str] = (), method_certainty: str | None = "high",
    limit: int = 12, all_uncovered: bool = False,
) -> list[Mapping[str, Any]]:
    routes = coverage.get("routes")
    if not isinstance(routes, list):
        raise ValueError("coverage.json has no routes array")
    if not all_uncovered and not any((paths, families, business_modules, costs)):
        raise ValueError("draft requires at least one path, family, module, or cost filter")
    path_set, family_set = set(paths), set(families)
    module_set, cost_set = set(business_modules), set(costs)
    selected: list[Mapping[str, Any]] = []
    for route in routes:
        if not isinstance(route, Mapping) or route.get("status") != "uncovered_read":
            continue
        if _route_matches(
            route, path_set=path_set, family_set=family_set,
            module_set=module_set, cost_set=cost_set,
            method_certainty=method_certainty,
        ):
            selected.append(route)
    selected.sort(key=lambda item: (str(item.get("path", "")), str(item.get("method", ""))))
    if len(selected) > limit:
        raise ValueError(f"route selection produced {len(selected)} entries; limit is {limit}")
    missing_paths = path_set - {str(item.get("path")) for item in selected}
    if missing_paths:
        raise ValueError(
            "selected paths are not high-certainty uncovered reads: "
            + ", ".join(sorted(missing_paths))
        )
    return selected


def _route_matches(
    route: Mapping[str, Any], *, path_set: set[str], family_set: set[str],
    module_set: set[str], cost_set: set[str], method_certainty: str | None,
) -> bool:
    return (
        (not path_set or route.get("path") in path_set)
        and (not family_set or route_family_id(route) in family_set)
        and (not module_set or route.get("business_module") in module_set)
        and (not cost_set or route.get("estimated_implementation_cost") in cost_set)
        and (not method_certainty or route.get("method_certainty") == method_certainty)
        and str(route.get("method", "")).upper() in {"GET", "POST"}
    )


def _platform_from_route(route: Mapping[str, Any]) -> str | None:
    platform = route.get("promotion_platform")
    if isinstance(platform, str) and platform and platform not in {"通用/未知", "unknown"}:
        return platform
    segments = [item for item in str(route.get("path", "")).split("/") if item]
    for index, segment in enumerate(segments):
        if segment == "huawei" and index + 1 < len(segments) and segments[index + 1] == "store":
            return "huawei_store"
        if segment in PLATFORMS:
            return segment
    return None


def _path_segments(path: str) -> list[str]:
    return [item for item in path.split("/") if item]


def _semantic_segments(path: str) -> tuple[str, list[str]]:
    segments = _path_segments(path)
    service = segments[0] if segments else "unknown"
    for index, segment in enumerate(segments):
        if segment == "api" and index + 1 < len(segments):
            version = segments[index + 1]
            if re.fullmatch(r"v\d+", version):
                return service, segments[index + 2 :]
    return service, segments


def _domain_from_route(route: Mapping[str, Any], platform: str | None) -> str:
    module = str(route.get("business_module", ""))
    path = str(route.get("path", ""))
    if path.startswith("/openapi/api/"):
        openapi_domain = _openapi_domain(path)
        if openapi_domain is not None:
            return openapi_domain
    if module in DOMAIN_BY_MODULE:
        domain = DOMAIN_BY_MODULE[module]
        if domain == "promotion" and any(
            token in path
            for token in ("/const/", "/health_status/", "/company_config/")
        ):
            return "metadata"
        return domain
    if path.startswith("/apprank/api/"):
        return "app"
    if path.startswith("/openapi/api/"):
        return "candidate"
    path_domain = _path_domain(path)
    if path_domain is not None:
        return path_domain
    if platform:
        return "promotion"
    return "unknown"


def _openapi_domain(path: str) -> str | None:
    _, segments = _semantic_segments(path)
    if "open_develop" in segments:
        return "developer"
    if "promoted_object" in segments:
        return "promotion"
    if segments and segments[0] == "report":
        return "report"
    return None


def _path_domain(path: str) -> str | None:
    rules = (
        (("/health_status/", "/base/company_config/"), "metadata"),
        (("/common/media_report/", "/monetization/", "/subscribe/"), "report"),
        (("/event/",), "analysis"),
        (("/portal/", "/oplog/"), "account"),
        (("/common/", "/media/", "/task/"), "promotion"),
    )
    return next(
        (domain for tokens, domain in rules if any(token in path for token in tokens)),
        None,
    )


def _normal_token(value: str) -> str:
    from .parameter_types import normal_route_token

    return normal_route_token(value)


def _suffix_list_resource(tail: str, values: Sequence[str]) -> str:
    prefix = tail[: -len("_list")]
    if prefix in {"public", "info", "user"} and len(values) > 1:
        return _normal_token(values[-2]) + "_" + prefix
    return prefix or "unknown"


def _resource_fallback(
    route: Mapping[str, Any], values: Sequence[str], tail: str, method: str,
) -> tuple[str, str]:
    report_resources = {
        "account", "adcreative", "adgroup", "campaign", "creative",
        "keyword", "plan", "unit",
    }
    if "report" in values and tail in report_resources:
        return tail, "list"
    if method == "GET":
        return tail, "get"
    if "read_action_path_token" in route.get("semantic_evidence", []):
        return tail, "query"
    return "unknown", "unknown"


def _resource_action(
    route: Mapping[str, Any], segments: Sequence[str], *, domain: str,
) -> tuple[str, str]:
    from .parameter_types import resource_action_rule

    if not segments:
        return "unknown", "unknown"
    values = list(segments)
    while values and re.fullmatch(r"v\d+", values[-1]):
        values.pop()
    if not values:
        return "unknown", "unknown"
    tail = _normal_token(values[-1])
    method = str(route.get("method", "")).upper()
    if method == "POST" and tail in {"manage", "set"}:
        return "unknown", "unknown"
    resolved = resource_action_rule(tail, values, domain)
    if resolved is not None:
        return resolved
    if tail.endswith("_list"):
        return _suffix_list_resource(tail, values), "list"
    return _resource_fallback(route, values, tail, method)


def _resource_context(
    route: Mapping[str, Any], segments: Sequence[str], platform: str | None,
) -> str:
    values = [_normal_token(item) for item in segments if not item.startswith("{")]
    values = [item for item in values if item]
    trailing_versions: list[str] = []
    while values and re.fullmatch(r"v\d+", values[-1]):
        trailing_versions.insert(0, values.pop())
    tail_markers = {
        "list", "public_list", "detail", "info", "get", "query", "report",
        "tree", "whole_tree", "calc_total",
    }
    if values and values[-1] in tail_markers:
        values.pop()
    values.extend(trailing_versions)
    service, _ = _semantic_segments(str(route.get("path", "")))
    if service != "turbo_engine":
        values.insert(0, _normal_token(service))
    return "_".join(values)


def infer_identity(route: Mapping[str, Any]) -> dict[str, Any]:
    path = str(route.get("path", ""))
    _, segments = _semantic_segments(path)
    platform = _platform_from_route(route)
    domain = _domain_from_route(route, platform)
    resource, action = _resource_action(route, segments, domain=domain)
    if domain == "developer" and resource == "open_develop":
        resource = "application"
    if resource == "metrics":
        resource = "metric"
    if "const" in segments and "promotion" in segments and resource == "gravity_metric":
        resource = "promotion_gravity_metric"
    if domain == "promotion" and platform:
        operation_id = f"promotion.{platform}.{resource}.{action}"
    elif domain != "unknown":
        operation_id = f"{domain}.{resource}.{action}"
    else:
        route_hash = hashlib.sha256(f"{route.get('method')} {path}".encode()).hexdigest()[:10]
        operation_id = f"unknown.route_{route_hash}.read"
    return {
        "operation_id": operation_id, "domain": domain, "resource": resource,
        "action": action, "platform": platform,
        "resource_context": _resource_context(route, segments, platform),
    }


def _infer_contract_parts(
    route: Mapping[str, Any], identity: Mapping[str, Any], existing_ids: set[str],
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    from .parameter_types import infer_contract_parts

    return infer_contract_parts(route, identity, existing_ids)


def _auth_profile(path: str) -> str:
    from .parameter_types import auth_profile

    return auth_profile(path)


def _initial_gate_missing(path: str, auth_profile: str) -> list[str]:
    from .parameter_types import initial_gate_missing

    return initial_gate_missing(path, auth_profile)


def _route_evidence(route: Mapping[str, Any]) -> dict[str, Any]:
    allowed = (
        "method_certainty", "estimated_implementation_cost", "contract_family",
        "business_module", "callers", "first_occurrence", "method_evidence", "ui_texts",
        "cost_reason", "semantic_confidence", "semantic_evidence", "method", "path",
        "promotion_level", "promotion_platform", "status",
    )
    return {key: copy.deepcopy(route.get(key)) for key in allowed if key in route}


def _coverage_reference(
    route: Mapping[str, Any], *, coverage_path: Path, route_index: int,
) -> dict[str, Any]:
    return {
        "coverage_path": display_path(coverage_path),
        "route_index": route_index,
        "json_pointer": f"/routes/{route_index}",
        "method": str(route.get("method", "")).upper(),
        "path": str(route.get("path", "")),
        "route_sha256": canonical_fingerprint(route),
    }


def _blocker(code: str, detail: str, evidence: str | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {"code": code, "status": "open", "detail": detail}
    if evidence:
        result["evidence"] = evidence
    return result


def _probe_evidence_blockers(
    latest: Mapping[str, Any] | None, latest_path: str | None,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    if not isinstance(latest, Mapping):
        return [
            _blocker("not_probed", "No live probe evidence exists for this route."),
            _blocker(
                "request_binding_unverified",
                "Query/body fields and fixed request values have not been observed.",
            ),
        ]
    conclusion = str(latest.get("conclusion", ""))
    if conclusion in {"inconclusive_empty", "available_empty"}:
        result.append(_blocker(
            "empty_sample",
            "The observed tenant response was empty and cannot prove an item schema.",
            latest_path,
        ))
    elif conclusion == "semantic_error":
        result.append(_blocker(
            "request_parameters_required",
            "The observed request reached a semantic error; required request fields remain unknown.",
            latest_path,
        ))
    elif not bool(latest.get("successful")):
        result.append(_blocker(
            "probe_inconclusive",
            "The latest probe did not satisfy the promotion gate.",
            latest_path,
        ))
    return result


def _parent_binding_blocker(
    *, indicated: bool, resolved: bool, resolution: Any,
    latest_path: str | None,
) -> dict[str, Any] | None:
    if not indicated or resolved:
        return None
    detail = "A parent account/campaign selector is indicated, but its binding and cardinality require proof."
    evidence = latest_path
    if isinstance(resolution, Mapping):
        detail = str(resolution.get("detail") or detail)
        evidence = str(resolution.get("evidence")) if resolution.get("evidence") else latest_path
    return _blocker("parent_resource_required", detail, evidence)


def _parent_data_blocker(
    conclusion: str, resolution: Any, latest_path: str | None,
) -> dict[str, Any] | None:
    if conclusion != "blocked_by_data" or not isinstance(resolution, Mapping):
        return None
    replacement = str(resolution.get("replacement_blocker", "empty_sample"))
    if replacement not in {"empty_sample", "permission_unavailable"}:
        replacement = "empty_sample"
    details = {
        "empty_sample": "The proven parent operation returned no selectable parent resource for this tenant.",
        "permission_unavailable": "The proven parent operation is unavailable to the current account.",
    }
    return _blocker(
        replacement, details[replacement],
        str(resolution.get("evidence") or latest_path or ""),
    )


def _parent_resource_blockers(
    operation: Mapping[str, Any], route: Mapping[str, Any] | None,
    latest: Mapping[str, Any] | None, latest_path: str | None,
) -> list[dict[str, Any]]:
    cost_reason = str((route or {}).get("cost_reason", ""))
    indicated = bool(
        operation.get("required_parent", [])
        or "depends on a parent" in cost_reason
        or "requires a parent" in cost_reason
    )
    resolution = (route or {}).get("parent_resolution", {})
    conclusion = str(resolution.get("conclusion", "")) if isinstance(resolution, Mapping) else ""
    resolved = bool(latest and latest.get("parent_resolved") is True)
    resolved = resolved or conclusion in {"unblocked", "blocked_by_data"}
    result = [
        blocker for blocker in (
            _parent_binding_blocker(
                indicated=indicated, resolved=resolved,
                resolution=resolution, latest_path=latest_path,
            ),
            _parent_data_blocker(conclusion, resolution, latest_path),
        )
        if blocker is not None
    ]
    return result


def _response_policy_blockers(
    operation: Mapping[str, Any], draft: Mapping[str, Any], latest_path: str | None,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    manual_fields = draft.get("manual_review_fields", []) if isinstance(draft, Mapping) else []
    if manual_fields:
        result.append(
            _blocker(
                "field_review_required",
                f"{len(manual_fields)} observed response field(s) still require human privacy review.",
                latest_path,
            )
        )
    projection = operation.get("response_projection", {})
    exposed = set()
    if isinstance(projection, Mapping):
        exposed = set(projection.get("item_keys", []))
        exposed.update(projection.get("data_scalar_list_types", {}))
        exposed.update(set(projection.get("data_keys", [])) - {"list", "page_info"})
    if not exposed:
        result.append(
            _blocker(
                "response_schema_unverified",
                "No response field is approved for exposure; response shape and item types remain unverified.",
                latest_path,
            )
        )
    privacy = operation.get("privacy_policy", {})
    if isinstance(privacy, Mapping) and privacy.get("classification") == "unverified":
        result.append(
            _blocker(
                "privacy_classification_unverified",
                "The route-level privacy classification has not been established.",
            )
        )
    return result


def _request_contract_blockers(
    operation: Mapping[str, Any], latest: Mapping[str, Any] | None,
    latest_path: str | None,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    pagination = operation.get("pagination", {})
    pagination_kind = pagination.get("kind") if isinstance(pagination, Mapping) else None
    pagination_verified = bool(
        isinstance(latest, Mapping) and latest.get("pagination_verified") is True
    )
    if pagination_kind == "unverified" or (
        pagination_kind not in {None, "none"} and not pagination_verified
    ):
        result.append(
            _blocker(
                "pagination_unverified",
                "Pagination kind, field names, and limits have not been observed.",
                latest_path,
            )
        )
    fields = operation.get("input_fields", {})
    request = operation.get("request", {})
    path_fields = request.get("path_fields", []) if isinstance(request, Mapping) else []
    if isinstance(fields, Mapping) and any(
        isinstance(fields.get(name), Mapping) and fields[name].get("type") == "any"
        for name in path_fields
    ):
        result.append(
            _blocker(
                "path_parameter_type_unverified",
                "A path placeholder is proven syntactically, but its value type and semantics are unknown.",
            )
        )
    return result


def _openapi_contract_blockers(
    operation: Mapping[str, Any],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    path_template = str(operation.get("path_template", ""))
    if path_template.startswith("/openapi/"):
        result.append(
            _blocker(
                "stable_runtime_route_unsupported",
                "The stable runtime does not expose OpenAPI draft routes.",
            )
        )
    if operation.get("auth_profile") == "gravity_openapi_signature":
        result.append(
            _blocker(
                "openapi_developer_credentials_unavailable",
                "OpenAPI developer signing credentials are unavailable to the stable runtime.",
            )
        )
    return result


def structured_blockers(
    source: Mapping[str, Any], route: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    operation_value = source.get("operation", {})
    draft_value = source.get("draft", {})
    operation = operation_value if isinstance(operation_value, Mapping) else {}
    draft = draft_value if isinstance(draft_value, Mapping) else {}
    evidence = draft.get("probe_evidence", [])
    latest_value = evidence[-1] if isinstance(evidence, list) and evidence else None
    latest = latest_value if isinstance(latest_value, Mapping) else None
    latest_path = str(latest.get("path", "")) if latest is not None else None
    result = _probe_evidence_blockers(latest, latest_path)
    result.extend(_parent_resource_blockers(operation, route, latest, latest_path))
    result.extend(_response_policy_blockers(operation, draft, latest_path))
    result.extend(_request_contract_blockers(operation, latest, latest_path))
    result.extend(_openapi_contract_blockers(operation))
    if not result:
        result.append(
            _blocker(
                "promotion_pending",
                "Probe gates are satisfied, but this contract remains an explicit draft until reviewed and promoted.",
            )
        )
    deduplicated = {item["code"]: item for item in result}
    return [deduplicated[code] for code in sorted(deduplicated)]


def refresh_structured_blockers(
    source: Mapping[str, Any], route: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    updated = copy.deepcopy(dict(source))
    blockers = structured_blockers(updated, route)
    blocking_codes = [
        item["code"] for item in blockers if item["code"] != "promotion_pending"
    ]
    updated["draft"]["blockers"] = blockers
    updated["draft"]["promotion_gate"] = {
        "eligible": not blocking_codes,
        "missing": blocking_codes,
    }
    updated["operation"]["block_reason"] = "draft blockers: " + ", ".join(
        item["code"] for item in blockers
    )
    return updated


def build_conservative_draft(
    route: Mapping[str, Any], *, identity: Mapping[str, Any], coverage_path: Path,
    route_index: int,
) -> dict[str, Any]:
    operation_id = str(identity["operation_id"])
    path = str(route["path"])
    path_fields = sorted(set(re.findall(r"\{([A-Za-z][A-Za-z0-9_]*)\}", path)))
    input_fields = {
        name: {"type": "any", "required": True} for name in path_fields
    }
    source: dict[str, Any] = {
        "$schema": "../schema/operation-v2.schema.json",
        "source_schema_version": 2,
        "target_manifest": TARGET_MANIFESTS.get(str(identity["domain"]), "other.json"),
        "manifest_order": 10000,
        "operation": _conservative_operation(
            route, identity, path=path, path_fields=path_fields,
            input_fields=input_fields,
        ),
        "draft": _conservative_metadata(
            route, coverage_path=coverage_path, route_index=route_index
        ),
    }
    return refresh_structured_blockers(source, route)


def _conservative_operation(
    route: Mapping[str, Any], identity: Mapping[str, Any], *, path: str,
    path_fields: Sequence[str], input_fields: Mapping[str, Any],
) -> dict[str, Any]:
    operation_id = str(identity["operation_id"])
    return {
        "operation_id": operation_id, "domain": identity["domain"],
        "resource": identity["resource"], "action": identity["action"],
        "platform": identity.get("platform"),
        "description": (
            f"Draft catalog entry inferred from census route {route['method']} {path}; "
            "request binding, pagination, and response projection remain unverified."
        ),
        "contract_version": 1, "upstream_method": str(route["method"]).upper(),
        "path_template": path, "auth_profile": "gravity_authorization",
        "stability": "experimental", "executable": False, "block_reason": None,
        "input_fields": input_fields,
        "request": {
            "path_fields": list(path_fields), "query_fields": [], "body_fields": [],
            "defaults": {}, "fixed_query": {}, "fixed_body": {},
        },
        "response_projection": {
            "data_keys": [], "required_data_keys": [], "item_keys": [],
            "dynamic_item_fields": [],
        },
        "pagination": {
            "kind": "unverified", "page_field": "", "page_size_field": "",
            "list_path": "", "page_info_path": "", "total_page_field": "",
        },
        "semantic_error_rules": [],
        "privacy_policy": {
            "classification": "unverified",
            "redact_fields": list(DEFAULT_REDACT_FIELDS),
        },
        "required_parent": [], "live_probe": {"enabled": False, "inputs": {}},
        "effect": "read", "examples": [],
        "provenance": {
            "source_files": [f"drafts/{operation_id}.json"],
            "family": route_family_id(route), "platform": identity.get("platform"),
            "applied_overrides": [],
        },
    }


def _conservative_metadata(
    route: Mapping[str, Any], *, coverage_path: Path, route_index: int,
) -> dict[str, Any]:
    return {
        "status": "draft", "generated_at": now_utc(),
        "coverage_reference": _coverage_reference(
            route, coverage_path=coverage_path, route_index=route_index
        ),
        "route_evidence": _route_evidence(route),
        "candidate_fields": [], "manual_review_fields": [], "probe_evidence": [],
        "blockers": [], "promotion_gate": {"eligible": False, "missing": []},
    }


def build_draft(route: Mapping[str, Any], existing_ids: set[str]) -> dict[str, Any]:
    identity = infer_identity(route)
    fields, request, parents, probe_inputs = _infer_contract_parts(route, identity, existing_ids)
    operation_id = str(identity["operation_id"])
    route_path = str(route["path"])
    auth_profile = _auth_profile(route_path)
    return {
        "$schema": "../schema/operation-v2.schema.json", "source_schema_version": 2,
        "target_manifest": TARGET_MANIFESTS.get(str(identity["domain"]), "other.json"),
        "manifest_order": 10000,
        "operation": {
            "operation_id": operation_id, "domain": identity["domain"],
            "resource": identity["resource"], "action": identity["action"],
            "platform": identity["platform"],
            "description": f"Draft inferred from census route {route['method']} {route['path']}; response remains hidden until probe classification.",
            "contract_version": 1, "upstream_method": str(route["method"]).upper(),
            "path_template": route_path, "auth_profile": auth_profile,
            "stability": "experimental", "executable": False,
            "block_reason": "draft contract requires successful live probe and promotion gate",
            "input_fields": fields, "request": request,
            "response_projection": {
                "data_keys": [], "required_data_keys": [], "item_keys": [],
                "dynamic_item_fields": [],
            },
            "pagination": {
                "kind": "none", "page_field": "", "page_size_field": "",
                "list_path": "", "page_info_path": "", "total_page_field": "",
            },
            "semantic_error_rules": ["code", "extra.error"],
            "privacy_policy": {
                "classification": "internal_business",
                "redact_fields": list(DEFAULT_REDACT_FIELDS),
            },
            "required_parent": parents, "live_probe": {"enabled": False, "inputs": probe_inputs},
            "effect": "read", "examples": [],
            "provenance": {
                "source_files": [f"drafts/{operation_id}.json"],
                "family": route_family_id(route), "platform": identity["platform"],
                "applied_overrides": [],
            },
        },
        "draft": {
            "status": "draft", "generated_at": now_utc(),
            "route_evidence": _route_evidence(route), "candidate_fields": [],
            "manual_review_fields": [], "probe_evidence": [],
            "promotion_gate": {
                "eligible": False,
                "missing": _initial_gate_missing(route_path, auth_profile),
            },
        },
    }


def validate_source(source: Mapping[str, Any]) -> None:
    from .parameter_types import validate_source_contract

    validate_source_contract(source)


def create_drafts(
    *, paths: Sequence[str] = (), families: Sequence[str] = (),
    business_modules: Sequence[str] = (), costs: Sequence[str] = (),
    method_certainty: str | None = "high", limit: int = 12,
    coverage_path: Path = COVERAGE_PATH, draft_root: Path = DRAFT_ROOT,
    operation_root: Path = OPERATION_ROOT, overwrite: bool = False,
    method_evidence_path: Path | None = None,
) -> list[dict[str, Any]]:
    coverage = read_json(coverage_path)
    if method_evidence_path is not None:
        coverage = _apply_method_evidence(coverage, read_json(method_evidence_path))
    routes = select_routes(
        coverage, paths=paths, families=families,
        business_modules=business_modules, costs=costs,
        method_certainty=method_certainty, limit=limit,
    )
    coverage_routes = coverage.get("routes", [])
    route_indices = {id(route): index for index, route in enumerate(coverage_routes)}
    existing_ids = set(existing_operations(operation_root))
    draft_ids = {path.stem for path in draft_root.glob("*.json")} if draft_root.is_dir() else set()
    created: list[dict[str, Any]] = []
    for route in routes:
        source = build_draft(route, existing_ids)
        source["draft"]["coverage_reference"] = _coverage_reference(
            route,
            coverage_path=coverage_path,
            route_index=route_indices[id(route)],
        )
        source = refresh_structured_blockers(source, route)
        operation_id = str(source["operation"]["operation_id"])
        if operation_id in existing_ids:
            raise ValueError(f"inferred operation_id conflicts with stable operation: {operation_id}")
        destination = draft_root / f"{operation_id}.json"
        if operation_id in draft_ids and not overwrite:
            raise ValueError(f"draft already exists: {operation_id}")
        validate_source(source)
        write_json(destination, source)
        draft_ids.add(operation_id)
        created.append(
            {
                "operation_id": operation_id, "method": route["method"],
                "path": route["path"], "family": route_family_id(route),
                "draft_path": display_path(destination),
            }
        )
    return created


def _operation_id(identity: Mapping[str, Any], resource: str) -> str:
    domain = str(identity["domain"])
    action = str(identity["action"])
    platform = identity.get("platform")
    if domain == "promotion" and platform:
        return f"{domain}.{platform}.{resource}.{action}"
    return f"{domain}.{resource}.{action}"


def _quality_reasons(
    source: Mapping[str, Any], *, stable_routes: set[tuple[str, str]],
    seen_ids: set[str], seen_routes: set[tuple[str, str]],
) -> list[dict[str, str]]:
    operation = source["operation"]
    reasons: list[dict[str, str]] = []
    for name in ("domain", "resource", "action"):
        value = str(operation.get(name, ""))
        if not value or value == "unknown":
            reasons.append(
                {
                    "code": f"unknown_{name}",
                    "detail": f"Could not infer {name} from census path/module/UI evidence.",
                }
            )
    operation_id = str(operation.get("operation_id", ""))
    if not re.fullmatch(r"[a-z][a-z0-9_]*(?:\.[a-z0-9_]+)+", operation_id):
        reasons.append(
            {"code": "invalid_operation_id", "detail": f"Invalid operation_id: {operation_id}"}
        )
    if operation_id in seen_ids:
        reasons.append(
            {"code": "duplicate_operation_id", "detail": f"Duplicate operation_id: {operation_id}"}
        )
    route_key = (str(operation["upstream_method"]), str(operation["path_template"]))
    if route_key in stable_routes:
        reasons.append(
            {
                "code": "stable_route_duplicate",
                "detail": f"Route is already registered: {route_key[0]} {route_key[1]}",
            }
        )
    if route_key in seen_routes:
        reasons.append(
            {
                "code": "duplicate_method_path",
                "detail": f"Duplicate census route: {route_key[0]} {route_key[1]}",
            }
        )
    path_fields = set(re.findall(r"\{([A-Za-z][A-Za-z0-9_]*)\}", route_key[1]))
    request = operation["request"]
    bound_path_fields = set(request.get("path_fields", []))
    if path_fields != bound_path_fields:
        reasons.append(
            {
                "code": "path_binding_mismatch",
                "detail": (
                    f"Path placeholders {sorted(path_fields)} do not match request.path_fields "
                    f"{sorted(bound_path_fields)}."
                ),
            }
        )
    input_names = set(operation.get("input_fields", {}))
    bound_names = (
        bound_path_fields
        | set(request.get("query_fields", []))
        | set(request.get("body_fields", []))
        | set(request.get("defaults", {}))
    )
    if not bound_names <= input_names:
        reasons.append(
            {
                "code": "request_input_mismatch",
                "detail": "One or more request-bound fields are absent from input_fields.",
            }
        )
    if "/get_verify_code/" in route_key[1]:
        reasons.append(
            {
                "code": "ambiguous_read_semantics",
                "detail": "The route name suggests a side effect despite census read classification.",
            }
        )
    return reasons


def _report_route(route: Mapping[str, Any], route_index: int) -> dict[str, Any]:
    return {
        "route_index": route_index,
        "json_pointer": f"/routes/{route_index}",
        "method": route.get("method"),
        "path": route.get("path"),
        "method_certainty": route.get("method_certainty"),
        "business_module": route.get("business_module"),
        "callers": copy.deepcopy(route.get("callers", [])),
        "ui_texts": copy.deepcopy(route.get("ui_texts", [])),
        "first_occurrence": copy.deepcopy(route.get("first_occurrence")),
    }


def _select_bulk_routes(
    routes: Sequence[Any], method_certainty: str, limit: int,
) -> tuple[list[tuple[int, Mapping[str, Any]]], list[tuple[int, Mapping[str, Any]]]]:
    selected = [
        (index, route) for index, route in enumerate(routes)
        if isinstance(route, Mapping)
        and route.get("status") == "uncovered_read"
        and route.get("method_certainty") == method_certainty
        and str(route.get("method", "")).upper() in {"GET", "POST"}
    ]
    if len(selected) > limit:
        raise ValueError(f"route selection produced {len(selected)} entries; limit is {limit}")
    excluded = [
        (index, route) for index, route in enumerate(routes)
        if isinstance(route, Mapping)
        and route.get("status") == "uncovered_read"
        and route.get("method_certainty") != method_certainty
    ]
    return selected, excluded


def _existing_draft_indexes(
    draft_root: Path,
) -> tuple[
    dict[str, Mapping[str, Any]],
    dict[tuple[str, str], tuple[str, Mapping[str, Any]]],
]:
    existing_drafts: dict[str, Mapping[str, Any]] = {}
    existing_by_route: dict[tuple[str, str], tuple[str, Mapping[str, Any]]] = {}
    if not draft_root.is_dir():
        return existing_drafts, existing_by_route
    for path in sorted(draft_root.glob("*.json")):
        source = read_json(path)
        operation = source.get("operation", {})
        operation_id = str(operation.get("operation_id", path.stem))
        existing_drafts[operation_id] = source
        route_key = (
            str(operation.get("upstream_method", "")),
            str(operation.get("path_template", "")),
        )
        existing_by_route[route_key] = (operation_id, source)
    return existing_drafts, existing_by_route


def _provisional_bulk_drafts(
    selected: Sequence[tuple[int, Mapping[str, Any]]],
    existing_by_route: Mapping[tuple[str, str], tuple[str, Mapping[str, Any]]],
) -> list[dict[str, Any]]:
    provisional: list[dict[str, Any]] = []
    for route_index, route in selected:
        route_key = (str(route.get("method", "")).upper(), str(route.get("path", "")))
        existing = existing_by_route.get(route_key)
        if existing:
            operation = existing[1]["operation"]
            identity = {
                "operation_id": existing[0], "domain": operation["domain"],
                "resource": operation["resource"], "action": operation["action"],
                "platform": operation.get("platform"),
                "resource_context": infer_identity(route).get("resource_context"),
            }
        else:
            identity = infer_identity(route)
        provisional.append({
            "route_index": route_index, "route": route, "route_key": route_key,
            "identity": identity, "existing": existing,
        })
    return provisional


def _assign_bulk_operation_ids(
    provisional: Sequence[dict[str, Any]], stable_ids: set[str],
    existing_ids: set[str],
) -> None:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in provisional:
        groups[str(item["identity"]["operation_id"])].append(item)
    reserved_ids = stable_ids | existing_ids
    assigned_ids: set[str] = set()
    for initial_id, items in sorted(groups.items()):
        conflict = len(items) > 1 or initial_id in stable_ids
        for item in sorted(items, key=lambda value: value["route_key"]):
            identity = item["identity"]
            if item["existing"]:
                assigned_ids.add(str(identity["operation_id"]))
                continue
            operation_id = str(identity["operation_id"])
            if conflict or operation_id in reserved_ids or operation_id in assigned_ids:
                context = _normal_token(str(identity.get("resource_context", "")))
                resource = context or str(identity["resource"])
                operation_id = _operation_id(identity, resource)
                if operation_id in reserved_ids or operation_id in assigned_ids:
                    suffix = hashlib.sha256(
                        f"{item['route_key'][0]} {item['route_key'][1]}".encode()
                    ).hexdigest()[:8]
                    resource = f"{resource}_{suffix}"
                    operation_id = _operation_id(identity, resource)
                item["identity"] = {
                    **identity, "resource": resource, "operation_id": operation_id,
                }
            assigned_ids.add(operation_id)


def _accepted_bulk_drafts(
    provisional: Sequence[dict[str, Any]], *, coverage_path: Path,
    stable_routes: set[tuple[str, str]],
) -> tuple[
    list[tuple[dict[str, Any], dict[str, Any], str]], list[dict[str, Any]],
]:
    accepted: list[tuple[dict[str, Any], dict[str, Any], str]] = []
    rejected: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_routes: set[tuple[str, str]] = set()
    for item in sorted(provisional, key=lambda value: value["route_key"]):
        route = item["route"]
        route_index = int(item["route_index"])
        if item["existing"]:
            source = copy.deepcopy(dict(item["existing"][1]))
            source["draft"]["coverage_reference"] = _coverage_reference(
                route, coverage_path=coverage_path, route_index=route_index
            )
            source["draft"]["route_evidence"] = _route_evidence(route)
            source = refresh_structured_blockers(source, route)
            disposition = "updated_existing"
        else:
            source = build_conservative_draft(
                route, identity=item["identity"], coverage_path=coverage_path,
                route_index=route_index,
            )
            disposition = "created"
        reasons = _quality_reasons(
            source, stable_routes=stable_routes,
            seen_ids=seen_ids, seen_routes=seen_routes,
        )
        if not reasons:
            try:
                validate_source(source)
            except (TypeError, ValueError) as exc:
                reasons.append({"code": "schema_validation_failed", "detail": str(exc)})
        if reasons:
            rejected.append({
                **_report_route(route, route_index),
                "inferred_identity": copy.deepcopy(item["identity"]), "reasons": reasons,
            })
            continue
        operation_id = str(source["operation"]["operation_id"])
        seen_ids.add(operation_id)
        seen_routes.add(item["route_key"])
        accepted.append((item, source, disposition))
    return accepted, rejected


def _write_bulk_drafts(
    accepted: Sequence[tuple[dict[str, Any], dict[str, Any], str]], draft_root: Path,
) -> list[dict[str, Any]]:
    draft_rows: list[dict[str, Any]] = []
    for item, source, disposition in accepted:
        operation_id = str(source["operation"]["operation_id"])
        destination = draft_root / f"{operation_id}.json"
        write_json(destination, source)
        draft_rows.append({
            "operation_id": operation_id, "domain": source["operation"]["domain"],
            "resource": source["operation"]["resource"],
            "action": source["operation"]["action"],
            "platform": source["operation"].get("platform"),
            "method": source["operation"]["upstream_method"],
            "path": source["operation"]["path_template"],
            "coverage_reference": copy.deepcopy(source["draft"]["coverage_reference"]),
            "blockers": copy.deepcopy(source["draft"]["blockers"]),
            "disposition": disposition, "draft_path": display_path(destination),
        })
    return draft_rows


def _bulk_draft_report(
    *, coverage_path: Path, method_certainty: str,
    selected: Sequence[tuple[int, Mapping[str, Any]]],
    excluded: Sequence[tuple[int, Mapping[str, Any]]],
    stable_sources: Mapping[str, Any],
    accepted: Sequence[tuple[dict[str, Any], dict[str, Any], str]],
    rejected: Sequence[Mapping[str, Any]], draft_rows: Sequence[Mapping[str, Any]],
    draft_root: Path, report_root: Path,
) -> dict[str, Any]:
    reason_counts = Counter(reason["code"] for row in rejected for reason in row["reasons"])
    blocker_counts = Counter(
        blocker["code"] for row in draft_rows for blocker in row["blockers"]
    )
    certainty_counts = Counter(str(route.get("method_certainty", "unknown")) for _, route in excluded)
    module_counts = Counter(str(route.get("business_module", "unknown")) for _, route in excluded)
    draft_count = len(list(draft_root.glob("*.json")))
    summary = {
        "schema_version": "gravity-insight.bulk-draft-summary.v1",
        "coverage_path": display_path(coverage_path), "method_certainty": method_certainty,
        "attempted": len(selected), "successful": len(draft_rows),
        "created": sum(row["disposition"] == "created" for row in draft_rows),
        "updated_existing": sum(row["disposition"] == "updated_existing" for row in draft_rows),
        "with_probe_evidence": sum(bool(source["draft"].get("probe_evidence")) for _, source, _ in accepted),
        "without_probe_evidence": sum(not bool(source["draft"].get("probe_evidence")) for _, source, _ in accepted),
        "rejected": len(rejected),
        "rejected_reason_counts": dict(sorted(reason_counts.items())),
        "blocker_counts": dict(sorted(blocker_counts.items())), "excluded": len(excluded),
        "excluded_certainty_counts": dict(sorted(certainty_counts.items())),
        "excluded_module_counts": dict(sorted(module_counts.items())),
        "stable_operation_contracts": len(stable_sources), "draft_contracts": draft_count,
        "total_contracts": len(stable_sources) + draft_count,
    }
    report_root.mkdir(parents=True, exist_ok=True)
    write_json(report_root / "drafts.json", {
        "schema_version": "gravity-insight.bulk-drafts.v1",
        "count": len(draft_rows), "drafts": draft_rows,
    })
    write_json(report_root / "rejected.json", {
        "schema_version": "gravity-insight.bulk-rejected.v1",
        "count": len(rejected), "routes": rejected,
    })
    excluded_rows = [_report_route(route, index) for index, route in excluded]
    write_json(report_root / "excluded-certainty.json", {
        "schema_version": "gravity-insight.bulk-excluded-certainty.v1",
        "count": len(excluded_rows),
        "certainty_counts": dict(sorted(certainty_counts.items())),
        "module_counts": dict(sorted(module_counts.items())), "routes": excluded_rows,
    })
    summary["reports"] = {
        "drafts": display_path(report_root / "drafts.json"),
        "rejected": display_path(report_root / "rejected.json"),
        "excluded_certainty": display_path(report_root / "excluded-certainty.json"),
        "summary": display_path(report_root / "summary.json"),
    }
    write_json(report_root / "summary.json", summary)
    return summary


def create_bulk_drafts(
    *, method_certainty: str = "high", limit: int = 321,
    coverage_path: Path = COVERAGE_PATH, draft_root: Path = DRAFT_ROOT,
    operation_root: Path = OPERATION_ROOT, report_root: Path = BULK_REPORT_ROOT,
) -> dict[str, Any]:
    coverage = read_json(coverage_path)
    routes = coverage.get("routes") if isinstance(coverage, Mapping) else None
    if not isinstance(routes, list):
        raise ValueError("coverage.json has no routes array")
    selected, excluded = _select_bulk_routes(routes, method_certainty, limit)

    stable_sources = existing_operations(operation_root)
    stable_routes = {
        (
            str(source["operation"]["upstream_method"]),
            str(source["operation"]["path_template"]),
        )
        for source in stable_sources.values()
    }
    existing_drafts, existing_by_route = _existing_draft_indexes(draft_root)
    provisional = _provisional_bulk_drafts(selected, existing_by_route)
    _assign_bulk_operation_ids(provisional, set(stable_sources), set(existing_drafts))
    accepted, rejected = _accepted_bulk_drafts(
        provisional, coverage_path=coverage_path, stable_routes=stable_routes
    )
    draft_rows = _write_bulk_drafts(accepted, draft_root)

    return _bulk_draft_report(
        coverage_path=coverage_path, method_certainty=method_certainty,
        selected=selected, excluded=excluded, stable_sources=stable_sources,
        accepted=accepted, rejected=rejected, draft_rows=draft_rows,
        draft_root=draft_root, report_root=report_root,
    )


def _route_tokens(path: str) -> list[str]:
    return [
        token
        for token in re.findall(r"[a-z0-9]+", path.casefold())
        if token
    ]


def _source_route_status(route: Mapping[str, Any]) -> str:
    classification = route.get("route_classification")
    if isinstance(classification, Mapping) and isinstance(
        classification.get("source_status"), str
    ):
        return str(classification["source_status"])
    return str(route.get("status", ""))


def _route_evidence_fingerprint(route: Mapping[str, Any]) -> str:
    evidence_fields = (
        "method", "path", "method_certainty", "method_evidence",
        "route_evidence_kinds", "business_module", "promotion_platform",
        "promotion_level", "occurrences", "raw_paths", "callers", "ui_texts",
        "first_occurrence", "contract_family", "contract_family_alternates",
    )
    payload = {
        key: copy.deepcopy(route.get(key))
        for key in evidence_fields if key in route
    }
    payload["source_status"] = _source_route_status(route)
    return canonical_fingerprint(payload)


def classify_mutation_kind(route: Mapping[str, Any]) -> tuple[str, str | None, list[str]]:
    path = str(route.get("path", ""))
    tokens = _route_tokens(path)
    token_set = set(tokens)
    evidence: list[str] = []
    inferred = _base_mutation_kind(path, token_set)
    batch = bool(token_set.intersection({"batch", "bulk", "onekey"})) or (
        "one_key" in path.casefold()
    )
    if batch:
        evidence.append("explicit_batch_path_token")
        return "batch", inferred if inferred != "other" else "other", evidence
    if inferred != "other":
        evidence.append(f"explicit_{inferred}_path_token")
    else:
        evidence.append("conservative_write_fallback")
    return inferred, None, evidence


def _base_mutation_kind(path: str, token_set: set[str]) -> str:
    for kind, rule_tokens in _MUTATION_KIND_RULES:
        if token_set.intersection(rule_tokens):
            return kind
        if kind == "state_change" and {"open", "close"}.issubset(token_set):
            return kind
        if kind == "execute" and path.endswith("/event/click/"):
            return kind
    return "other"


def _mutation_reversibility(
    path: str, tokens: set[str], kind: str, ui_text: str,
) -> tuple[str, str]:
    if tokens.intersection({"clear", "kill", "terminate", "resetkey"}) or "reset_key" in path:
        return "irreversible", "explicit_irreversible_action"
    if kind in {"update", "state_change", "bind", "move", "share"}:
        return "reversible", "subsequent_mutation_can_restore_state"
    if "undelete" in tokens or "恢复" in ui_text:
        return "reversible", "explicit_restore_semantics"
    return "unknown", "reversal_contract_not_observed"


def _mutation_idempotency(kind: str) -> str:
    if kind in {"create", "upload", "import", "copy", "execute", "approve"}:
        return "non_idempotent"
    if kind in {"update", "delete", "state_change", "bind", "move", "share"}:
        return "conditional"
    return "unknown"


def _live_delivery_effect(
    tokens: set[str], module: str,
) -> tuple[str, str]:
    delivery_tokens = {
        "ad", "adgroup", "adplan", "advertisement", "advertiser", "campaign",
        "creative", "delivery", "materialpush", "plan", "project", "promotion",
        "publish", "stardelivery", "trackurl",
    }
    compact_tokens = {token.replace("_", "") for token in tokens}
    attribution = {"postback", "attribution", "reattribution", "click", "impress"}
    if compact_tokens.intersection(delivery_tokens) or (
        module in {"推广平台", "归因"} and tokens.intersection(attribution)
    ):
        return "yes", "delivery_or_attribution_resource"
    administration = {"tutorial", "message", "password", "member", "dept", "role"}
    if module == "App 与账号" and tokens.intersection(administration):
        return "no", "account_administration_not_delivery"
    return "unknown", "live_delivery_effect_not_proven"


def _mutation_risk_level(
    kind: str, scope: str, reversibility: str, affects_live_delivery: str,
) -> str:
    if reversibility == "irreversible" or (
        affects_live_delivery == "yes"
        and (scope == "batch" or kind in {"approve", "delete", "execute", "state_change"})
    ):
        return "high"
    if affects_live_delivery == "yes" or scope == "batch" or kind in {
        "approve", "delete", "import", "sync", "upload",
    }:
        return "medium"
    if affects_live_delivery == "no" and reversibility == "reversible":
        return "low"
    return "unknown"


def _mutation_risk(
    route: Mapping[str, Any], kind: str, batch_action: str | None,
    evidence: Sequence[str],
) -> dict[str, Any]:
    path = str(route.get("path", "")).casefold()
    tokens = set(_route_tokens(path))
    ui_text = " ".join(str(item) for item in route.get("ui_texts", [])).casefold()
    scope = "batch" if kind == "batch" else "unknown"
    risk_evidence = list(evidence)
    reversibility, reversibility_evidence = _mutation_reversibility(
        path, tokens, kind, ui_text
    )
    risk_evidence.append(reversibility_evidence)
    idempotency = _mutation_idempotency(kind)
    module = str(route.get("business_module", ""))
    affects_live_delivery, delivery_evidence = _live_delivery_effect(tokens, module)
    risk_evidence.append(delivery_evidence)
    risk_level = _mutation_risk_level(
        kind, scope, reversibility, affects_live_delivery
    )

    return {
        "kind": kind,
        "batch_action": batch_action,
        "idempotency": idempotency,
        "reversibility": reversibility,
        "scope": scope,
        "affects_live_delivery": affects_live_delivery,
        "risk_level": risk_level,
        "evidence": sorted(set(risk_evidence)),
    }


def _reservation_domain(route: Mapping[str, Any]) -> str:
    return {
        "分析": "analysis",
        "推广平台": "promotion",
        "资产": "asset",
        "素材": "material",
        "报表": "report",
        "App 与账号": "app",
        "归因": "attribution",
        "元数据": "metadata",
        "其它": "other",
    }.get(str(route.get("business_module", "")), "other")


def _reservation_identity(
    route: Mapping[str, Any], kind: str, existing_ids: set[str]
) -> dict[str, Any]:
    domain = _reservation_domain(route)
    platform = _platform_from_route(route) if domain == "promotion" else None
    ignored = {
        "account", "accountcenter", "api", "eventcenter", "manager", "openapi",
        "report", "turboengine", "v1", "v2", "v3", "0",
    }
    if platform:
        ignored.add(platform.replace("_", ""))
    candidates = []
    for token in _route_tokens(str(route.get("path", ""))):
        compact = token.replace("_", "")
        if compact in ignored or token in _ACTION_TOKENS or token.isdigit():
            continue
        candidates.append(token)
    resource_parts = candidates[-3:] or [
        "route_" + hashlib.sha256(str(route.get("path", "")).encode()).hexdigest()[:8]
    ]
    parts = [domain]
    if platform:
        parts.append(platform)
    parts.extend(resource_parts)
    parts.append(kind)
    normalized = [re.sub(r"[^a-z0-9_]+", "_", part.casefold()).strip("_") for part in parts]
    normalized = [part for part in normalized if part]
    operation_id = ".".join(normalized)
    if len(operation_id) > 118:
        operation_id = ".".join(normalized[:2] + [normalized[-2], normalized[-1]])
    if operation_id in existing_ids:
        suffix = hashlib.sha256(
            f"{route.get('method')} {route.get('path')}".encode()
        ).hexdigest()[:8]
        operation_id = ".".join(normalized[:-1] + [suffix, normalized[-1]])
    resource = "_".join(resource_parts)
    return {
        "operation_id": operation_id,
        "domain": domain,
        "resource": resource,
        "action": kind,
        "platform": platform,
    }


def _reservation_source(
    route: Mapping[str, Any], *, route_index: int, coverage_path: Path,
    existing_ids: set[str], generated_at: str,
) -> dict[str, Any]:
    kind, batch_action, semantic_evidence = classify_mutation_kind(route)
    identity = _reservation_identity(route, kind, existing_ids)
    operation_id = str(identity["operation_id"])
    risk = _mutation_risk(route, kind, batch_action, semantic_evidence)
    source_path = f"reservations/{operation_id}.json"
    return {
        "$schema": "../schema/operation-v2.schema.json",
        "source_schema_version": 2,
        "target_manifest": TARGET_MANIFESTS.get(str(identity["domain"]), "other.json"),
        "manifest_order": 20000 + route_index,
        "operation": {
            "operation_id": operation_id,
            "domain": identity["domain"],
            "resource": identity["resource"],
            "action": identity["action"],
            "platform": identity["platform"],
            "description": (
                f"Reserved mutation route {route['method']} {route['path']}; "
                "this version never dispatches the upstream request."
            ),
            "contract_version": 1,
            "upstream_method": str(route["method"]).upper(),
            "path_template": str(route["path"]),
            "auth_profile": "gravity_authorization",
            "stability": "blocked_write",
            "executable": False,
            "block_reason": "mutation_sdk_not_implemented",
            "input_fields": {},
            "request": {
                "path_fields": [], "query_fields": [], "body_fields": [],
                "defaults": {}, "fixed_query": {}, "fixed_body": {},
            },
            "response_projection": {
                "data_keys": [], "required_data_keys": [], "item_keys": [],
                "dynamic_item_fields": [],
            },
            "pagination": {
                "kind": "none", "page_field": "", "page_size_field": "",
                "list_path": "", "page_info_path": "", "total_page_field": "",
            },
            "semantic_error_rules": [],
            "privacy_policy": {
                "classification": "internal_business",
                "redact_fields": list(DEFAULT_REDACT_FIELDS),
            },
            "required_parent": [],
            "live_probe": {"enabled": False, "inputs": {}},
            "effect": "mutation",
            "examples": [],
            "provenance": {
                "source_files": [source_path], "family": None,
                "platform": identity["platform"], "applied_overrides": [],
            },
        },
        "reservation": {
            "status": "blocked_write",
            "block_reason": "mutation_sdk_not_implemented",
            "generated_at": generated_at,
            "route_evidence": {
                "coverage_path": display_path(coverage_path),
                "route_index": route_index,
                "json_pointer": f"/routes/{route_index}",
                "route_sha256": _route_evidence_fingerprint(route),
                "source_status": _source_route_status(route),
            },
            "mutation_semantics": risk,
            "request_contract_status": "unknown_until_mutation_sdk_implementation",
            "implementation_prerequisites": [
                "approved_mutation_policy",
                "exact_request_schema",
                "idempotency_and_retry_contract",
                "approval_and_audit_requirements",
                "preimage_readback_and_rollback_contract",
            ],
        },
    }


def _auth_proxy_decision(route: Mapping[str, Any]) -> tuple[str, str, str, str]:
    path = str(route.get("path", "")).casefold()
    rules = (
        (("query_api", "/post/api/", "/proxy/"), (
            "proxy", "third_party_api_proxy", "third_party_proxy_not_sdk_operation",
            "Generic third-party API proxy routes are not exposed as atomic SDK capabilities.",
        )),
        (("callback_url", "event_callback"), (
            "auth", "callback_configuration", "callback_configuration_out_of_scope",
            "Callback configuration belongs to authentication/integration administration.",
        )),
        (("auth_callback", "login_request", "login_url", "oauth_url"), (
            "auth", "oauth_flow", "interactive_oauth_flow",
            "Interactive OAuth navigation and callbacks are not agent-callable API operations.",
        )),
        (("login", "without_passwd"), (
            "auth", "login", "interactive_login_flow",
            "Login and passwordless session establishment remain in the credential subsystem.",
        )),
        (("token", "authorization"), (
            "auth", "credential_management", "credential_material_route",
            "Credential and authorization material must not enter the business capability catalog.",
        )),
        (("auth2user", "auth_user"), (
            "auth", "authorization_assignment", "authorization_administration",
            "Authorization assignment is an administrative auth surface, not a business operation.",
        )),
    )
    for tokens, decision in rules:
        if any(token in path for token in tokens):
            return decision
    if path.endswith("/auth/"):
        return rules[-1][1]
    return "auth", "third_party_auth", "authentication_surface", (
        "Authentication and third-party authorization surfaces are intentionally unsupported."
    )


def _unclassified_decision(route: Mapping[str, Any]) -> tuple[str, str, str, str, str]:
    path = str(route.get("path", ""))
    if path in _NON_API_UNCLASSIFIED_PATHS:
        subtype = "service_base_url" if path in {
            "/event_center/api/v1/openapi/", "/turbo_engine/api/v2/",
            "/turbo_engine/api/v2/material", "/turbo_engine/api/v2/report",
        } else "unresolved_dynamic_fragment"
        return "non_api", subtype, "unsupported", "not_an_atomic_api_route", (
            "The captured value is a service base URL or unresolved frontend expression, not an atomic route."
        )
    if path in _READ_UNCLASSIFIED_PATHS:
        return "read", "lookup_or_report", "unsupported", "read_contract_not_verified", (
            "Route semantics are read-like, but method/request/response contracts are not verified."
        )
    return "write", "conservative_mutation", "blocked_write", (
        "mutation_sdk_not_implemented"
    ), (
        "The route changes state or cannot be proven read-only; fail-closed policy classifies it as mutation."
    )


def _validate_route_registry(document: Mapping[str, Any]) -> None:
    from gravity_sdk.compiler import JsonSchemaValidator

    schema_path = CONTRACT_ROOT / "schema" / "route-classification-v1.schema.json"
    schema = read_json(schema_path)
    JsonSchemaValidator(schema, str(schema_path)).validate(document)
    keys = [(item["method"], item["path"]) for item in document["routes"]]
    if len(keys) != len(set(keys)):
        raise ValueError("route classification registry contains duplicate method+path")


def _validated_routes(coverage_path: Path) -> list[Any]:
    routes = read_json(coverage_path).get("routes")
    if not isinstance(routes, list):
        raise ValueError("coverage.json has no routes array")
    source_counts = Counter(
        _source_route_status(route) for route in routes if isinstance(route, Mapping)
    )
    expected = {
        "uncovered_write": 362,
        "uncovered_auth_or_proxy": 30,
        "unclassified": 80,
    }
    mismatches = {
        key: {"expected": value, "actual": source_counts[key]}
        for key, value in expected.items() if source_counts[key] != value
    }
    if mismatches:
        raise ValueError(f"coverage target counts drifted: {mismatches}")
    return routes


def _selected_routes(routes: Sequence[Any]) -> list[tuple[int, Mapping[str, Any]]]:
    selected: list[tuple[int, Mapping[str, Any]]] = []
    for route_index, route in enumerate(routes):
        if not isinstance(route, Mapping):
            continue
        source_status = _source_route_status(route)
        if source_status == "uncovered_write":
            selected.append((route_index, route))
        elif source_status == "unclassified":
            classification, _, disposition, _, _ = _unclassified_decision(route)
            if classification == "write" and disposition == "blocked_write":
                selected.append((route_index, route))
    return selected


def _create_reservations(
    selected: Sequence[tuple[int, Mapping[str, Any]]], *,
    coverage_path: Path, reservation_root: Path, existing_ids: set[str],
    generated_at: str, overwrite: bool,
) -> tuple[
    list[dict[str, Any]], dict[tuple[str, str], str], list[dict[str, Any]],
]:
    reservations: list[dict[str, Any]] = []
    reservation_by_route: dict[tuple[str, str], str] = {}
    rejected: list[dict[str, Any]] = []
    for route_index, route in selected:
        try:
            source = _reservation_source(
                route, route_index=route_index, coverage_path=coverage_path,
                existing_ids=existing_ids, generated_at=generated_at,
            )
            operation_id = str(source["operation"]["operation_id"])
            if operation_id in existing_ids:
                raise ValueError(f"duplicate operation_id after disambiguation: {operation_id}")
            destination = reservation_root / f"{operation_id}.json"
            if destination.exists() and not overwrite:
                raise ValueError(f"reservation already exists: {operation_id}")
            validate_source(source)
            write_json(destination, source)
            existing_ids.add(operation_id)
            key = (str(route["method"]).upper(), str(route["path"]))
            reservation_by_route[key] = operation_id
            reservations.append({
                "operation_id": operation_id, "method": key[0], "path": key[1],
                "source_status": _source_route_status(route), "route_index": route_index,
                "reservation_path": display_path(destination),
                "mutation_semantics": source["reservation"]["mutation_semantics"],
            })
        except (OSError, TypeError, ValueError) as exc:
            rejected.append({
                "method": route.get("method"), "path": route.get("path"),
                "route_index": route_index, "reason": str(exc),
            })
    return reservations, reservation_by_route, rejected


def _classification_decisions(
    routes: Sequence[Any], reservation_by_route: Mapping[tuple[str, str], str],
) -> list[dict[str, Any]]:
    decisions: list[dict[str, Any]] = []
    for route_index, route in enumerate(routes):
        if not isinstance(route, Mapping):
            continue
        source_status = _source_route_status(route)
        if source_status == "uncovered_auth_or_proxy":
            classification, subtype, reason_code, reason = _auth_proxy_decision(route)
            disposition = "unsupported"
        elif source_status == "unclassified":
            classification, subtype, disposition, reason_code, reason = _unclassified_decision(route)
        else:
            continue
        key = (str(route["method"]).upper(), str(route["path"]))
        operation_id = reservation_by_route.get(key)
        if disposition == "blocked_write" and not operation_id:
            raise ValueError(f"blocked write decision has no reservation: {key[0]} {key[1]}")
        decisions.append({
            "method": key[0], "path": key[1], "source_status": source_status,
            "classification": classification, "subtype": subtype,
            "disposition": disposition, "reason_code": reason_code,
            "reason": reason, "operation_id": operation_id, "route_index": route_index,
            "route_sha256": _route_evidence_fingerprint(route),
        })
    return decisions


def _risk_counts(routes: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    return {
        "irreversible": sum(
            item["mutation_semantics"]["reversibility"] == "irreversible"
            for item in routes
        ),
        "batch": sum(item["mutation_semantics"]["scope"] == "batch" for item in routes),
        "affects_live_delivery": sum(
            item["mutation_semantics"]["affects_live_delivery"] == "yes"
            for item in routes
        ),
    }


def _summary(
    *, generated_at: str, coverage_path: Path,
    reservations: Sequence[Mapping[str, Any]], rejected: Sequence[Mapping[str, Any]],
    decisions: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    baseline = [item for item in reservations if item["source_status"] == "uncovered_write"]
    extra = [item for item in reservations if item["source_status"] == "unclassified"]
    semantic_counts = Counter(item["mutation_semantics"]["kind"] for item in reservations)
    baseline_semantic_counts = Counter(item["mutation_semantics"]["kind"] for item in baseline)
    extra_semantic_counts = Counter(item["mutation_semantics"]["kind"] for item in extra)
    auth_counts = Counter(
        item["subtype"] for item in decisions
        if item["source_status"] == "uncovered_auth_or_proxy"
    )
    unclassified_counts = Counter(
        item["classification"] for item in decisions
        if item["source_status"] == "unclassified"
    )
    return {
        "schema_version": "gravity-insight.write-registry-summary.v1",
        "generated_at": generated_at, "source": display_path(coverage_path),
        "baseline_write_routes": len(baseline),
        "extra_unclassified_write_routes": len(extra),
        "reservations_created": len(reservations), "rejected": len(rejected),
        "auth_proxy_registered": sum(auth_counts.values()),
        "unclassified_registered": sum(unclassified_counts.values()),
        "mutation_semantics": dict(sorted(semantic_counts.items())),
        "baseline_mutation_semantics": dict(sorted(baseline_semantic_counts.items())),
        "extra_mutation_semantics": dict(sorted(extra_semantic_counts.items())),
        "risk": _risk_counts(reservations), "baseline_risk": _risk_counts(baseline),
        "extra_risk": _risk_counts(extra),
        "auth_proxy_subtypes": dict(sorted(auth_counts.items())),
        "unclassified_classifications": dict(sorted(unclassified_counts.items())),
    }


def _write_reports(
    *, report_root: Path, reservations: Sequence[Mapping[str, Any]],
    decisions: Sequence[Mapping[str, Any]], rejected: Sequence[Mapping[str, Any]],
    summary: Mapping[str, Any],
) -> None:
    write_json(report_root / "write-reservations.json", {
        "schema_version": "gravity-insight.write-reservations.v1", "routes": reservations,
    })
    write_json(report_root / "auth-proxy.json", {
        "schema_version": "gravity-insight.auth-proxy-classification.v1",
        "routes": [item for item in decisions if item["source_status"] == "uncovered_auth_or_proxy"],
    })
    write_json(report_root / "unclassified.json", {
        "schema_version": "gravity-insight.unclassified-resolution.v1",
        "routes": [item for item in decisions if item["source_status"] == "unclassified"],
    })
    write_json(report_root / "rejected.json", {
        "schema_version": "gravity-insight.write-rejected.v1", "routes": rejected,
    })
    write_json(report_root / "summary.json", summary)


def _create_write_registry_impl(
    *, coverage_path: Path, reservation_root: Path,
    route_registry_path: Path, report_root: Path, overwrite: bool,
) -> dict[str, Any]:
    routes = _validated_routes(coverage_path)
    generated_at = now_utc()
    existing_ids = set(existing_operations(OPERATION_ROOT))
    existing_ids.update(path.stem for path in DRAFT_ROOT.glob("*.json"))
    reservations, reservation_by_route, rejected = _create_reservations(
        _selected_routes(routes), coverage_path=coverage_path,
        reservation_root=reservation_root, existing_ids=existing_ids,
        generated_at=generated_at, overwrite=overwrite,
    )
    decisions = _classification_decisions(routes, reservation_by_route)
    registry = {
        "schema_version": "gravity-insight.route-classification.v1",
        "generated_at": generated_at, "source": display_path(coverage_path),
        "routes": decisions,
    }
    _validate_route_registry(registry)
    write_json(route_registry_path, registry)
    summary = _summary(
        generated_at=generated_at, coverage_path=coverage_path,
        reservations=reservations, rejected=rejected, decisions=decisions,
    )
    _write_reports(
        report_root=report_root, reservations=reservations,
        decisions=decisions, rejected=rejected, summary=summary,
    )
    return summary


def create_write_registry(
    *, coverage_path: Path = COVERAGE_PATH,
    reservation_root: Path = RESERVATION_ROOT,
    route_registry_path: Path = ROUTE_REGISTRY_PATH,
    report_root: Path = WRITE_REPORT_ROOT,
    overwrite: bool = False,
) -> dict[str, Any]:
    return _create_write_registry_impl(
        coverage_path=coverage_path,
        reservation_root=reservation_root,
        route_registry_path=route_registry_path,
        report_root=report_root,
        overwrite=overwrite,
    )


def _apply_method_evidence(
    coverage: Mapping[str, Any], evidence: Mapping[str, Any]
) -> dict[str, Any]:
    from .parameter_types import apply_method_evidence

    return apply_method_evidence(coverage, evidence)
