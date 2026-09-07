"""Pure fail-closed policy for response drift declaration candidates."""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping, Sequence
from typing import Any

from gravity_insight.governance.stable_privacy import (
    operation_exposure_paths,
    suspected_personal_reason,
)
from gravity_insight.models import OperationSpec, ResponseProjection
from gravity_insight.pagination_contract_audit import (
    operation_pagination_candidate_signatures,
)
from gravity_insight.response_drift import dynamic_key_path_shape, dynamic_key_shape

from .privacy import classify_candidate_field, projection_exposes_path


_SCALAR_TYPES = frozenset({"boolean", "integer", "number", "string"})
_DATE_KEY = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")


def _decode_pointer(pointer: str) -> tuple[str, ...] | None:
    if not pointer.startswith("/") or pointer == "/":
        return None
    decoded: list[str] = []
    for raw in pointer[1:].split("/"):
        if re.search(r"~(?![01])", raw):
            return None
        decoded.append(raw.replace("~1", "/").replace("~0", "~"))
    return tuple(decoded) if _encode_pointer(decoded) == pointer else None


def _encode_pointer(parts: Sequence[str]) -> str:
    return "/" + "/".join(
        part.replace("~", "~0").replace("/", "~1") for part in parts
    )


def _projection_path(parts: Sequence[str]) -> str:
    result: list[str] = []
    for part in parts:
        if part == "*":
            if result:
                result[-1] += "[]"
        else:
            result.append(part)
    return ".".join(result)


def _edit(field: str, key: str | None, value: str) -> dict[str, Any]:
    return {"projection_field": field, "projection_key": key, "value": value}


def _list_parts(operation: Mapping[str, Any]) -> tuple[str, ...]:
    pagination = operation.get("pagination")
    list_path = pagination.get("list_path") if isinstance(pagination, Mapping) else None
    if isinstance(list_path, str) and list_path.startswith("data."):
        return tuple(list_path.split(".")[1:])
    projection = operation.get("response_projection")
    if isinstance(projection, Mapping) and "list" in projection.get("data_keys", ()):
        return ("list",)
    return ()


def _map_keys(projection: Mapping[str, Any], name: str) -> set[str]:
    value = projection.get(name)
    return {str(item) for item in value} if isinstance(value, Mapping) else set()


def _wildcard_slot(
    operation: Mapping[str, Any], projection: Mapping[str, Any], parts: Sequence[str]
) -> dict[str, Any] | None:
    if len(parts) < 4 or parts[-2] != "*":
        return None
    leaf = parts[-1]
    container = tuple(parts[1:-2])
    list_parts = _list_parts(operation)
    if container == list_parts:
        return _edit("item_keys", None, leaf)
    dotted = ".".join(container)
    if dotted in _map_keys(projection, "data_path_item_keys"):
        return _edit("data_path_item_keys", dotted, leaf)
    mapping_roots = (
        _map_keys(projection, "data_item_keys")
        | _map_keys(projection, "data_dynamic_item_fields")
        | _map_keys(projection, "data_numeric_suffix_item_fields")
    )
    if len(container) == 1 and container[0] in mapping_roots:
        return _edit("data_item_keys", container[0], leaf)
    nested_parent = container[-1] if container else ""
    nested_shape = (
        len(container) == len(list_parts) + 2
        and container[: len(list_parts)] == list_parts
        and container[-2:-1] == ("*",)
    )
    if nested_shape and nested_parent in _map_keys(projection, "nested_item_keys"):
        return _edit("nested_item_keys", nested_parent, leaf)
    return None


def _mapping_slot(
    projection: Mapping[str, Any], parts: Sequence[str]
) -> dict[str, Any] | None:
    mapping_roots = (
        _map_keys(projection, "data_item_keys")
        | _map_keys(projection, "data_dynamic_item_fields")
        | _map_keys(projection, "data_numeric_suffix_item_fields")
    )
    if len(parts) == 3 and parts[1] in mapping_roots:
        return _edit("data_item_keys", parts[1], parts[-1])
    return None


def _projection_slot(
    operation: Mapping[str, Any], parts: Sequence[str]
) -> dict[str, Any] | None:
    projection = operation.get("response_projection")
    if not isinstance(projection, Mapping) or not parts or parts[0] != "data":
        return None
    leaf = parts[-1]
    if leaf == "*" or len(parts) == 1:
        return None
    if len(parts) == 2:
        return _edit("data_keys", None, leaf)
    if projection.get("data_shape") == "list" and parts == ("data", "*", leaf):
        return _edit("item_keys", None, leaf)
    return _wildcard_slot(operation, projection, parts) or _mapping_slot(
        projection, parts
    )


