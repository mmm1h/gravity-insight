"""Single versioned analysis playbook definition; not a workflow registry."""

from __future__ import annotations

import copy
import hashlib
import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

from .errors import ContractChangedError
from .semantic_contract import SemanticContractError, validate_semantic_binding
from .semantic_compose_catalog import definition_by_id


DEFINITION_SCHEMA_VERSION = "gravity.analysis-playbook-definition.v1"
PLAYBOOK_ID = "metric-anomaly-localization"
PLAYBOOK_VERSION = 1
_ROOT_FIELDS = frozenset(
    {
        "$schema", "schema_version", "playbook_id", "version", "goal",
        "semantic_definition", "members", "required_inputs", "steps",
        "stop_conditions", "allowed_claims",
    }
)
_MEMBER_FIELDS = frozenset({"metric", "dimension", "filter", "grain", "join"})
_STEP_FIELDS = frozenset(
    {
        "id", "kind", "product", "contract", "depends_on",
        "input_dependencies", "fact_path",
    }
)
_EXPECTED_INPUTS = (
    "schema_version", "question", "app", "current_window",
    "reference_window", "hypothesis",
)
_EXPECTED_STEPS = (
    ("compare_current", "query", ()),
    ("compare_reference", "query", ()),
    ("breakdown_current", "local", ("compare_current", "compare_reference")),
    ("hypothesis", "local", ("breakdown_current",)),
    ("validate_current", "query", ("hypothesis",)),
    ("validate_reference", "query", ("hypothesis",)),
    ("breakdown_reference", "local", ("compare_current", "compare_reference")),
    ("conclusion", "local", ("validate_current", "validate_reference", "breakdown_reference")),
)


def metric_anomaly_playbook_definition() -> dict[str, Any]:
    """Return a fresh, validated copy of the only supported playbook."""

    return copy.deepcopy(_definition())


def bind_metric_anomaly_playbook_definition(
    semantic_binding: Mapping[str, Any],
) -> dict[str, Any]:
    """Bind one compiled project Semantic without changing the playbook owner."""

    try:
        binding = validate_semantic_binding(semantic_binding)
    except SemanticContractError as exc:
        raise ContractChangedError(str(exc)) from exc
    provider = binding["provider"]
    if provider["kind"] != "semantic_compose" or binding["parameters"]:
        raise ContractChangedError(
            "metric anomaly playbook requires a parameter-free semantic_compose binding"
        )
    selected = metric_anomaly_playbook_definition()
    selected["semantic_definition"] = copy.deepcopy(provider["definition"])
    selected["members"] = copy.deepcopy(provider["members"])
    _validate_definition(selected)
    return selected


