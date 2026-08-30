"""Keep credential redactions consistent with draft field classifications."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping


CHECK_NAME = "privacy-classification-consistency"
_STATIC_UNREVIEWED_REASON = "frontend_static_consumer_unreviewed"

_ARRAY_EXPOSURES = frozenset(
    {
        "data_keys",
        "item_keys",
        "dynamic_item_fields",
        "numeric_paths",
        "opaque_json_item_keys",
    }
)
_MAP_EXPOSURES = frozenset(
    {
        "nested_item_keys",
        "data_item_keys",
        "data_path_item_keys",
        "data_dynamic_item_fields",
        "recursive_data_item_keys",
    }
)
_TYPE_MAP_EXPOSURES = frozenset(
    {"scalar_list_item_types", "data_scalar_list_types"}
)


def _leaf(value: Any) -> str:
    normalized = str(value).casefold().replace("[]", "").replace("[ ]", "")
    normalized = normalized.replace(".[].", ".").replace(".[ ]", "")
    return normalized.rsplit(".", 1)[-1]


def exposed_field_names(projection: Mapping[str, Any]) -> set[str]:
    """Return every exposed field, including path- and map-shaped allowlists."""

    result: set[str] = set()
    for key in _ARRAY_EXPOSURES:
        values = projection.get(key, [])
        if isinstance(values, list):
            result.update(_leaf(value) for value in values)
    for key in _MAP_EXPOSURES:
        values = projection.get(key, {})
        if not isinstance(values, Mapping):
            continue
        result.update(_leaf(value) for value in values)
        for children in values.values():
            if isinstance(children, list):
                result.update(_leaf(value) for value in children)
    for key in _TYPE_MAP_EXPOSURES:
        values = projection.get(key, {})
        if isinstance(values, Mapping):
            result.update(_leaf(value) for value in values)
    result.discard("")
    return result


def _stable_field_states(
    contract_root: Path,
) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    exposed: dict[str, list[str]] = {}
    redacted: dict[str, list[str]] = {}
    for path in sorted((contract_root / "operations").glob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        operation = document.get("operation", {})
        if operation.get("stability") != "stable":
            continue
        operation_id = str(operation.get("operation_id", path.stem))
        projection = operation.get("response_projection", {})
        if isinstance(projection, Mapping):
            for field in exposed_field_names(projection):
                exposed.setdefault(field, []).append(operation_id)
        privacy = operation.get("privacy_policy", {})
        if isinstance(privacy, Mapping):
            for field in privacy.get("redact_fields", []):
                redacted.setdefault(_leaf(field), []).append(operation_id)
    return exposed, redacted


def _draft_classifications(
    contract_root: Path,
) -> dict[str, dict[str, list[str]]]:
    classified: dict[str, dict[str, list[str]]] = {}
    for path in sorted((contract_root / "drafts").glob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        operation_id = str(document.get("operation", {}).get("operation_id", path.stem))
        draft = document.get("draft", {})
        if not isinstance(draft, Mapping):
            continue
        for item in draft.get("candidate_fields", []):
            if not isinstance(item, Mapping):
                continue
            if item.get("classification_reason") == _STATIC_UNREVIEWED_REASON:
                continue
            field = _leaf(item.get("path", ""))
            decision = str(item.get("privacy_classification", "manual_review"))
            classified.setdefault(field, {}).setdefault(decision, []).append(operation_id)
    return classified


def _consistency_errors(
    exposed: Mapping[str, list[str]],
    redacted: Mapping[str, list[str]],
    classified: Mapping[str, Mapping[str, list[str]]],
) -> list[str]:
    errors: list[str] = []
    for field, decisions in sorted(classified.items()):
        if field in redacted and "non_sensitive" in decisions:
            errors.append(
                f"{CHECK_NAME}: field {field!r} is redacted by stable operation(s) "
                f"{', '.join(redacted[field][:3])} but draft classification is "
                "non_sensitive"
            )
    return errors


def inspect_privacy_classification_consistency(root: Path) -> list[str]:
    contract_root = root / "src/gravity_insight/contracts"
    exposed, redacted = _stable_field_states(contract_root)
    classified = _draft_classifications(contract_root)
    return _consistency_errors(exposed, redacted, classified)


def validate(root: Path) -> list[str]:
    return inspect_privacy_classification_consistency(root)
