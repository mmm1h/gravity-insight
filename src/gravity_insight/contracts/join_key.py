"""Platform-scoped acquisition-to-user join-key contract and resolver."""

from __future__ import annotations

import copy
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..agent_runtime_contracts import (
    AgentRuntimeContractError,
    load_json_object,
    validate_schema,
)
from ..models import OperationSpec, load_operation_manifest
from ..paths import CONTRACT_ROOT, MANIFEST_ROOT


SCHEMA_VERSION = "gravity.join-key-registry.v1"
RESOLUTION_SCHEMA_VERSION = "gravity.join-key-resolution.v1"
_SCHEMA_NAME = "join-key-registry-v1.schema.json"
_REGISTRY_PATH = CONTRACT_ROOT / "join-keys" / "registry.v1.json"
_STATUSES = frozenset({"proven", "disproven", "insufficient_evidence"})


class JoinKeyContractError(AgentRuntimeContractError):
    """A join-key registry or requested mapping is unsafe to consume."""


def validate_join_key_registry(
    value: Mapping[str, Any], *, manifest_root: Path = MANIFEST_ROOT
) -> dict[str, Any]:
    selected = copy.deepcopy(dict(value))
    try:
        validate_schema(selected, _SCHEMA_NAME, "Join-key registry")
        _validate_registry_semantics(selected, manifest_root)
    except AgentRuntimeContractError as exc:
        raise JoinKeyContractError(str(exc)) from exc
    return selected


def load_join_key_registry(
    path: Path, *, manifest_root: Path = MANIFEST_ROOT
) -> dict[str, Any]:
    selected = load_json_object(path, f"Join-key registry {path.name}")
    return validate_join_key_registry(selected, manifest_root=manifest_root)


@lru_cache(maxsize=1)
def _registry() -> dict[str, Any]:
    return load_join_key_registry(_REGISTRY_PATH)


def join_key_registry() -> dict[str, Any]:
    """Return an isolated copy of the validated checked-in registry."""

    return copy.deepcopy(_registry())


def require_proven_join_key(
    mapping_id: str,
    *,
    object_subtype: str | None = None,
    as_of: str | date | None = None,
) -> dict[str, Any]:
    mapping = _require_proven_mapping(mapping_id, as_of)
    right = _select_right_field(mapping, object_subtype)
    return _resolution(mapping, right)


def _require_proven_mapping(
    mapping_id: str, as_of: str | date | None
) -> Mapping[str, Any]:
    mapping = next(
        (item for item in _registry()["mappings"] if item["mapping_id"] == mapping_id),
        None,
    )
    if mapping is None:
        raise JoinKeyContractError("join-key mapping is not registered")
    if mapping["namespace_status"] != "proven":
        raise JoinKeyContractError(
            "join-key namespace is not proven and cannot be used"
        )
    _require_current_evidence(mapping, as_of)
    return mapping


def resolve_proven_join_key(
    platform: str,
    object_type: str,
    *,
    object_subtype: str | None = None,
    as_of: str | date | None = None,
) -> dict[str, Any]:
    candidates = [
        item
        for item in _registry()["mappings"]
        if item["platform"] == platform and item["object_type"] == object_type
    ]
    proven = [item for item in candidates if item["namespace_status"] == "proven"]
    if not proven:
        states = sorted({item["namespace_status"] for item in candidates})
        detail = ", ".join(states) if states else "unregistered"
        raise JoinKeyContractError(
            f"join-key namespace is not proven for this platform/object ({detail})"
        )
    if len(proven) != 1:
        raise JoinKeyContractError("join-key registry has ambiguous proven mappings")
    return require_proven_join_key(
        proven[0]["mapping_id"],
        object_subtype=object_subtype,
        as_of=as_of,
    )


