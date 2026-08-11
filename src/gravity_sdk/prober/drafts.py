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

PLURAL_RESOURCES = {
    "ad_groups": "ad_group",
    "campaigns": "campaign",
    "components": "component",
    "favorites": "favorite",
    "keys": "key",
    "members": "member",
}

AMBIGUOUS_POST_TAILS = {"manage", "set"}
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
        matches = (
            (not path_set or route.get("path") in path_set)
            and (not family_set or route_family_id(route) in family_set)
            and (not module_set or route.get("business_module") in module_set)
            and (not cost_set or route.get("estimated_implementation_cost") in cost_set)
            and (not method_certainty or route.get("method_certainty") == method_certainty)
            and str(route.get("method", "")).upper() in {"GET", "POST"}
        )
        if matches:
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
        _, segments = _semantic_segments(path)
        if "open_develop" in segments:
            return "developer"
        if "promoted_object" in segments:
            return "promotion"
        if segments and segments[0] == "report":
            return "report"
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
    if any(token in path for token in ("/health_status/", "/base/company_config/")):
        return "metadata"
    if any(token in path for token in ("/common/media_report/", "/monetization/", "/subscribe/")):
        return "report"
    if "/event/" in path:
        return "analysis"
    if "/portal/" in path or "/oplog/" in path:
        return "account"
    if any(token in path for token in ("/common/", "/media/", "/task/")):
        return "promotion"
    if platform:
        return "promotion"
    return "unknown"


def _normal_token(value: str) -> str:
    value = value.casefold().replace("-", "_")
    value = re.sub(r"[^a-z0-9_]+", "_", value)
    return re.sub(r"_+", "_", value).strip("_")


def _resource_action(
    route: Mapping[str, Any], segments: Sequence[str], *, domain: str,
) -> tuple[str, str]:
    if not segments:
        return "unknown", "unknown"
    values = list(segments)
    while values and re.fullmatch(r"v\d+", values[-1]):
        values.pop()
    if not values:
        return "unknown", "unknown"
    tail = _normal_token(values[-1])
    method = str(route.get("method", "")).upper()
    if method == "POST" and tail in AMBIGUOUS_POST_TAILS:
        return "unknown", "unknown"
    if tail == "by_company":
        return "account_company", "list"
    if tail in {"tree", "whole_tree"}:
        resource = _normal_token(values[-2]) if len(values) > 1 else "unknown"
        return resource, "tree"
    if tail == "calc_total":
        resource = _normal_token(values[-2]) if len(values) > 1 else "report"
        return resource, "calc_total"
    if tail == "list":
        if len(values) < 2:
            return "unknown", "list"
        resource = _normal_token(values[-2])
        if "manager" in values and resource in {"campaign", "adgroup", "ad_group"}:
            resource += "_option"
        return resource, "list"
    if tail.endswith("_list"):
        prefix = tail[: -len("_list")]
        if prefix in {"public", "info", "user"} and len(values) > 1:
            resource = _normal_token(values[-2])
            resource += "_" + prefix
        else:
            resource = prefix
        return resource or "unknown", "list"
    if tail in PLURAL_RESOURCES:
        return PLURAL_RESOURCES[tail], "list"
    if tail == "filters":
        resource = _normal_token(values[-2]) if len(values) > 1 else "filter"
        return resource + "_filter", "list"
    if tail in {"detail", "info"}:
        resource = _normal_token(values[-2]) if len(values) > 1 else "unknown"
        return resource, tail
    if tail in {
        "get", "preview", "check", "history", "binding_url", "click_info",
        "device_info", "fetch_app_info", "get_file_params", "get_metrics",
        "get_result", "latest_account_status", "role_get", "sensitive_info",
        "test_message", "tutorial_mark", "use_template", "user_privacy_policy",
        "version_id_set",
    }:
        if tail == "get" and len(values) > 1:
            resource = _normal_token(values[-2])
        else:
            resource = re.sub(r"^(fetch|get)_", "", tail)
        return resource or "unknown", "get"
    if tail == "custom_get" and len(values) > 1:
        return _normal_token(values[-2]), "query"
    if tail in {"query", "data_analysis", "hour_comparison", "overview", "query_company_amount", "setting", "attribution"}:
        resource = re.sub(r"^(custom_|query_)", "", tail) or "report"
        return resource, "query"
    if tail == "report":
        resource = _normal_token(values[-2]) if len(values) > 1 else "report"
        return resource, "list" if domain == "promotion" else "query"
    if "report" in values and tail in {"account", "adcreative", "adgroup", "campaign", "creative", "keyword", "plan", "unit"}:
        return tail, "list"
    if method == "GET":
        return tail, "get"
    if "read_action_path_token" in route.get("semantic_evidence", []):
        return tail, "query"
    return "unknown", "unknown"


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


