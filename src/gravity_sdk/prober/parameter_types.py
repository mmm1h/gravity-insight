"""Normalize ambiguous frontend parameter observations into probe-safe fields."""

from __future__ import annotations

import copy
import re
from typing import Any, Mapping


MISSING = object()
_DESCRIPTION_MARKER = "Frontend-observed candidate"
_PARAMETER_GROUPS = (
    ("path", "path_parameters", "path_fields"),
    ("query", "query_parameters", "query_fields"),
    ("body", "body_parameters", "body_fields"),
)
_VALID_PARAMETER_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_INTEGER_PAGINATION_FIELDS = {
    "current_page",
    "limit",
    "page",
    "page_no",
    "page_num",
    "page_number",
    "page_size",
    "pagesize",
    "size",
}


def _field(
    type_name: str, *, default: Any = None, required: bool = False,
) -> dict[str, Any]:
    value: dict[str, Any] = {"type": type_name}
    if required:
        value["required"] = True
    elif default is not None:
        value["default"] = default
    return value


def _option_contract(
    platform: Any, existing_ids: set[str],
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
        parents.append({
            "operation_id": parent_id, "input_field": "advertiser_id",
            "output_path": "data.list[].advertiser_id", "selection": "caller_select",
        })
        placeholder = (
            f"$first_{platform}_advertiser_id"
            if platform in {"bytedance", "tencent", "kuaishou"} else "$parent"
        )
        probe_inputs["advertiser_id"] = (
            [placeholder] if input_type == "array" else placeholder
        )
    return fields, probe_inputs, parents


def _report_contract() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    fields = {
        "date_list": _field("array", required=True),
        "filtering": _field("object", default={}),
        "filters": _field("array", default=[]),
        "order_by": _field("array", default=[]),
        "page": _field("integer", default=1),
        "page_size": _field("integer", default=10),
        "query_fields": _field("array", default=[]),
    }
    defaults = {
        "filtering": {}, "filters": [], "order_by": [], "page": 1,
        "page_size": 10, "query_fields": [],
    }
    return fields, defaults, {
        **defaults, "date_list": ["$yesterday", "$today"], "page_size": 2,
    }


def _openapi_adreport_contract(
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
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
        **defaults, "time_dims": "day", "date_list": ["$today", "$today"],
        "metrics_list": ["ap_cost"],
        "filters": [
            {"field": "app_id", "operator": "EQUALS", "values": ["$first_app_id"]}
        ],
    }
    return fields, defaults, probe_inputs


def _openapi_metric_contract(
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
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
    return fields, defaults, {**defaults, "metric_type": "gravity_preset"}


def infer_contract_parts(
    route: Mapping[str, Any], identity: Mapping[str, Any], existing_ids: set[str],
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
        body_fields.extend([
            "filtering", "page", "page_size", "query_fields",
            "date_list", "order_by", "filters",
        ])
    elif path.endswith("/list/") and not any(
        token in path for token in ("/datamanageconfig/", "/const/", "/health_status/")
    ):
        fields.update({
            "page": _field("integer", default=1),
            "page_size": _field("integer", default=20),
        })
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


def auth_profile(path: str) -> str:
    if not path.startswith("/openapi/api/v1/"):
        return "gravity_authorization"
    if any(segment in path for segment in ("/open_develop/", "/open_app/")):
        return "gravity_authorization"
    return "gravity_openapi_signature"


def initial_gate_missing(path: str, auth: str) -> list[str]:
    missing = ["successful_probe", "classified_projection", "response_projection"]
    if path.startswith("/openapi/"):
        missing.append("stable_runtime_route_unsupported")
    if auth == "gravity_openapi_signature":
        missing.append("openapi_developer_credentials_unavailable")
    return sorted(missing)


def _observed_methods(evidence: Mapping[str, Any]) -> dict[str, str]:
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
    return methods


def apply_method_evidence(
    coverage: Mapping[str, Any], evidence: Mapping[str, Any],
) -> dict[str, Any]:
    updated = copy.deepcopy(dict(coverage))
    methods = _observed_methods(evidence)
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


def value_type(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, Mapping):
        return "object"
    return "any"


def field_accepts_value(field: Mapping[str, Any], value: Any) -> bool:
    if isinstance(value, str) and value.startswith("$"):
        return True
    if value is None:
        return bool(field.get("nullable", False))
    declared = str(field.get("type", "any"))
    actual = value_type(value)
    return (
        declared == "any"
        or declared == actual
        or (declared == "number" and actual == "integer")
        or (declared in {"date", "datetime"} and actual == "string")
    )


def top_level_parameters(route: Mapping[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for location, source_key, request_key in _PARAMETER_GROUPS:
        parameters = route.get(source_key, [])
        if not isinstance(parameters, list):
            continue
        for parameter in parameters:
            if not isinstance(parameter, Mapping):
                continue
            name = str(parameter.get("name", ""))
            if (
                str(parameter.get("path", "")) != f"$.{name}"
                or not _VALID_PARAMETER_NAME.fullmatch(name)
            ):
                continue
            result.append(
                {
                    **copy.deepcopy(dict(parameter)),
                    "location": location,
                    "request_key": request_key,
                }
            )
    return result


def field_type(parameter: Mapping[str, Any]) -> str:
    observed = {
        str(item) for item in parameter.get("types", []) if isinstance(item, str)
    }
    name = str(parameter.get("name", "")).casefold()
    if name in _INTEGER_PAGINATION_FIELDS:
        return "integer"
    if "default" in parameter:
        default_type = value_type(parameter["default"])
        if (
            default_type == "number"
            and isinstance(parameter["default"], float)
            and parameter["default"].is_integer()
            and "integer" in observed
        ):
            default_type = "integer"
        if default_type in observed:
            return default_type
    for candidate in (
        "array",
        "object",
        "boolean",
        "integer",
        "number",
        "string",
    ):
        if candidate in observed:
            return candidate
    return "any"


def _item_type(parameter: Mapping[str, Any]) -> str | None:
    items = parameter.get("items")
    if not isinstance(items, Mapping):
        return None
    selected = field_type(items)
    allowed = {"string", "integer", "number", "boolean", "object"}
    return selected if selected in allowed else None


def candidate_value(parameter: Mapping[str, Any]) -> Any:
    if "default" in parameter:
        value = copy.deepcopy(parameter["default"])
        if (
            field_type(parameter) == "integer"
            and isinstance(value, float)
            and value.is_integer()
        ):
            return int(value)
        return value
    if parameter.get("required") != "observed_always":
        return MISSING
    name = str(parameter.get("name", "")).casefold()
    inferred_type = field_type(parameter)
    if name in {"page", "page_no", "page_num", "page_number", "current_page"}:
        return 1
    if name in {"page_size", "pagesize", "limit", "size"}:
        return 20
    if name in {"start_date", "begin_date", "date_start"}:
        return "$yesterday"
    if name in {"end_date", "date_end", "date"}:
        return "$today"
    if inferred_type == "array":
        return []
    if inferred_type == "object":
        return {}
    if inferred_type == "boolean":
        return False
    if inferred_type in {"integer", "number", "any"}:
        return 0
    return ""


def reconcile_field(
    existing: Any, parameter: Mapping[str, Any]
) -> tuple[dict[str, Any], Any]:
    """Repair inferred type/default conflicts without overriding valid manual types."""

    field = dict(existing) if isinstance(existing, Mapping) else {}
    inferred_type = field_type(parameter)
    candidate = candidate_value(parameter)
    current_type = str(field.get("type", "any"))
    candidate_type = value_type(candidate) if candidate is not MISSING else None
    compatible = candidate_type is None or field_accepts_value(field, candidate)
    if not field.get("type") or field.get("type") == "any" or not compatible:
        field["type"] = inferred_type
    if field.get("type") != "array":
        for key in ("item_type", "item_enum", "min_items", "max_items"):
            field.pop(key, None)
    elif not field.get("item_type"):
        item_type = _item_type(parameter)
        if item_type:
            field["item_type"] = item_type
    return field, candidate


def merge_description(existing: Any, observed: str) -> str:
    current = str(existing or "").strip()
    if _DESCRIPTION_MARKER in current:
        current = current.split(_DESCRIPTION_MARKER, 1)[0].rstrip(" ;")
    return f"{current}; {observed}" if current else observed


def parameter_metadata(parameter: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "name": str(parameter["name"]),
        "location": str(parameter["location"]),
        "path": str(parameter.get("path", "")),
        "types": [str(item) for item in parameter.get("types", [])],
        "confidence": str(parameter.get("confidence", "unknown")),
        "presence": str(parameter.get("required", "unknown")),
        "default_observed": "default" in parameter,
    }


def apply_parameter(operation: dict[str, Any], parameter: Mapping[str, Any]) -> str:
    name = str(parameter["name"])
    field, candidate = reconcile_field(operation["input_fields"].get(name), parameter)
    if "default" in parameter:
        field["default"] = copy.deepcopy(candidate)
        operation["request"]["defaults"][name] = copy.deepcopy(candidate)
    confidence = str(parameter.get("confidence", "unknown"))
    presence = str(parameter.get("required", "unknown"))
    description = (
        f"{_DESCRIPTION_MARKER} from route-params.json "
        f"(confidence={confidence}, presence={presence}); "
        "presence describes frontend calls and is not a server-required declaration."
    )
    field["description"] = merge_description(field.get("description"), description)
    operation["input_fields"][name] = field

    request = operation["request"]
    binding = str(parameter["request_key"])
    for other in ("path_fields", "query_fields", "body_fields"):
        if other != binding:
            request[other] = [item for item in request.get(other, []) if item != name]
    request[binding] = sorted(set(request.get(binding, [])) | {name})
    probe_inputs = operation["live_probe"]["inputs"]
    existing_probe = probe_inputs.get(name, MISSING)
    observed_default = parameter.get("default", MISSING)
    generated_default = (
        observed_default is not MISSING
        and existing_probe is not MISSING
        and value_type(existing_probe) == value_type(observed_default)
        and existing_probe == observed_default
    )
    incompatible_literal = (
        existing_probe is not MISSING
        and not field_accepts_value(field, existing_probe)
    )
    if candidate is not MISSING and (
        existing_probe is MISSING or generated_default or incompatible_literal
    ):
        probe_inputs[name] = candidate
    return confidence


def validate_operation_bindings(operation: Mapping[str, Any]) -> None:
    fields = operation.get("input_fields", {})
    if not isinstance(fields, Mapping):
        return
    request = operation.get("request", {})
    live_probe = operation.get("live_probe", {})
    bindings = (
        (
            "input_fields",
            {
                name: field["default"]
                for name, field in fields.items()
                if isinstance(field, Mapping) and "default" in field
            },
        ),
        (
            "request.defaults",
            request.get("defaults", {}) if isinstance(request, Mapping) else {},
        ),
        (
            "live_probe.inputs",
            live_probe.get("inputs", {}) if isinstance(live_probe, Mapping) else {},
        ),
    )
    for source, values in bindings:
        if not isinstance(values, Mapping):
            continue
        for name, value in values.items():
            field = fields.get(name)
            if isinstance(field, Mapping) and not field_accepts_value(field, value):
                declared = str(field.get("type", "any"))
                raise ValueError(
                    f"operation.{source}.{name} conflicts with declared type {declared}"
                )


def validate_source_contract(source: Mapping[str, Any]) -> None:
    from gravity_sdk.compiler import ContractCompiler

    ContractCompiler().operation_schema.validate(source)
    validate_operation_bindings(source["operation"])