def _resolution(
    mapping: Mapping[str, Any], right: Mapping[str, Any]
) -> dict[str, Any]:
    return {
        "schema_version": RESOLUTION_SCHEMA_VERSION,
        "mapping_id": mapping["mapping_id"],
        "platform": mapping["platform"],
        "object_type": mapping["object_type"],
        "object_subtype": right["object_subtype"],
        "namespace_status": mapping["namespace_status"],
        "left": copy.deepcopy(mapping["left"]),
        "right": copy.deepcopy(right["reference"]),
        "normalization": copy.deepcopy(mapping["normalization"]),
        "evidence": copy.deepcopy(mapping["evidence"]),
    }


def normalize_join_value(
    mapping_id: str,
    value: Any,
    *,
    side: str,
    as_of: str | date | None = None,
) -> Any:
    mapping = _require_proven_mapping(mapping_id, as_of)
    if side not in {"left", "right"}:
        raise JoinKeyContractError("join-key normalization side must be left or right")
    rule = mapping["normalization"]["rule"]
    apply_to = mapping["normalization"]["apply_to"]
    if rule == "identity" or side != apply_to:
        return value
    if rule == "json_integer_to_decimal_string":
        if not isinstance(value, int) or isinstance(value, bool):
            raise JoinKeyContractError(
                "json_integer_to_decimal_string requires an integer JSON value"
            )
        return str(value)
    raise JoinKeyContractError("join-key normalization rule is unsupported")


def inspect_join_key_contract(root: Path) -> list[str]:
    path = root / "src/gravity_insight/contracts/join-keys/registry.v1.json"
    manifests = root / "src/gravity_insight/manifests"
    try:
        load_join_key_registry(path, manifest_root=manifests)
    except (AgentRuntimeContractError, OSError, UnicodeError, ValueError) as exc:
        return [f"join-key-contract: {exc}"]
    return []


def _validate_registry_semantics(
    registry: Mapping[str, Any], manifest_root: Path
) -> None:
    mappings = registry["mappings"]
    identities = [item["mapping_id"] for item in mappings]
    if len(identities) != len(set(identities)):
        raise JoinKeyContractError("join-key mapping identity is duplicated")
    operations = _operation_index(manifest_root)
    for mapping in mappings:
        _validate_mapping_semantics(mapping)
        _validate_field_reference(mapping["left"], operations)
        for field in mapping["right"]["fields"]:
            _validate_field_reference(field["reference"], operations)


def _operation_index(manifest_root: Path) -> dict[str, OperationSpec]:
    operations: dict[str, OperationSpec] = {}
    for path in sorted(manifest_root.glob("*.json")):
        for operation in load_operation_manifest(path):
            if operation.operation_id in operations:
                raise JoinKeyContractError("operation identity is duplicated")
            operations[operation.operation_id] = operation
    if not operations:
        raise JoinKeyContractError("operation manifest catalog is empty")
    return operations


def _validate_field_reference(
    reference: Mapping[str, Any], operations: Mapping[str, OperationSpec]
) -> None:
    operation = operations.get(reference["operation_id"])
    if operation is None:
        raise JoinKeyContractError("join-key operation reference is missing")
    field = str(reference["path"]).rsplit(".", 1)[-1]
    if field not in operation.response_projection.item_keys:
        raise JoinKeyContractError("join-key field is absent from response projection")


def _validate_mapping_semantics(mapping: Mapping[str, Any]) -> None:
    status = mapping["namespace_status"]
    if status not in _STATUSES:
        raise JoinKeyContractError("join-key namespace status is invalid")
    _validate_evidence(mapping["evidence"], status)
    _validate_right_selection(mapping["right"], status)
    _validate_normalization(mapping["normalization"])


def _validate_right_selection(right: Mapping[str, Any], status: str) -> None:
    fields = right["fields"]
    subtypes = [field["object_subtype"] for field in fields]
    if right["selection"] == "single":
        if len(fields) != 1 or subtypes != [None]:
            raise JoinKeyContractError("single join-key selection must have one field")
    elif (
        len(fields) < 2
        or any(subtype is None for subtype in subtypes)
        or len(subtypes) != len(set(subtypes))
    ):
        raise JoinKeyContractError(
            "subtype join-key selection must have unique explicit subtypes"
        )
    for field in fields:
        candidate = field["candidate_evidence"]
        if candidate is not None:
            _validate_evidence(candidate, status)
        if right["selection"] == "by_object_subtype" and candidate is None:
            raise JoinKeyContractError(
                "subtype join-key fields require candidate-level evidence"
            )