def _field(type_name: str, *, default: Any = None, required: bool = False) -> dict[str, Any]:
    value: dict[str, Any] = {"type": type_name}
    if required:
        value["required"] = True
    elif default is not None:
        value["default"] = default
    return value


def _option_contract(
    platform: Any, existing_ids: set[str]
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    input_type = "array" if platform == "kuaishou" else "string"
    fields = {"advertiser_id": _field(input_type, required=True)}
    parents: list[dict[str, Any]] = []
    parent_candidates = [
        f"promotion.{platform}.account.list",
        f"promotion.{platform}.advertiser.list",
    ]
    parent_id = next((item for item in parent_candidates if item in existing_ids), None)
    probe_inputs: dict[str, Any] = {}
    if parent_id:
        parents.append(
            {
                "operation_id": parent_id, "input_field": "advertiser_id",
                "output_path": "data.list[].advertiser_id", "selection": "caller_select",
            }
        )
        placeholder = (
            f"$first_{platform}_advertiser_id"
            if platform in {"bytedance", "tencent", "kuaishou"} else "$parent"
        )
        probe_inputs["advertiser_id"] = [placeholder] if input_type == "array" else placeholder
    return fields, probe_inputs, parents


def _report_contract() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    fields = {
        "date_list": _field("array", required=True), "filtering": _field("object", default={}),
        "filters": _field("array", default=[]), "order_by": _field("array", default=[]),
        "page": _field("integer", default=1), "page_size": _field("integer", default=10),
        "query_fields": _field("array", default=[]),
    }
    defaults = {
        "filtering": {}, "filters": [], "order_by": [], "page": 1,
        "page_size": 10, "query_fields": [],
    }
    probe_inputs = {**defaults, "date_list": ["$yesterday", "$today"], "page_size": 2}
    return fields, defaults, probe_inputs


def _openapi_adreport_contract() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    fields = {
        "time_dims": {
            "type": "string", "required": True,
            "enum": ["total", "month", "week", "day", "hour"],
        },
        "data_dims": _field("array", default=[]),
        "relate_dims": _field("object", default={}),
        "date_list": _field("array", required=True),
        "metrics_list": _field("array", required=True),
        "custom_metrics_list": _field("array", default=[]),
        "filters": _field("array", required=True),
        "data_conf": _field("object", default={}),
    }
    defaults = {
        "data_dims": [], "relate_dims": {}, "custom_metrics_list": [],
        "data_conf": {},
    }
    probe_inputs = {
        **defaults,
        "time_dims": "day",
        "date_list": ["$today", "$today"],
        "metrics_list": ["ap_cost"],
        "filters": [
            {"field": "app_id", "operator": "EQUALS", "values": ["$first_app_id"]}
        ],
    }
    return fields, defaults, probe_inputs


def _openapi_metric_contract() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    fields = {
        "data_topic": {
            "type": "string", "default": "adreport", "enum": ["adreport"],
        },
        "metric_type": {
            "type": "string", "required": True,
            "enum": ["gravity_preset", "user_custom"],
        },
    }
    defaults = {"data_topic": "adreport"}
    probe_inputs = {**defaults, "metric_type": "gravity_preset"}
    return fields, defaults, probe_inputs


def _infer_contract_parts(
    route: Mapping[str, Any], identity: Mapping[str, Any], existing_ids: set[str]
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    method, path = str(route["method"]).upper(), str(route["path"])
    resource, platform = str(identity["resource"]), identity.get("platform")
    fields: dict[str, Any] = {}
    defaults: dict[str, Any] = {}
    query_fields: list[str] = []
    body_fields: list[str] = []
    parents: list[dict[str, Any]] = []
    probe_inputs: dict[str, Any] = {}
    if path.endswith("/openapi/api/v1/report/adreport/custom_get/"):
        fields, defaults, probe_inputs = _openapi_adreport_contract()
        body_fields.extend(fields)
    elif path.endswith("/openapi/api/v1/report/metrics/list/"):
        fields, defaults, probe_inputs = _openapi_metric_contract()
        body_fields.extend(fields)
    elif resource == "account_company" and platform == "kuaishou":
        fields["need_company"] = _field("boolean", default=True)
        defaults["need_company"] = probe_inputs["need_company"] = True
        body_fields.append("need_company")
    elif resource.endswith("_option"):
        fields, probe_inputs, parents = _option_contract(platform, existing_ids)
        body_fields.append("advertiser_id")
    elif "/report/" in path and identity.get("domain") == "promotion":
        fields, defaults, probe_inputs = _report_contract()
        body_fields.extend(
            ["filtering", "page", "page_size", "query_fields", "date_list", "order_by", "filters"]
        )
    elif path.endswith("/list/") and not any(
        token in path for token in ("/datamanageconfig/", "/const/", "/health_status/")
    ):
        fields.update({"page": _field("integer", default=1), "page_size": _field("integer", default=20)})
        defaults.update({"page": 1, "page_size": 20})
        probe_inputs.update({"page": 1, "page_size": 2})
        (query_fields if method == "GET" else body_fields).extend(["page", "page_size"])
        if path.endswith("/open_develop/list/"):
            fields["filters"] = _field("array", default=[])
            defaults["filters"] = probe_inputs["filters"] = []
            body_fields.append("filters")
        if resource == "brand":
            fields["filters"] = _field("array", default=[])
            defaults["filters"] = probe_inputs["filters"] = []
            body_fields.append("filters")
    request = {
        "path_fields": [], "query_fields": query_fields, "body_fields": body_fields,
        "defaults": defaults, "fixed_query": {}, "fixed_body": {},
    }
    return fields, request, parents, probe_inputs


def _auth_profile(path: str) -> str:
    if not path.startswith("/openapi/api/v1/"):
        return "gravity_authorization"
    if any(segment in path for segment in ("/open_develop/", "/open_app/")):
        return "gravity_authorization"
    return "gravity_openapi_signature"


def _initial_gate_missing(path: str, auth_profile: str) -> list[str]:
    missing = ["successful_probe", "classified_projection", "response_projection"]
    if path.startswith("/openapi/"):
        missing.append("stable_runtime_route_unsupported")
    if auth_profile == "gravity_openapi_signature":
        missing.append("openapi_developer_credentials_unavailable")
    return sorted(missing)


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


def structured_blockers(
    source: Mapping[str, Any], route: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    operation = source.get("operation", {})
    draft = source.get("draft", {})
    evidence = draft.get("probe_evidence", []) if isinstance(draft, Mapping) else []
    latest = evidence[-1] if isinstance(evidence, list) and evidence else None
    latest_path = str(latest.get("path", "")) if isinstance(latest, Mapping) else None
    result: list[dict[str, Any]] = []
    if not isinstance(latest, Mapping):
        result.extend(
            [
                _blocker("not_probed", "No live probe evidence exists for this route."),
                _blocker(
                    "request_binding_unverified",
                    "Query/body fields and fixed request values have not been observed.",
                ),
            ]
        )
    else:
        conclusion = str(latest.get("conclusion", ""))
        if conclusion in {"inconclusive_empty", "available_empty"}:
            result.append(
                _blocker(
                    "empty_sample",
                    "The observed tenant response was empty and cannot prove an item schema.",
                    latest_path,
                )
            )
        elif conclusion == "semantic_error":
            result.append(
                _blocker(
                    "request_parameters_required",
                    "The observed request reached a semantic error; required request fields remain unknown.",
                    latest_path,
                )
            )
        elif not bool(latest.get("successful")):
            result.append(
                _blocker(
                    "probe_inconclusive",
                    "The latest probe did not satisfy the promotion gate.",
                    latest_path,
                )
            )
    cost_reason = str((route or {}).get("cost_reason", ""))
    required_parent = operation.get("required_parent", []) if isinstance(operation, Mapping) else []
    parent_indicated = bool(
        required_parent
        or "depends on a parent" in cost_reason
        or "requires a parent" in cost_reason
    )
    parent_resolved = bool(
        isinstance(latest, Mapping) and latest.get("parent_resolved") is True
    )
    parent_resolution = (
        (route or {}).get("parent_resolution", {})
        if isinstance(route, Mapping)
        else {}
    )
    resolution_conclusion = (
        str(parent_resolution.get("conclusion", ""))
        if isinstance(parent_resolution, Mapping)
        else ""
    )
    if resolution_conclusion in {"unblocked", "blocked_by_data"}:
        parent_resolved = True
    if parent_indicated and not parent_resolved:
        result.append(
            _blocker(
                "parent_resource_required",
                str(parent_resolution.get("detail"))
                if isinstance(parent_resolution, Mapping)
                and parent_resolution.get("detail")
                else "A parent account/campaign selector is indicated, but its binding and cardinality require proof.",
                str(parent_resolution.get("evidence"))
                if isinstance(parent_resolution, Mapping)
                and parent_resolution.get("evidence")
                else latest_path,
            )
        )
    if resolution_conclusion == "blocked_by_data" and isinstance(
        parent_resolution, Mapping
    ):
        replacement = str(parent_resolution.get("replacement_blocker", "empty_sample"))
        if replacement not in {"empty_sample", "permission_unavailable"}:
            replacement = "empty_sample"
        details = {
            "empty_sample": "The proven parent operation returned no selectable parent resource for this tenant.",
            "permission_unavailable": "The proven parent operation is unavailable to the current account.",
        }
        if not any(item.get("code") == replacement for item in result):
            result.append(
                _blocker(
                    replacement,
                    details[replacement],
                    str(parent_resolution.get("evidence") or latest_path or ""),
                )
            )
    manual_fields = draft.get("manual_review_fields", []) if isinstance(draft, Mapping) else []
    if manual_fields:
        result.append(
            _blocker(
                "field_review_required",
                f"{len(manual_fields)} observed response field(s) still require human privacy review.",
                latest_path,
            )
        )
    projection = operation.get("response_projection", {}) if isinstance(operation, Mapping) else {}
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
    privacy = operation.get("privacy_policy", {}) if isinstance(operation, Mapping) else {}
    if isinstance(privacy, Mapping) and privacy.get("classification") == "unverified":
        result.append(
            _blocker(
                "privacy_classification_unverified",
                "The route-level privacy classification has not been established.",
            )
        )
    pagination = operation.get("pagination", {}) if isinstance(operation, Mapping) else {}
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
    fields = operation.get("input_fields", {}) if isinstance(operation, Mapping) else {}
    request = operation.get("request", {}) if isinstance(operation, Mapping) else {}
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
        "operation": {
            "operation_id": operation_id,
            "domain": identity["domain"],
            "resource": identity["resource"],
            "action": identity["action"],
            "platform": identity.get("platform"),
            "description": (
                f"Draft catalog entry inferred from census route {route['method']} {path}; "
                "request binding, pagination, and response projection remain unverified."
            ),
            "contract_version": 1,
            "upstream_method": str(route["method"]).upper(),
            "path_template": path,
            "auth_profile": "gravity_authorization",
            "stability": "experimental",
            "executable": False,
            "block_reason": None,
            "input_fields": input_fields,
            "request": {
                "path_fields": path_fields,
                "query_fields": [],
                "body_fields": [],
                "defaults": {},
                "fixed_query": {},
                "fixed_body": {},
            },
            "response_projection": {
                "data_keys": [],
                "required_data_keys": [],
                "item_keys": [],
                "dynamic_item_fields": [],
            },
            "pagination": {
                "kind": "unverified",
                "page_field": "",
                "page_size_field": "",
                "list_path": "",
                "page_info_path": "",
                "total_page_field": "",
            },
            "semantic_error_rules": [],
            "privacy_policy": {
                "classification": "unverified",
                "redact_fields": list(DEFAULT_REDACT_FIELDS),
            },
            "required_parent": [],
            "live_probe": {"enabled": False, "inputs": {}},
            "effect": "read",
            "examples": [],
            "provenance": {
                "source_files": [f"drafts/{operation_id}.json"],
                "family": route_family_id(route),
                "platform": identity.get("platform"),
                "applied_overrides": [],
            },
        },
        "draft": {
            "status": "draft",
            "generated_at": now_utc(),
            "coverage_reference": _coverage_reference(
                route, coverage_path=coverage_path, route_index=route_index
            ),
            "route_evidence": _route_evidence(route),
            "candidate_fields": [],
            "manual_review_fields": [],
            "probe_evidence": [],
            "blockers": [],
            "promotion_gate": {"eligible": False, "missing": []},
        },
    }
    return refresh_structured_blockers(source, route)


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


def create_bulk_drafts(
    *, method_certainty: str = "high", limit: int = 321,
    coverage_path: Path = COVERAGE_PATH, draft_root: Path = DRAFT_ROOT,
    operation_root: Path = OPERATION_ROOT, report_root: Path = BULK_REPORT_ROOT,
) -> dict[str, Any]:
    coverage = read_json(coverage_path)
    routes = coverage.get("routes") if isinstance(coverage, Mapping) else None
    if not isinstance(routes, list):
        raise ValueError("coverage.json has no routes array")
    selected = [
        (index, route)
        for index, route in enumerate(routes)
        if isinstance(route, Mapping)
        and route.get("status") == "uncovered_read"
        and route.get("method_certainty") == method_certainty
        and str(route.get("method", "")).upper() in {"GET", "POST"}
    ]
    if len(selected) > limit:
        raise ValueError(
            f"route selection produced {len(selected)} entries; limit is {limit}"
        )
    excluded = [
        (index, route)
        for index, route in enumerate(routes)
        if isinstance(route, Mapping)
        and route.get("status") == "uncovered_read"
        and route.get("method_certainty") != method_certainty
    ]

    stable_sources = existing_operations(operation_root)
    stable_routes = {
        (
            str(source["operation"]["upstream_method"]),
            str(source["operation"]["path_template"]),
        )
        for source in stable_sources.values()
    }
    existing_drafts: dict[str, Mapping[str, Any]] = {}
    existing_by_route: dict[tuple[str, str], tuple[str, Mapping[str, Any]]] = {}
    if draft_root.is_dir():
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

    provisional: list[dict[str, Any]] = []
    for route_index, route in selected:
        route_key = (str(route.get("method", "")).upper(), str(route.get("path", "")))
        existing = existing_by_route.get(route_key)
        if existing:
            operation = existing[1]["operation"]
            identity = {
                "operation_id": existing[0],
                "domain": operation["domain"],
                "resource": operation["resource"],
                "action": operation["action"],
                "platform": operation.get("platform"),
                "resource_context": infer_identity(route).get("resource_context"),
            }
        else:
            identity = infer_identity(route)
        provisional.append(
            {
                "route_index": route_index,
                "route": route,
                "route_key": route_key,
                "identity": identity,
                "existing": existing,
            }
        )

    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in provisional:
        groups[str(item["identity"]["operation_id"])].append(item)
    reserved_ids = set(stable_sources) | set(existing_drafts)
    assigned_ids: set[str] = set()
    for initial_id, items in sorted(groups.items()):
        conflict = len(items) > 1 or initial_id in stable_sources
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
                identity = {**identity, "resource": resource, "operation_id": operation_id}
                item["identity"] = identity
            assigned_ids.add(operation_id)

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
                route,
                identity=item["identity"],
                coverage_path=coverage_path,
                route_index=route_index,
            )
            disposition = "created"
        reasons = _quality_reasons(
            source,
            stable_routes=stable_routes,
            seen_ids=seen_ids,
            seen_routes=seen_routes,
        )
        if not reasons:
            try:
                validate_source(source)
            except (TypeError, ValueError) as exc:
                reasons.append(
                    {"code": "schema_validation_failed", "detail": str(exc)}
                )
        if reasons:
            rejected.append(
                {
                    **_report_route(route, route_index),
                    "inferred_identity": copy.deepcopy(item["identity"]),
                    "reasons": reasons,
                }
            )
            continue
        operation_id = str(source["operation"]["operation_id"])
        seen_ids.add(operation_id)
        seen_routes.add(item["route_key"])
        accepted.append((item, source, disposition))

    draft_rows: list[dict[str, Any]] = []
    for item, source, disposition in accepted:
        operation_id = str(source["operation"]["operation_id"])
        destination = draft_root / f"{operation_id}.json"
        write_json(destination, source)
        draft_rows.append(
            {
                "operation_id": operation_id,
                "domain": source["operation"]["domain"],
                "resource": source["operation"]["resource"],
                "action": source["operation"]["action"],
                "platform": source["operation"].get("platform"),
                "method": source["operation"]["upstream_method"],
                "path": source["operation"]["path_template"],
                "coverage_reference": copy.deepcopy(
                    source["draft"]["coverage_reference"]
                ),
                "blockers": copy.deepcopy(source["draft"]["blockers"]),
                "disposition": disposition,
                "draft_path": display_path(destination),
            }
        )

    reason_counts = Counter(
        reason["code"] for row in rejected for reason in row["reasons"]
    )
    blocker_counts = Counter(
        blocker["code"] for row in draft_rows for blocker in row["blockers"]
    )
    certainty_counts = Counter(str(route.get("method_certainty", "unknown")) for _, route in excluded)
    module_counts = Counter(str(route.get("business_module", "unknown")) for _, route in excluded)
    summary = {
        "schema_version": "gravity-insight.bulk-draft-summary.v1",
        "coverage_path": display_path(coverage_path),
        "method_certainty": method_certainty,
        "attempted": len(selected),
        "successful": len(draft_rows),
        "created": sum(row["disposition"] == "created" for row in draft_rows),
        "updated_existing": sum(
            row["disposition"] == "updated_existing" for row in draft_rows
        ),
        "with_probe_evidence": sum(
            bool(source["draft"].get("probe_evidence")) for _, source, _ in accepted
        ),
        "without_probe_evidence": sum(
            not bool(source["draft"].get("probe_evidence")) for _, source, _ in accepted
        ),
        "rejected": len(rejected),
        "rejected_reason_counts": dict(sorted(reason_counts.items())),
        "blocker_counts": dict(sorted(blocker_counts.items())),
        "excluded": len(excluded),
        "excluded_certainty_counts": dict(sorted(certainty_counts.items())),
        "excluded_module_counts": dict(sorted(module_counts.items())),
        "stable_operation_contracts": len(stable_sources),
        "draft_contracts": len(list(draft_root.glob("*.json"))),
        "total_contracts": len(stable_sources) + len(list(draft_root.glob("*.json"))),
    }
    report_root.mkdir(parents=True, exist_ok=True)
    write_json(
        report_root / "drafts.json",
        {"schema_version": "gravity-insight.bulk-drafts.v1", "count": len(draft_rows), "drafts": draft_rows},
    )
    write_json(
        report_root / "rejected.json",
        {"schema_version": "gravity-insight.bulk-rejected.v1", "count": len(rejected), "routes": rejected},
    )
    excluded_rows = [_report_route(route, index) for index, route in excluded]
    write_json(
        report_root / "excluded-certainty.json",
        {
            "schema_version": "gravity-insight.bulk-excluded-certainty.v1",
            "count": len(excluded_rows),
            "certainty_counts": dict(sorted(certainty_counts.items())),
            "module_counts": dict(sorted(module_counts.items())),
            "routes": excluded_rows,
        },
    )
    summary["reports"] = {
        "drafts": display_path(report_root / "drafts.json"),
        "rejected": display_path(report_root / "rejected.json"),
        "excluded_certainty": display_path(report_root / "excluded-certainty.json"),
        "summary": display_path(report_root / "summary.json"),
    }
    write_json(report_root / "summary.json", summary)
    return summary


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

    def has(*names: str) -> bool:
        return any(name in token_set for name in names)

    def base_kind() -> str:
        if has("clear", "kill", "terminate", "delete", "remove", "dl"):
            return "delete"
        if has("approve", "audit", "examine", "review"):
            return "approve"
        if has("upload"):
            return "upload"
        if has("import"):
            return "import"
        if has("sync", "async", "handsel"):
            return "sync"
        if has("enable", "disable", "start", "stop", "cancel", "switch", "status", "change") or (
            "open" in token_set and "close" in token_set
        ):
            return "state_change"
        if has("bind", "unbind", "binding", "unbinding", "auth2user"):
            return "bind"
        if has("copy", "clone"):
            return "copy"
        if has("move", "transfer"):
            return "move"
        if has("share"):
            return "share"
        if has("submit", "execute", "push", "send", "test", "debug") or path.endswith("/event/click/"):
            return "execute"
        if has("create", "add", "append", "register", "generate"):
            return "create"
        if has(
            "update", "edit", "modify", "save", "manage", "setting", "config",
            "set", "reset", "rename", "opt", "override", "collect", "distinct",
            "mark", "use", "undelete", "restore",
        ):
            return "update"
        return "other"

    inferred = base_kind()
    batch = has("batch", "bulk", "onekey") or "one_key" in path.casefold()
    if batch:
        evidence.append("explicit_batch_path_token")
        return "batch", inferred if inferred != "other" else "other", evidence
    if inferred != "other":
        evidence.append(f"explicit_{inferred}_path_token")
    else:
        evidence.append("conservative_write_fallback")
    return inferred, None, evidence


def _mutation_risk(
    route: Mapping[str, Any], kind: str, batch_action: str | None,
    evidence: Sequence[str],
) -> dict[str, Any]:
    path = str(route.get("path", "")).casefold()
    tokens = set(_route_tokens(path))
    ui_text = " ".join(str(item) for item in route.get("ui_texts", [])).casefold()
    scope = "batch" if kind == "batch" else "unknown"
    risk_evidence = list(evidence)

    if tokens.intersection({"clear", "kill", "terminate", "resetkey"}) or "reset_key" in path:
        reversibility = "irreversible"
        risk_evidence.append("explicit_irreversible_action")
    elif kind in {"update", "state_change", "bind", "move", "share"}:
        reversibility = "reversible"
        risk_evidence.append("subsequent_mutation_can_restore_state")
    elif "undelete" in tokens or "恢复" in ui_text:
        reversibility = "reversible"
        risk_evidence.append("explicit_restore_semantics")
    else:
        reversibility = "unknown"
        risk_evidence.append("reversal_contract_not_observed")

    if kind in {"create", "upload", "import", "copy", "execute", "approve"}:
        idempotency = "non_idempotent"
    elif kind in {"update", "delete", "state_change", "bind", "move", "share"}:
        idempotency = "conditional"
    elif kind in {"sync", "batch"}:
        idempotency = "unknown"
    else:
        idempotency = "unknown"

    delivery_tokens = {
        "ad", "adgroup", "adplan", "advertisement", "advertiser", "campaign",
        "creative", "delivery", "materialpush", "plan", "project", "promotion",
        "publish", "stardelivery", "trackurl",
    }
    compact_tokens = {token.replace("_", "") for token in tokens}
    module = str(route.get("business_module", ""))
    if compact_tokens.intersection(delivery_tokens) or (
        module in {"推广平台", "归因"}
        and tokens.intersection({"postback", "attribution", "reattribution", "click", "impress"})
    ):
        affects_live_delivery = "yes"
        risk_evidence.append("delivery_or_attribution_resource")
    elif module == "App 与账号" and tokens.intersection(
        {"tutorial", "message", "password", "member", "dept", "role"}
    ):
        affects_live_delivery = "no"
        risk_evidence.append("account_administration_not_delivery")
    else:
        affects_live_delivery = "unknown"
        risk_evidence.append("live_delivery_effect_not_proven")

    if reversibility == "irreversible" or (
        affects_live_delivery == "yes"
        and (scope == "batch" or kind in {"approve", "delete", "execute", "state_change"})
    ):
        risk_level = "high"
    elif affects_live_delivery == "yes" or scope == "batch" or kind in {
        "approve", "delete", "import", "sync", "upload",
    }:
        risk_level = "medium"
    elif affects_live_delivery == "no" and reversibility == "reversible":
        risk_level = "low"
    else:
        risk_level = "unknown"

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
    if "query_api" in path or "/post/api/" in path or "/proxy/" in path:
        return "proxy", "third_party_api_proxy", "third_party_proxy_not_sdk_operation", (
            "Generic third-party API proxy routes are not exposed as atomic SDK capabilities."
        )
    if "callback_url" in path or "event_callback" in path:
        return "auth", "callback_configuration", "callback_configuration_out_of_scope", (
            "Callback configuration belongs to authentication/integration administration."
        )
    if "auth_callback" in path or "login_request" in path or "login_url" in path or "oauth_url" in path:
        return "auth", "oauth_flow", "interactive_oauth_flow", (
            "Interactive OAuth navigation and callbacks are not agent-callable API operations."
        )
    if "login" in path or "without_passwd" in path:
        return "auth", "login", "interactive_login_flow", (
            "Login and passwordless session establishment remain in the credential subsystem."
        )
    if "token" in path or "authorization" in path:
        return "auth", "credential_management", "credential_material_route", (
            "Credential and authorization material must not enter the business capability catalog."
        )
    if "auth2user" in path or "auth_user" in path or path.endswith("/auth/"):
        return "auth", "authorization_assignment", "authorization_administration", (
            "Authorization assignment is an administrative auth surface, not a business operation."
        )
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


def create_write_registry(
    *, coverage_path: Path = COVERAGE_PATH,
    reservation_root: Path = RESERVATION_ROOT,
    route_registry_path: Path = ROUTE_REGISTRY_PATH,
    report_root: Path = WRITE_REPORT_ROOT,
    overwrite: bool = False,
) -> dict[str, Any]:
    coverage = read_json(coverage_path)
    routes = coverage.get("routes")
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

    generated_at = now_utc()
    existing_ids = set(existing_operations(OPERATION_ROOT))
    existing_ids.update(path.stem for path in DRAFT_ROOT.glob("*.json"))
    reservations: list[dict[str, Any]] = []
    reservation_by_route: dict[tuple[str, str], str] = {}
    rejected: list[dict[str, Any]] = []

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

    for route_index, route in selected:
        try:
            source = _reservation_source(
                route, route_index=route_index, coverage_path=coverage_path,
                existing_ids=existing_ids, generated_at=generated_at,
            )
            operation = source["operation"]
            operation_id = str(operation["operation_id"])
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
            semantics = source["reservation"]["mutation_semantics"]
            reservations.append(
                {
                    "operation_id": operation_id,
                    "method": key[0],
                    "path": key[1],
                    "source_status": _source_route_status(route),
                    "route_index": route_index,
                    "reservation_path": display_path(destination),
                    "mutation_semantics": semantics,
                }
            )
        except (OSError, TypeError, ValueError) as exc:
            rejected.append(
                {
                    "method": route.get("method"), "path": route.get("path"),
                    "route_index": route_index, "reason": str(exc),
                }
            )

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
        decisions.append(
            {
                "method": key[0], "path": key[1], "source_status": source_status,
                "classification": classification, "subtype": subtype,
                "disposition": disposition, "reason_code": reason_code,
                "reason": reason, "operation_id": operation_id,
                "route_index": route_index,
                "route_sha256": _route_evidence_fingerprint(route),
            }
        )

    registry = {
        "schema_version": "gravity-insight.route-classification.v1",
        "generated_at": generated_at,
        "source": display_path(coverage_path),
        "routes": decisions,
    }
    _validate_route_registry(registry)
    write_json(route_registry_path, registry)

    baseline = [item for item in reservations if item["source_status"] == "uncovered_write"]
    extra = [item for item in reservations if item["source_status"] == "unclassified"]
    semantic_counts = Counter(
        item["mutation_semantics"]["kind"] for item in reservations
    )
    baseline_semantic_counts = Counter(
        item["mutation_semantics"]["kind"] for item in baseline
    )
    extra_semantic_counts = Counter(
        item["mutation_semantics"]["kind"] for item in extra
    )
    auth_counts = Counter(
        item["subtype"] for item in decisions
        if item["source_status"] == "uncovered_auth_or_proxy"
    )
    unclassified_counts = Counter(
        item["classification"] for item in decisions
        if item["source_status"] == "unclassified"
    )
    summary = {
        "schema_version": "gravity-insight.write-registry-summary.v1",
        "generated_at": generated_at,
        "source": display_path(coverage_path),
        "baseline_write_routes": len(baseline),
        "extra_unclassified_write_routes": len(extra),
        "reservations_created": len(reservations),
        "rejected": len(rejected),
        "auth_proxy_registered": sum(auth_counts.values()),
        "unclassified_registered": sum(unclassified_counts.values()),
        "mutation_semantics": dict(sorted(semantic_counts.items())),
        "baseline_mutation_semantics": dict(sorted(baseline_semantic_counts.items())),
        "extra_mutation_semantics": dict(sorted(extra_semantic_counts.items())),
        "risk": {
            "irreversible": sum(
                item["mutation_semantics"]["reversibility"] == "irreversible"
                for item in reservations
            ),
            "batch": sum(
                item["mutation_semantics"]["scope"] == "batch"
                for item in reservations
            ),
            "affects_live_delivery": sum(
                item["mutation_semantics"]["affects_live_delivery"] == "yes"
                for item in reservations
            ),
        },
        "baseline_risk": {
            "irreversible": sum(
                item["mutation_semantics"]["reversibility"] == "irreversible"
                for item in baseline
            ),
            "batch": sum(
                item["mutation_semantics"]["scope"] == "batch"
                for item in baseline
            ),
            "affects_live_delivery": sum(
                item["mutation_semantics"]["affects_live_delivery"] == "yes"
                for item in baseline
            ),
        },
        "extra_risk": {
            "irreversible": sum(
                item["mutation_semantics"]["reversibility"] == "irreversible"
                for item in extra
            ),
            "batch": sum(
                item["mutation_semantics"]["scope"] == "batch"
                for item in extra
            ),
            "affects_live_delivery": sum(
                item["mutation_semantics"]["affects_live_delivery"] == "yes"
                for item in extra
            ),
        },
        "auth_proxy_subtypes": dict(sorted(auth_counts.items())),
        "unclassified_classifications": dict(sorted(unclassified_counts.items())),
    }
    write_json(
        report_root / "write-reservations.json",
        {"schema_version": "gravity-insight.write-reservations.v1", "routes": reservations},
    )
    write_json(
        report_root / "auth-proxy.json",
        {
            "schema_version": "gravity-insight.auth-proxy-classification.v1",
            "routes": [
                item for item in decisions
                if item["source_status"] == "uncovered_auth_or_proxy"
            ],
        },
    )
    write_json(
        report_root / "unclassified.json",
        {
            "schema_version": "gravity-insight.unclassified-resolution.v1",
            "routes": [
                item for item in decisions if item["source_status"] == "unclassified"
            ],
        },
    )
    write_json(
        report_root / "rejected.json",
        {"schema_version": "gravity-insight.write-rejected.v1", "routes": rejected},
    )
    write_json(report_root / "summary.json", summary)
    return summary


def _apply_method_evidence(
    coverage: Mapping[str, Any], evidence: Mapping[str, Any]
) -> dict[str, Any]:
    updated = copy.deepcopy(dict(coverage))
    route_section = evidence.get("routes")
    observed = route_section.get("results") if isinstance(route_section, Mapping) else None
    if not isinstance(observed, list):
        raise ValueError("method evidence has no routes.results array")
    methods: dict[str, str] = {}
    for item in observed:
        options = item.get("options") if isinstance(item, Mapping) else None
        allow = options.get("allow") if isinstance(options, Mapping) else None
        candidates = [str(value).upper() for value in allow] if isinstance(allow, list) else []
        accepted = [value for value in candidates if value in {"GET", "POST"}]
        if len(accepted) == 1 and isinstance(item.get("path"), str):
            methods[str(item["path"])] = accepted[0]
    routes = updated.get("routes")
    if not isinstance(routes, list):
        raise ValueError("coverage.json has no routes array")
    for route in routes:
        if not isinstance(route, dict) or route.get("path") not in methods:
            continue
        route["method"] = methods[str(route["path"])]
        route["method_certainty"] = "high"
        current = route.get("method_evidence")
        values = [str(value) for value in current] if isinstance(current, list) else []
        route["method_evidence"] = sorted(set(values + ["live_options_allow"]))
    return updated
