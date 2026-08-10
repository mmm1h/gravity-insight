"""Apply frontend-observed route parameter contracts to probe drafts.
Static census input is package data; generated probe output uses workspace state."""

from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from gravity_sdk.paths import CENSUS_DATA_ROOT

from .core import DRAFT_ROOT, OPERATION_ROOT, canonical_fingerprint, read_json
from .promotion import save_draft


ROUTE_PARAMETERS_PATH = CENSUS_DATA_ROOT / "route-params.json"

_PARAMETER_GROUPS = (
    ("path", "path_parameters", "path_fields"),
    ("query", "query_parameters", "query_fields"),
    ("body", "body_parameters", "body_fields"),
)
_VALID_PARAMETER_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_RESERVED_EXTRA_KEYS = {
    "code",
    "detail",
    "error",
    "errors",
    "field",
    "fields",
    "message",
    "msg",
    "request_id",
    "status",
    "trace_id",
}
_DESCRIPTION_MARKER = "Frontend-observed candidate"
_MISSING = object()


def _route_key(method: Any, path: Any) -> tuple[str, str]:
    return str(method).upper(), str(path)


def load_route_parameter_contracts(
    path: Path = ROUTE_PARAMETERS_PATH,
) -> dict[tuple[str, str], Mapping[str, Any]]:
    payload = read_json(path)
    routes = payload.get("routes", []) if isinstance(payload, Mapping) else []
    return {
        _route_key(route.get("method"), route.get("path")): route
        for route in routes
        if isinstance(route, Mapping)
    }


def _top_level(parameter: Mapping[str, Any]) -> bool:
    path = str(parameter.get("path", ""))
    name = str(parameter.get("name", ""))
    return path == f"$.{name}" and bool(_VALID_PARAMETER_NAME.fullmatch(name))