def _projection_values(
    projection: Mapping[str, Any], edit: Mapping[str, Any]
) -> Sequence[Any]:
    field = str(edit["projection_field"])
    key = edit.get("projection_key")
    current = projection.get(field, {} if key is not None else [])
    if key is not None:
        return current.get(key, ()) if isinstance(current, Mapping) else ()
    return current if isinstance(current, Sequence) and not isinstance(current, str) else ()


def _omitted_field(operation: Mapping[str, Any], edit: Mapping[str, Any]) -> bool:
    projection = operation.get("response_projection")
    if not isinstance(projection, Mapping):
        return False
    field = str(edit["projection_field"])
    key = edit.get("projection_key")
    omitted_field = {
        "data_keys": "known_omitted_data_keys",
        "item_keys": "known_omitted_item_keys",
        "data_item_keys": "known_omitted_data_item_keys",
        "nested_item_keys": "known_omitted_nested_item_keys",
        "data_path_item_keys": "known_omitted_data_item_keys",
    }[field]
    omitted = projection.get(omitted_field, {})
    if key is not None:
        omitted = omitted.get(key, ()) if isinstance(omitted, Mapping) else ()
    return edit["value"] in omitted


def apply_projection_edit(
    operation: dict[str, Any], edit: Mapping[str, Any]
) -> None:
    projection = operation.setdefault("response_projection", {})
    field = str(edit["projection_field"])
    key = edit.get("projection_key")
    value = str(edit["value"])
    values = (
        projection.setdefault(field, [])
        if key is None
        else projection.setdefault(field, {}).setdefault(str(key), [])
    )
    if value not in values:
        values.append(value)


def manual_decision(
    pointer: str, observed_types: Sequence[str], reason: str, **details: Any
) -> dict[str, Any]:
    return {
        "path": pointer,
        "observed_types": list(observed_types),
        "decision": "manual",
        "reason": reason,
        **details,
    }


def _automatic(
    pointer: str,
    observed_types: Sequence[str],
    *,
    projection_path: str,
    edit: Mapping[str, Any],
    exposure_path: str,
    classification_reason: str,
) -> dict[str, Any]:
    return {
        "path": pointer,
        "observed_types": list(observed_types),
        "decision": "automatic",
        "reason": "safe_scalar_existing_projection_slot",
        "projection_path": projection_path,
        "proposed_edit": dict(edit),
        "exposure_path": exposure_path,
        "privacy_classification": "non_sensitive",
        "classification_reason": classification_reason,
    }


def _shape_rejection(
    operation: Mapping[str, Any], pointer: str, types: Sequence[str]
) -> tuple[dict[str, Any] | None, tuple[str, ...] | None]:
    if len(types) != 1:
        return manual_decision(pointer, types, "conflicting_observed_types"), None
    parts = _decode_pointer(pointer)
    if parts is None:
        return manual_decision(pointer, types, "invalid_json_pointer"), None
    projection = operation.get("response_projection")
    patterns = (
        projection.get("dynamic_key_patterns", {})
        if isinstance(projection, Mapping)
        else {}
    )
    if parts[0:1] == ("data",) and len(parts) >= 3:
        container = parts[1:-1]
        key = parts[-1]
        expected_shape = dynamic_key_path_shape(patterns, container)
        if expected_shape is not None:
            matched_shape = dynamic_key_shape(patterns, container, key)
            projection_path = ".".join((*container, f"{{{expected_shape}}}"))
            if matched_shape is not None:
                return manual_decision(
                    pointer,
                    types,
                    "declared_dynamic_key",
                    projection_path=projection_path,
                    key_shape=matched_shape,
                ), None
            return manual_decision(
                pointer,
                types,
                "dynamic_key_shape_mismatch",
                projection_path=projection_path,
                expected_key_shape=expected_shape,
            ), None
    if any(_DATE_KEY.fullmatch(part) for part in parts):
        return manual_decision(pointer, types, "dynamic_key_requires_review"), None
    if types[0] == "null":
        return manual_decision(pointer, types, "null_type_unproven"), None
    if types[0] not in _SCALAR_TYPES:
        return manual_decision(pointer, types, "container_shape_unproven"), None
    return None, parts


def _privacy_decision(
    operation: Mapping[str, Any], operation_id: str, path: str
) -> tuple[str, str]:
    classification, reason = classify_candidate_field(path, operation_id=operation_id)
    if classification == "sensitive":
        return "credential_requires_omission", reason
    privacy = operation.get("privacy_policy")
    redacted = privacy.get("redact_fields", ()) if isinstance(privacy, Mapping) else ()
    leaf = path.rsplit(".", 1)[-1].replace("[]", "").casefold()
    if any(str(item).rsplit(".", 1)[-1].casefold() == leaf for item in redacted):
        return "redacted_field_requires_review", reason
    personal = suspected_personal_reason(operation, path)
    if personal is not None:
        return "personal_or_privilege_field_requires_review", personal
    if classification != "non_sensitive":
        return "privacy_classification_required", reason
    return "automatic", reason


