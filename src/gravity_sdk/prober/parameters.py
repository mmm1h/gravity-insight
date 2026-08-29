"""Apply frontend-observed route parameter contracts to probe drafts.
Static census input is package data; generated probe output uses workspace state."""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from gravity_sdk.paths import CENSUS_DATA_ROOT, CONTRACT_ROOT

from .core import DRAFT_ROOT, OPERATION_ROOT, canonical_fingerprint, read_json
from .parameter_types import MISSING as _MISSING
from .parameter_types import apply_parameter
from .parameter_types import field_type as _field_type
from .parameter_types import merge_description as _merge_description
from .parameter_types import parameter_metadata as _metadata_parameter
from .parameter_types import top_level_parameters
from .parent_bindings import (
    automatic_parent_state,
    restore_removed_parent_inputs,
)
from .promotion import save_draft


ROUTE_PARAMETERS_PATH = CENSUS_DATA_ROOT / "route-params.json"
_PROBER_BINDINGS = json.loads(
    (CONTRACT_ROOT / "runtime-operation-bindings.json").read_text(encoding="utf-8")
)["prober"]
_EXACT_PARENT_CANDIDATES: Mapping[str, tuple[tuple[str, ...], str]] = {
    "ai_id": (("promotion", "ai_trusteeship", "list"), "data.list[].id"),
    "app_id": (("app", "list"), "data.list[].id"),
    "user_id": (("analysis", "account_user", "list"), "data.list[].user_id"),
    "examine_user_id": (
        ("analysis", "account_user", "list"),
        "data.list[].user_id",
    ),
    "material_id": (("material", "local", "list"), "data.list[].material_id"),
    "material_ids": (("material", "local", "list"), "data.list[].material_id"),
    "album_id": (("material", "album", "tree"), "data.tree..id"),
}
_PLATFORM_PARENT_CANDIDATES = {
    (str(item["field_name"]), str(item["platform"])): (
        str(item["operation_id"]), str(item["output_path"]),
    )
    for item in _PROBER_BINDINGS["parent_candidates"]
}

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


def assemble_source_parameters(
    source: Mapping[str, Any], route: Mapping[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Merge one static frontend contract without claiming server requiredness."""

    updated = copy.deepcopy(dict(source))
    operation = updated["operation"]
    parameters = top_level_parameters(route)
    confidence_counts = {"high": 0, "medium": 0}
    for parameter in parameters:
        confidence = apply_parameter(operation, parameter)
        if confidence in confidence_counts:
            confidence_counts[confidence] += 1

    analysis = route.get("analysis", {})
    call_sites = analysis.get("call_sites", []) if isinstance(analysis, Mapping) else []
    route_evidence = updated["draft"].setdefault("route_evidence", {})
    prior = route_evidence.get("parameter_contract", {})
    learned = prior.get("learned_parameters", []) if isinstance(prior, Mapping) else []
    route_evidence["parameter_contract"] = {
        **(copy.deepcopy(dict(prior)) if isinstance(prior, Mapping) else {}),
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
    exact = _EXACT_PARENT_CANDIDATES.get(field_name)
    if exact is not None:
        parent_operation = ".".join(exact[0])
        return (parent_operation, exact[1]) if parent_operation in stable_ids else None
    candidate = _PLATFORM_PARENT_CANDIDATES.get((field_name, platform))
    if candidate is not None and candidate[0] in stable_ids:
        return candidate
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


def _bind_source_parent_candidates(
    source: dict[str, Any], stable_ids: set[str]
) -> list[dict[str, Any]] | None:
    operation = source["operation"]
    platform = operation.get("platform")
    original_parents = copy.deepcopy(operation.get("required_parent", []))
    contract, existing_parents, prior_automatic, automatic = (
        automatic_parent_state(source, operation)
    )
    bound_fields = {
        str(item.get("input_field"))
        for item in existing_parents
        if isinstance(item, Mapping) and item.get("input_field")
    }
    bindings: list[dict[str, Any]] = []
    for field_name, field in operation.get("input_fields", {}).items():
        if field_name in bound_fields:
            continue
        candidate = _parent_candidate(
            str(field_name), str(platform) if platform else None, stable_ids
        )
        if candidate is None:
            continue
        parent_operation, output_path = candidate
        parent = {
            "operation_id": parent_operation, "input_field": str(field_name),
            "output_path": output_path,
            "selection": "all" if field.get("type") == "array" else "caller_select",
        }
        existing_parents.append(parent)
        operation["live_probe"]["inputs"][str(field_name)] = f"$parent:{field_name}"
        bindings.append(parent)
    if automatic:
        restore_removed_parent_inputs(source, operation, prior_automatic, bindings)
    operation["required_parent"] = existing_parents
    if not bindings and not automatic:
        return None
    contract["stable_parent_candidates"] = copy.deepcopy(bindings)
    if original_parents != existing_parents:
        source["draft"]["route_evidence"].pop("parent_resolution", None)
    applied = operation["provenance"].get("applied_overrides", [])
    marker = "stable_parent_candidate_binding"
    if marker not in applied:
        operation["provenance"]["applied_overrides"] = [*applied, marker]
    return bindings


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
        bindings = _bind_source_parent_candidates(source, stable_ids)
        if bindings is None:
            continue
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