def top_level_parameters(route: Mapping[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for location, source_key, request_key in _PARAMETER_GROUPS:
        parameters = route.get(source_key, [])
        if not isinstance(parameters, list):
            continue
        for parameter in parameters:
            if not isinstance(parameter, Mapping) or not _top_level(parameter):
                continue
            result.append(
                {
                    **copy.deepcopy(dict(parameter)),
                    "location": location,
                    "request_key": request_key,
                }
            )
    return result


def _field_type(parameter: Mapping[str, Any]) -> str:
    observed = {
        str(item) for item in parameter.get("types", []) if isinstance(item, str)
    }
    for candidate in (
        "array", "object", "boolean", "integer", "number", "string"
    ):
        if candidate in observed:
            return candidate
    return "any"


def _item_type(parameter: Mapping[str, Any]) -> str | None:
    items = parameter.get("items")
    if not isinstance(items, Mapping):
        return None
    selected = _field_type(items)
    return selected if selected in {"string", "integer", "number", "boolean", "object"} else None


def _candidate_value(parameter: Mapping[str, Any]) -> Any:
    if "default" in parameter:
        return copy.deepcopy(parameter["default"])
    if parameter.get("required") != "observed_always":
        return _MISSING
    name = str(parameter.get("name", "")).casefold()
    field_type = _field_type(parameter)
    if name in {"page", "page_no", "page_num", "page_number", "current_page"}:
        return 1
    if name in {"page_size", "pagesize", "limit", "size"}:
        return 20
    if name in {"start_date", "begin_date", "date_start"}:
        return "$yesterday"
    if name in {"end_date", "date_end", "date"}:
        return "$today"
    if field_type == "array":
        return []
    if field_type == "object":
        return {}
    if field_type == "boolean":
        return False
    if field_type in {"integer", "number", "any"}:
        return 0
    return ""


def _field_description(parameter: Mapping[str, Any]) -> str:
    confidence = str(parameter.get("confidence", "unknown"))
    presence = str(parameter.get("required", "unknown"))
    return (
        f"{_DESCRIPTION_MARKER} from route-params.json "
        f"(confidence={confidence}, presence={presence}); "
        "presence describes frontend calls and is not a server-required declaration."
    )


def _merge_description(existing: Any, observed: str) -> str:
    current = str(existing or "").strip()
    if _DESCRIPTION_MARKER in current:
        current = current.split(_DESCRIPTION_MARKER, 1)[0].rstrip(" ;")
    return f"{current}; {observed}" if current else observed


def _metadata_parameter(parameter: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "name": str(parameter["name"]),
        "location": str(parameter["location"]),
        "path": str(parameter.get("path", "")),
        "types": [str(item) for item in parameter.get("types", [])],
        "confidence": str(parameter.get("confidence", "unknown")),
        "presence": str(parameter.get("required", "unknown")),
        "default_observed": "default" in parameter,
    }


def assemble_source_parameters(
    source: Mapping[str, Any], route: Mapping[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Merge one static frontend contract without claiming server requiredness."""

    updated = copy.deepcopy(dict(source))
    operation = updated["operation"]
    input_fields = operation["input_fields"]
    request = operation["request"]
    probe_inputs = operation["live_probe"]["inputs"]
    parameters = top_level_parameters(route)
    confidence_counts = {"high": 0, "medium": 0}
    for parameter in parameters:
        name = str(parameter["name"])
        confidence = str(parameter.get("confidence", "unknown"))
        if confidence in confidence_counts:
            confidence_counts[confidence] += 1
        existing = input_fields.get(name)
        field = dict(existing) if isinstance(existing, Mapping) else {}
        observed_type = _field_type(parameter)
        if not field.get("type") or field.get("type") == "any":
            field["type"] = observed_type
        if observed_type == "array" and not field.get("item_type"):
            item_type = _item_type(parameter)
            if item_type:
                field["item_type"] = item_type
        if "default" in parameter:
            field["default"] = copy.deepcopy(parameter["default"])
            request["defaults"][name] = copy.deepcopy(parameter["default"])
        field["description"] = _merge_description(
            field.get("description"), _field_description(parameter)
        )
        input_fields[name] = field
        binding = str(parameter["request_key"])
        for other_binding in ("path_fields", "query_fields", "body_fields"):
            if other_binding != binding:
                request[other_binding] = [
                    item for item in request.get(other_binding, []) if item != name
                ]
        request[binding] = sorted(set(request.get(binding, [])) | {name})
        candidate = _candidate_value(parameter)
        if candidate is not _MISSING:
            if "default" in parameter or name not in probe_inputs:
                probe_inputs[name] = candidate

    analysis = route.get("analysis", {})
    call_sites = analysis.get("call_sites", []) if isinstance(analysis, Mapping) else []
    route_evidence = updated["draft"].setdefault("route_evidence", {})
    prior = route_evidence.get("parameter_contract", {})
    learned = prior.get("learned_parameters", []) if isinstance(prior, Mapping) else []
    route_evidence["parameter_contract"] = {
        "source": "src/gravity_sdk/census/data/route-params.json",
        "route": {"method": str(route.get("method", "")), "path": str(route.get("path", ""))},
        "status": str(route.get("status", "unknown")),
        "contract_confidence": str(route.get("contract_confidence", "unknown")),
        "top_level_parameters": [_metadata_parameter(item) for item in parameters],
        "call_sites": copy.deepcopy(call_sites) if isinstance(call_sites, list) else [],
        "required_semantics": "frontend_observation_only",
        "learned_parameters": list(learned) if isinstance(learned, list) else [],
    }
    applied = operation.get("provenance", {}).get("applied_overrides", [])
    marker = "frontend_route_parameter_contract"
    if marker not in applied:
        operation["provenance"]["applied_overrides"] = [*applied, marker]
    return updated, {
        "parameter_count": len(parameters),
        "high_confidence": confidence_counts["high"],
        "medium_confidence": confidence_counts["medium"],
        "has_high_confidence": confidence_counts["high"] > 0,
        "has_medium_confidence": confidence_counts["medium"] > 0,
    }


def assemble_draft_parameters(
    *, draft_root: Path = DRAFT_ROOT,
    route_parameters_path: Path = ROUTE_PARAMETERS_PATH,
    operation_ids: Sequence[str] = (),
) -> dict[str, Any]:
    contracts = load_route_parameter_contracts(route_parameters_path)
    selected = set(operation_ids)
    rows: list[dict[str, Any]] = []
    changed = 0
    for path in sorted(draft_root.glob("*.json")):
        if selected and path.stem not in selected:
            continue
        source = read_json(path)
        coverage = source.get("draft", {}).get("coverage_reference", {})
        key = _route_key(
            coverage.get("method", source["operation"].get("upstream_method")),
            coverage.get("path", source["operation"].get("path_template")),
        )
        route = contracts.get(key)
        if not route:
            continue
        parameters = top_level_parameters(route)
        if not parameters:
            continue
        before = canonical_fingerprint(source)
        updated, stats = assemble_source_parameters(source, route)
        after = canonical_fingerprint(updated)
        if before != after:
            save_draft(updated, draft_root)
            changed += 1
        rows.append({"operation_id": path.stem, "changed": before != after, **stats})
    return {
        "schema_version": "gravity-insight.parameter-assembly.v1",
        "drafts_assembled": len(rows),
        "drafts_changed": changed,
        "parameters_assembled": sum(item["parameter_count"] for item in rows),
        "high_confidence_parameters": sum(item["high_confidence"] for item in rows),
        "medium_confidence_parameters": sum(item["medium_confidence"] for item in rows),
        "drafts_with_high_confidence": sum(item["has_high_confidence"] for item in rows),
        "drafts_with_medium_confidence": sum(item["has_medium_confidence"] for item in rows),
        "operations": rows,
    }


def _parent_candidate(
    field_name: str, platform: str | None, stable_ids: set[str]
) -> tuple[str, str] | None:
    if field_name == "app_id" and "app.list" in stable_ids:
        return "app.list", "data.list[].id"
    if field_name in {"user_id", "examine_user_id"} and "analysis.account_user.list" in stable_ids:
        return "analysis.account_user.list", "data.list[].user_id"
    if field_name in {"material_id", "material_ids"} and "material.local.list" in stable_ids:
        return "material.local.list", "data.list[].material_id"
    if field_name == "album_id" and "material.album.tree" in stable_ids:
        return "material.album.tree", "data.tree..id"
    if field_name == "promotion_id" and platform == "bytedance":
        operation_id = "promotion.bytedance.promotion_filter.list"
        if operation_id in stable_ids:
            return operation_id, "data.list[].promotion_id"
    if field_name == "project_id" and platform == "bytedance":
        operation_id = "promotion.bytedance.project_filter.list"
        if operation_id in stable_ids:
            return operation_id, "data.list[].project_id"
    if field_name == "adgroup_id" and platform == "tencent":
        operation_id = "promotion.tencent.adgroup_filter.list"
        if operation_id in stable_ids:
            return operation_id, "data.list[].adgroup_id"
    if field_name in {"advertiser_id", "advertiser_ids"} and platform == "bytedance":
        operation_id = "promotion.bytedance.project_filter.list"
        if operation_id in stable_ids:
            return operation_id, "data.list[].advertiser_id"
    if field_name in {"advertiser_id", "advertiser_ids"} and platform == "tencent":
        operation_id = "promotion.tencent.adgroup_filter.list"
        if operation_id in stable_ids:
            return operation_id, "data.list[].advertiser_id"
    if field_name == "campaign_id" and platform == "honor":
        operation_id = "promotion.honor.campaign.list"
        if operation_id in stable_ids:
            return operation_id, "data.list[].campaign_id"
    if platform:
        operation_id = f"promotion.{platform}.advertiser.list"
        output_names = {
            "advertiser_id": "advertiser_id",
            "unit_id": "ad_unit_id",
        }
        output_name = output_names.get(field_name)
        if operation_id in stable_ids and output_name:
            return operation_id, f"data.list[].{output_name}"
    return None


def bind_stable_parent_candidates(
    *, draft_root: Path = DRAFT_ROOT, operation_root: Path = OPERATION_ROOT,
    operation_ids: Sequence[str] = (),
) -> dict[str, Any]:
    """Bind exact ID fields to stable read operations without persisting values."""

    stable_ids = {
        str(source["operation"]["operation_id"])
        for path in operation_root.glob("*.json")
        for source in [read_json(path)]
        if source.get("operation", {}).get("stability") == "stable"
    }
    selected = set(operation_ids)
    rows: list[dict[str, Any]] = []
    for path in sorted(draft_root.glob("*.json")):
        if selected and path.stem not in selected:
            continue
        source = read_json(path)
        operation = source["operation"]
        platform = operation.get("platform")
        original_parents = copy.deepcopy(operation.get("required_parent", []))
        existing_parents = operation.get("required_parent", [])
        automatic = "stable_parent_candidate_binding" in operation.get(
            "provenance", {}
        ).get("applied_overrides", [])
        if automatic:
            existing_parents = []
        bound_fields = {
            str(item.get("input_field"))
            for item in existing_parents
            if isinstance(item, Mapping) and item.get("input_field")
        }
        bindings: list[dict[str, Any]] = []
        for field_name in operation.get("input_fields", {}):
            if field_name in bound_fields:
                continue
            candidate = _parent_candidate(
                str(field_name), str(platform) if platform else None, stable_ids
            )
            if candidate is None:
                continue
            parent_operation, output_path = candidate
            parent = {
                "operation_id": parent_operation,
                "input_field": str(field_name),
                "output_path": output_path,
                "selection": (
                    "all"
                    if operation["input_fields"][field_name].get("type") == "array"
                    else "caller_select"
                ),
            }
            existing_parents.append(parent)
            operation["live_probe"]["inputs"][str(field_name)] = (
                f"$parent:{field_name}"
            )
            bindings.append(parent)
        if automatic:
            old_fields = {
                str(item.get("input_field"))
                for item in operation.get("required_parent", [])
                if isinstance(item, Mapping) and item.get("input_field")
            }
            new_fields = {str(item["input_field"]) for item in bindings}
            metadata = {
                str(item.get("name")): item
                for item in source.get("draft", {})
                .get("route_evidence", {})
                .get("parameter_contract", {})
                .get("top_level_parameters", [])
                if isinstance(item, Mapping) and item.get("name")
            }
            for removed_field in sorted(old_fields - new_fields):
                parameter = metadata.get(removed_field)
                candidate = _candidate_value(parameter) if parameter else 0
                operation["live_probe"]["inputs"][removed_field] = (
                    0 if candidate is _MISSING else candidate
                )
        operation["required_parent"] = existing_parents
        if not bindings and not automatic:
            continue
        contract = (
            source["draft"].setdefault("route_evidence", {})
            .setdefault("parameter_contract", {})
        )
        contract["stable_parent_candidates"] = copy.deepcopy(bindings)
        if original_parents != existing_parents:
            source["draft"]["route_evidence"].pop("parent_resolution", None)
        applied = operation["provenance"].get("applied_overrides", [])
        marker = "stable_parent_candidate_binding"
        if marker not in applied:
            operation["provenance"]["applied_overrides"] = [*applied, marker]
        save_draft(source, draft_root)
        rows.append(
            {"operation_id": path.stem, "bindings": copy.deepcopy(bindings)}
        )
    return {
        "schema_version": "gravity-insight.parent-candidate-binding.v1",
        "drafts_bound": len(rows),
        "bindings": sum(len(item["bindings"]) for item in rows),
        "operations": rows,
    }


def apply_stable_request_patterns(
    *, draft_root: Path = DRAFT_ROOT, operation_ids: Sequence[str] = (),
) -> dict[str, Any]:
    """Apply candidate values already proven by closely related stable reads."""

    selected = set(operation_ids)
    rows: list[dict[str, Any]] = []
    for path in sorted(draft_root.glob("*.json")):
        if selected and path.stem not in selected:
            continue
        source = read_json(path)
        operation = source["operation"]
        inputs = operation["live_probe"]["inputs"]
        date_list = inputs.get("date_list", _MISSING)
        if date_list is _MISSING or not (
            date_list is None or date_list == "" or date_list == 0
        ):
            continue
        inputs["date_list"] = ["$today", "$today"]
        field = dict(operation["input_fields"].get("date_list", {}))
        field["type"] = "array"
        field["item_type"] = "string"
        field.pop("default", None)
        field["description"] = _merge_description(
            field.get("description"),
            (
                "Probe candidate aligned with the verified stable report request "
                "pattern; not a server-required declaration."
            ),
        )
        operation["input_fields"]["date_list"] = field
        operation["request"].get("defaults", {}).pop("date_list", None)
        contract = (
            source["draft"].setdefault("route_evidence", {})
            .setdefault("parameter_contract", {})
        )
        adjustments = contract.setdefault("stable_pattern_adjustments", [])
        adjustment = {
            "field": "date_list",
            "pattern_source": "verified_stable_report_operations",
            "candidate_shape": "array<string>",
            "server_required_claimed": False,
        }
        if adjustment not in adjustments:
            adjustments.append(adjustment)
        applied = operation["provenance"].get("applied_overrides", [])
        marker = "stable_report_request_pattern"
        if marker not in applied:
            operation["provenance"]["applied_overrides"] = [*applied, marker]
        save_draft(source, draft_root)
        rows.append({"operation_id": path.stem, "field": "date_list"})
    return {
        "schema_version": "gravity-insight.stable-request-pattern.v1",
        "drafts_adjusted": len(rows),
        "operations": rows,
    }


def _known_parameter_metadata(source: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    contract = (
        source.get("draft", {}).get("route_evidence", {}).get("parameter_contract", {})
    )
    parameters = contract.get("top_level_parameters", []) if isinstance(contract, Mapping) else []
    return {
        str(item.get("name")): item
        for item in parameters
        if isinstance(item, Mapping) and item.get("name")
    }


def _string_values(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, Mapping):
        return [item for child in value.values() for item in _string_values(child)]
    if isinstance(value, list):
        return [item for child in value for item in _string_values(child)]
    return []


def parameter_hints_from_error(
    payload: Any, *, known_parameters: Sequence[str] = ()
) -> list[dict[str, str]]:
    """Extract parameter names in memory; never retain response messages or values."""

    if not isinstance(payload, Mapping) or str(payload.get("code")) not in {"1003", "1004"}:
        return []
    extra = payload.get("extra")
    if not isinstance(extra, Mapping):
        return []
    hints: dict[str, dict[str, str]] = {}
    for name in extra:
        normalized = str(name)
        if (
            normalized.casefold() not in _RESERVED_EXTRA_KEYS
            and _VALID_PARAMETER_NAME.fullmatch(normalized)
        ):
            hints[normalized] = {
                "field": normalized,
                "basis": "semantic_error_extra_key",
            }
    text = "\n".join(_string_values(extra))
    for name in known_parameters:
        if _VALID_PARAMETER_NAME.fullmatch(name) and re.search(
            rf"(?<![A-Za-z0-9_]){re.escape(name)}(?![A-Za-z0-9_])", text
        ):
            hints.setdefault(
                name,
                {"field": name, "basis": "semantic_error_known_parameter_mention"},
            )
    return [hints[name] for name in sorted(hints)]


def _retry_value(field: Mapping[str, Any], current: Any, retry_index: int) -> Any:
    field_type = str(field.get("type", "any"))
    if field_type == "array":
        return [{}] if retry_index == 1 else [0]
    if field_type == "object":
        return {"id": 0} if retry_index == 1 else {"id": 1}
    if field_type == "boolean":
        return not bool(current)
    if field_type in {"integer", "number", "any"}:
        return retry_index
    return str(retry_index)


def apply_error_learning(
    source: Mapping[str, Any], payload: Any, *, retry_index: int,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Apply one value-free retry adjustment learned from a semantic error."""

    updated = copy.deepcopy(dict(source))
    operation = updated["operation"]
    metadata = _known_parameter_metadata(updated)
    hints = parameter_hints_from_error(payload, known_parameters=tuple(metadata))
    inputs = operation["live_probe"]["inputs"]
    parameter_contract = updated["draft"].setdefault(
        "route_evidence", {}
    ).setdefault(
        "parameter_contract",
        {
            "source": "live_semantic_error",
            "status": "probe_learned",
            "top_level_parameters": [],
        },
    )
    learned = parameter_contract.setdefault("learned_parameters", [])
    changed_fields: list[str] = []
    bases: dict[str, str] = {}
    candidate_types: dict[str, str] = {}
    for hint in hints:
        name = hint["field"]
        field = operation["input_fields"].get(name)
        if not isinstance(field, Mapping):
            parameter = metadata.get(name, {})
            inferred_type = _field_type(parameter) if parameter else "any"
            field = {
                "type": inferred_type,
                "description": (
                    "Probe-learned candidate from a semantic missing-parameter shape; "
                    "not a server-required declaration."
                ),
            }
            operation["input_fields"][name] = field
        location = str(metadata.get(name, {}).get("location", ""))
        if location not in {"path", "query", "body"}:
            location = "query" if operation["upstream_method"] == "GET" else "body"
        request_key = f"{location}_fields"
        operation["request"][request_key] = sorted(
            set(operation["request"].get(request_key, [])) | {name}
        )
        inputs[name] = _retry_value(field, inputs.get(name), retry_index)
        if name not in learned:
            learned.append(name)
        changed_fields.append(name)
        bases[name] = hint["basis"]
        candidate_types[name] = str(field.get("type", "any"))
    if changed_fields:
        return updated, {
            "retry": retry_index,
            "action": "add_or_change_candidates",
            "field": changed_fields[0],
            "fields": changed_fields,
            "basis": bases[changed_fields[0]],
            "basis_by_field": bases,
            "candidate_type": candidate_types[changed_fields[0]],
            "candidate_types": candidate_types,
            "response_values_persisted": False,
        }

    # Without a field hint, only remove a medium-confidence conditional input.
    for name, parameter in metadata.items():
        if (
            parameter.get("confidence") == "medium"
            and parameter.get("presence") != "observed_always"
            and name in inputs
        ):
            inputs.pop(name, None)
            return updated, {
                "retry": retry_index,
                "action": "omit_medium_confidence_candidate",
                "field": name,
                "basis": "semantic_error_without_parameter_hint",
                "candidate_type": str(operation["input_fields"].get(name, {}).get("type", "any")),
                "response_values_persisted": False,
            }
    return updated, None


__all__ = [
    "ROUTE_PARAMETERS_PATH",
    "apply_error_learning",
    "assemble_draft_parameters",
    "assemble_source_parameters",
    "apply_stable_request_patterns",
    "bind_stable_parent_candidates",
    "load_route_parameter_contracts",
    "parameter_hints_from_error",
    "top_level_parameters",
]