def _proposed_rejection(
    operation: Mapping[str, Any], proposed: Mapping[str, Any], projection_path: str
) -> tuple[dict[str, Any] | None, list[str]]:
    try:
        ResponseProjection.from_dict(proposed["response_projection"])
        OperationSpec.from_dict(proposed)
    except (TypeError, ValueError) as exc:
        return manual_decision(
            "", (), "proposed_contract_invalid",
            projection_path=projection_path, detail=type(exc).__name__,
        ), []
    if not projection_exposes_path(projection_path, proposed["response_projection"]):
        return manual_decision(
            "", (), "projection_model_cannot_expose_path",
            projection_path=projection_path,
        ), []
    before, after = operation_pagination_candidate_signatures(operation, proposed)
    if before is None:
        return manual_decision(
            "", (), "pagination_audit_missing", projection_path=projection_path
        ), []
    if before != after:
        return manual_decision(
            "", (), "pagination_evidence_context_changed",
            projection_path=projection_path,
            governance_before=before,
            governance_after=after,
        ), []
    delta = sorted(operation_exposure_paths(proposed) - operation_exposure_paths(operation))
    if len(delta) != 1:
        return manual_decision(
            "", (), "projection_blast_radius_not_single",
            projection_path=projection_path, exposure_delta=delta,
        ), delta
    return None, delta


def _replace_observation(
    decision: Mapping[str, Any], pointer: str, types: Sequence[str]
) -> dict[str, Any]:
    return {**decision, "path": pointer, "observed_types": list(types)}


def decide_observation(
    operation: Mapping[str, Any], pointer: str, observed_types: set[str]
) -> dict[str, Any]:
    """Return one automatic/manual decision without mutating the operation."""

    types = sorted(observed_types)
    rejected, parts = _shape_rejection(operation, pointer, types)
    if rejected is not None or parts is None:
        return rejected or manual_decision(pointer, types, "invalid_json_pointer")
    projection_path = _projection_path(parts)
    edit = _projection_slot(operation, parts)
    if edit is None:
        return manual_decision(
            pointer, types, "projection_topology_requires_review",
            projection_path=projection_path,
        )
    privacy, reason = _privacy_decision(
        operation, str(operation["operation_id"]), projection_path
    )
    if privacy in {
        "credential_requires_omission",
        "personal_or_privilege_field_requires_review",
        "redacted_field_requires_review",
    }:
        return manual_decision(
            pointer, types, privacy,
            projection_path=projection_path,
            privacy_classification_reason=reason,
        )
    projection = operation.get("response_projection", {})
    if edit["value"] in _projection_values(projection, edit):
        return manual_decision(
            pointer, types, "already_exposed", projection_path=projection_path
        )
    if _omitted_field(operation, edit):
        return manual_decision(
            pointer, types, "already_omitted", projection_path=projection_path
        )

    proposed = copy.deepcopy(dict(operation))
    apply_projection_edit(proposed, edit)
    rejection, exposure_delta = _proposed_rejection(
        operation, proposed, projection_path
    )
    if rejection is not None:
        return _replace_observation(rejection, pointer, types)
    if privacy != "automatic":
        return manual_decision(
            pointer, types, privacy,
            projection_path=projection_path,
            privacy_classification_reason=reason,
        )
    return _automatic(
        pointer,
        types,
        projection_path=projection_path,
        edit=edit,
        exposure_path=exposure_delta[0],
        classification_reason=reason,
    )


def validate_combined_decisions(
    operation: Mapping[str, Any], decisions: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    automatic = [item for item in decisions if item["decision"] == "automatic"]
    if not automatic:
        return decisions
    proposed = copy.deepcopy(dict(operation))
    for item in automatic:
        apply_projection_edit(proposed, item["proposed_edit"])
    try:
        OperationSpec.from_dict(proposed)
    except (TypeError, ValueError):
        return _downgrade_automatic(decisions, "combined_contract_invalid")
    before, after = operation_pagination_candidate_signatures(operation, proposed)
    if before != after:
        return _downgrade_automatic(
            decisions, "combined_pagination_evidence_context_changed"
        )
    delta = operation_exposure_paths(proposed) - operation_exposure_paths(operation)
    if delta != {item["exposure_path"] for item in automatic}:
        return _downgrade_automatic(
            decisions, "combined_projection_blast_radius_changed"
        )
    return decisions


def _downgrade_automatic(
    decisions: list[dict[str, Any]], reason: str
) -> list[dict[str, Any]]:
    return [
        (
            manual_decision(
                item["path"], item["observed_types"], reason,
                projection_path=item.get("projection_path"),
            )
            if item["decision"] == "automatic"
            else item
        )
        for item in decisions
    ]


__all__ = [
    "apply_projection_edit",
    "decide_observation",
    "manual_decision",
    "validate_combined_decisions",
]