def playbook_definition_fingerprint(value: Mapping[str, Any] | None = None) -> str:
    selected = _definition() if value is None else value
    payload = json.dumps(
        selected, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


@lru_cache(maxsize=1)
def _definition() -> dict[str, Any]:
    path = (
        Path(__file__).resolve().parent
        / "contracts" / "playbooks" / "metric-anomaly-localization.v1.json"
    )
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ContractChangedError("metric anomaly playbook definition cannot be read") from exc
    if not isinstance(value, dict):
        raise ContractChangedError("metric anomaly playbook definition must be an object")
    _validate_definition(value)
    return value


def _validate_definition(value: Mapping[str, Any]) -> None:
    if set(value) != _ROOT_FIELDS:
        raise ContractChangedError("metric anomaly playbook root fields changed")
    if (
        value.get("schema_version") != DEFINITION_SCHEMA_VERSION
        or value.get("playbook_id") != PLAYBOOK_ID
        or value.get("version") != PLAYBOOK_VERSION
        or not isinstance(value.get("goal"), str)
        or not value["goal"].strip()
    ):
        raise ContractChangedError("metric anomaly playbook identity changed")
    semantic_ref = _reference(value.get("semantic_definition"), "semantic_definition")
    semantic = definition_by_id(*semantic_ref)
    members = value.get("members")
    if not isinstance(members, Mapping) or set(members) != _MEMBER_FIELDS:
        raise ContractChangedError("metric anomaly playbook members changed")
    _validate_members(members, semantic)
    if tuple(value.get("required_inputs", ())) != _EXPECTED_INPUTS:
        raise ContractChangedError("metric anomaly playbook required inputs changed")
    _validate_steps(value.get("steps"))
    _validate_text_contracts(value.get("stop_conditions"), value.get("allowed_claims"))


def _validate_members(members: Mapping[str, Any], semantic: Mapping[str, Any]) -> None:
    collections = {
        "metric": "metrics", "dimension": "dimensions", "filter": "filters",
        "grain": "grains", "join": "joins",
    }
    for name, collection in collections.items():
        selected = _reference(members.get(name), f"members.{name}")
        available = {
            (str(item.get("definition_id")), item.get("version"))
            for item in semantic.get(collection, ())
            if isinstance(item, Mapping)
        }
        if selected not in available:
            raise ContractChangedError(f"metric anomaly playbook {name} is not registered")


def _validate_steps(value: Any) -> None:
    if not isinstance(value, list) or len(value) != len(_EXPECTED_STEPS):
        raise ContractChangedError("metric anomaly playbook steps changed")
    observed: list[tuple[str, str, tuple[str, ...]]] = []
    ids: set[str] = set()
    for step in value:
        step_id, kind, dependencies = _validated_step(step, ids)
        ids.add(step_id)
        observed.append((step_id, str(kind), tuple(dependencies)))
    if tuple(observed) != _EXPECTED_STEPS:
        raise ContractChangedError("metric anomaly playbook step order changed")


def _validate_text_contracts(stops: Any, claims: Any) -> None:
    if not _valid_text_items(stops, {"condition", "outcome"}):
        raise ContractChangedError("metric anomaly stop conditions changed")
    if not _valid_text_items(claims, {"claim_id", "statement"}):
        raise ContractChangedError("metric anomaly allowed claims changed")


def _validated_step(
    value: Any, prior_ids: set[str]
) -> tuple[str, str, list[str]]:
    if not isinstance(value, Mapping) or set(value) != _STEP_FIELDS:
        raise ContractChangedError("metric anomaly playbook step fields changed")
    step_id, kind = value.get("id"), value.get("kind")
    dependencies, inputs = value.get("depends_on"), value.get("input_dependencies")
    if not isinstance(step_id, str) or step_id in prior_ids:
        raise ContractChangedError("metric anomaly playbook step identity changed")
    if kind not in {"query", "local"}:
        raise ContractChangedError("metric anomaly playbook step kind changed")
    if not _string_array(dependencies) or not _string_array(inputs):
        raise ContractChangedError("metric anomaly playbook step arrays changed")
    if any(item not in prior_ids for item in dependencies):
        raise ContractChangedError("metric anomaly playbook DAG changed")
    if kind == "query":
        _validate_query_step(value)
    return step_id, str(kind), dependencies


def _validate_query_step(value: Mapping[str, Any]) -> None:
    expected = (
        "semantic_compose", "gravity.semantic-compose-input.v1",
        "/result/result/query/data/list",
    )
    observed = (value.get("product"), value.get("contract"), value.get("fact_path"))
    if observed != expected:
        raise ContractChangedError("metric anomaly query step contract changed")


def _valid_text_items(value: Any, fields: set[str]) -> bool:
    if not isinstance(value, list) or not value:
        return False
    for item in value:
        if not isinstance(item, Mapping) or set(item) != fields:
            return False
        if any(not isinstance(item.get(key), str) or not item[key].strip() for key in fields):
            return False
    return True


def _reference(value: Any, field: str) -> tuple[str, int]:
    if (
        not isinstance(value, Mapping)
        or set(value) != {"definition_id", "version"}
        or not isinstance(value.get("definition_id"), str)
        or type(value.get("version")) is not int
        or value["version"] < 1
    ):
        raise ContractChangedError(f"metric anomaly playbook {field} reference changed")
    return str(value["definition_id"]), int(value["version"])


def _string_array(value: Any) -> bool:
    return (
        isinstance(value, list)
        and len(value) == len(set(value))
        and all(isinstance(item, str) and item for item in value)
    )


__all__ = [
    "DEFINITION_SCHEMA_VERSION",
    "PLAYBOOK_ID",
    "PLAYBOOK_VERSION",
    "bind_metric_anomaly_playbook_definition",
    "metric_anomaly_playbook_definition",
    "playbook_definition_fingerprint",
]