def _validate_normalization(normalization: Mapping[str, Any]) -> None:
    expected_side = (
        "none" if normalization["rule"] == "identity" else "left"
    )
    if normalization["apply_to"] != expected_side:
        raise JoinKeyContractError("join-key normalization side contradicts its rule")


def _validate_evidence(evidence: Mapping[str, Any], status: str) -> None:
    sampled = _canonical_date(evidence["sampled_on"], "sampled_on")
    review = _canonical_date(evidence["revalidate_after"], "revalidate_after")
    if review <= sampled:
        raise JoinKeyContractError("join-key evidence revalidation must follow sampling")
    _validate_evidence_counts(evidence)
    _validate_evidence_status(evidence, status)


def _validate_evidence_counts(evidence: Mapping[str, Any]) -> None:
    left = evidence["left_distinct_count"]
    right = evidence["right_distinct_count"]
    overlap = evidence["intersection_distinct_count"]
    if overlap is not None and (
        left is None or right is None or overlap > min(left, right)
    ):
        raise JoinKeyContractError("join-key evidence intersection is inconsistent")


def _validate_evidence_status(evidence: Mapping[str, Any], status: str) -> None:
    left = evidence["left_distinct_count"]
    right = evidence["right_distinct_count"]
    overlap = evidence["intersection_distinct_count"]
    if status == "proven" and (overlap is None or overlap <= 0):
        raise JoinKeyContractError("proven join-key evidence needs a non-zero intersection")
    if status == "disproven" and (overlap != 0 or not left or not right):
        raise JoinKeyContractError("disproven join-key evidence needs a tested zero intersection")
    if status == "insufficient_evidence" and overlap is not None and overlap > 0:
        raise JoinKeyContractError(
            "insufficient join-key evidence cannot contain a proven intersection"
        )


def _select_right_field(
    mapping: Mapping[str, Any], object_subtype: str | None
) -> Mapping[str, Any]:
    right = mapping["right"]
    fields: Sequence[Mapping[str, Any]] = right["fields"]
    if right["selection"] == "single":
        if object_subtype is not None:
            raise JoinKeyContractError("object_subtype is not valid for this join-key")
        return fields[0]
    if object_subtype is None:
        raise JoinKeyContractError(
            "object_subtype is required for this join-key selection"
        )
    selected = [field for field in fields if field["object_subtype"] == object_subtype]
    if len(selected) != 1:
        raise JoinKeyContractError("object_subtype has no proven join-key field")
    return selected[0]


def _require_current_evidence(
    mapping: Mapping[str, Any], as_of: str | date | None
) -> None:
    selected = date.today() if as_of is None else _as_of_date(as_of)
    sampled = _canonical_date(mapping["evidence"]["sampled_on"], "sampled_on")
    review = _canonical_date(mapping["evidence"]["revalidate_after"], "revalidate_after")
    if selected < sampled or selected > review:
        raise JoinKeyContractError(
            "join-key evidence is not current for the requested date"
        )


def _as_of_date(value: str | date) -> date:
    return value if isinstance(value, date) else _canonical_date(value, "as_of")


def _canonical_date(value: Any, field: str) -> date:
    try:
        selected = date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise JoinKeyContractError(f"join-key {field} must be YYYY-MM-DD") from exc
    if selected.isoformat() != value:
        raise JoinKeyContractError(f"join-key {field} must be canonical YYYY-MM-DD")
    return selected


__all__ = [
    "JoinKeyContractError",
    "RESOLUTION_SCHEMA_VERSION",
    "SCHEMA_VERSION",
    "inspect_join_key_contract",
    "join_key_registry",
    "load_join_key_registry",
    "normalize_join_value",
    "require_proven_join_key",
    "resolve_proven_join_key",
    "validate_join_key_registry",
]
