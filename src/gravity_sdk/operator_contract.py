"""Formal Operator contract compilation and packaged resource validation."""

from __future__ import annotations

import copy
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

from .agent_runtime_contracts import (
    AgentRuntimeContractError,
    canonical_digest,
    load_json_object,
    validate_schema,
)
from .compiler import ContractError, JsonSchemaValidator


SCHEMA_VERSION = "gravity.operator.v1"
GOLDEN_SCHEMA_VERSION = "gravity.operator-golden.v1"
_CONTRACT_SCHEMA = "operator-v1.schema.json"
_GOLDEN_SCHEMA = "operator-golden-v1.schema.json"
_PACKAGE_ROOT = Path(__file__).resolve().parent
_SCHEMA_ROOT = _PACKAGE_ROOT / "contracts" / "schema"
_OPERATOR_ROOT = _PACKAGE_ROOT / "contracts" / "operators"
_GOLDEN_ROOT = _PACKAGE_ROOT / "contracts" / "operator-golden"
_URI = re.compile(
    r"^operator://[a-z0-9.-]+/[a-z0-9./-]+@(?P<version>[1-9][0-9]*)$"
)


class OperatorContractError(AgentRuntimeContractError):
    """An Operator definition or packaged schema/golden resource is invalid."""

    def __init__(self, reason_code: str, message: str) -> None:
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {message}")


def compile_operator_contract(value: Mapping[str, Any]) -> dict[str, Any]:
    contract = _object(value, "Operator Contract", "OPERATOR_CONTRACT_INVALID")
    try:
        validate_schema(contract, _CONTRACT_SCHEMA, "Operator Contract")
    except AgentRuntimeContractError as exc:
        raise OperatorContractError("OPERATOR_CONTRACT_INVALID", str(exc)) from exc
    match = _URI.fullmatch(str(contract["uri"]))
    if match is None or int(match.group("version")) != contract["version"]:
        raise OperatorContractError(
            "OPERATOR_IDENTITY_INVALID", "Operator URI and version disagree"
        )
    _unique_ids(contract["assumptions"], "assumption_id", "Operator assumptions")
    _unique_ids(contract["golden_cases"], "case_id", "Operator golden cases")
    _disjoint_claims(contract["claim_policy"])
    input_schema = _schema_resource(contract["schemas"]["input"])
    output_schema = _schema_resource(contract["schemas"]["output"])
    golden = _golden_resource(contract)
    components = {
        "contract": canonical_digest(contract),
        "input_schema": canonical_digest(input_schema),
        "output_schema": canonical_digest(output_schema),
        "golden": canonical_digest(golden),
    }
    return {
        "contract": contract,
        "digest": canonical_digest(components),
        "component_digests": components,
        "assumptions_digest": canonical_digest(contract["assumptions"]),
        "input_schema": input_schema,
        "output_schema": output_schema,
        "golden": golden,
    }


def builtin_operator_artifacts() -> tuple[dict[str, Any], ...]:
    return copy.deepcopy(_cached_builtin_operator_artifacts())


@lru_cache(maxsize=1)
def _cached_builtin_operator_artifacts() -> tuple[dict[str, Any], ...]:
    artifacts = tuple(
        compile_operator_contract(load_json_object(path, f"Operator {path.name}"))
        for path in sorted(_OPERATOR_ROOT.glob("*.json"))
    )
    if not artifacts:
        raise OperatorContractError(
            "OPERATOR_REGISTRY_EMPTY", "Built-in Operator registry is empty"
        )
    uris = [artifact["contract"]["uri"] for artifact in artifacts]
    if len(uris) != len(set(uris)):
        raise OperatorContractError(
            "OPERATOR_IDENTITY_CONFLICT", "Built-in Operator URI is duplicated"
        )
    return artifacts


def validate_operator_input(
    artifact: Mapping[str, Any], value: Mapping[str, Any]
) -> dict[str, Any]:
    selected = _object(value, "Operator input", "OPERATOR_INPUT_INVALID")
    _validate_with_schema(artifact["input_schema"], selected, "OPERATOR_INPUT_INVALID")
    selected.setdefault("current_step_id", "compare_current")
    selected.setdefault("reference_step_id", "compare_reference")
    selected.setdefault("selected_current_step_id", "validate_current")
    selected.setdefault("selected_reference_step_id", "validate_reference")
    selected.setdefault("metric", "ap_cost")
    selected.setdefault("dimension", "click_company")
    return selected


def validate_operator_output(
    artifact: Mapping[str, Any], value: Mapping[str, Any]
) -> dict[str, Any]:
    selected = _object(value, "Operator output", "OPERATOR_OUTPUT_INVALID")
    _validate_with_schema(artifact["output_schema"], selected, "OPERATOR_OUTPUT_INVALID")
    return selected


def canonical_json_size(value: Any, *, reason_code: str) -> int:
    try:
        return len(
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        )
    except (TypeError, ValueError) as exc:
        raise OperatorContractError(reason_code, "value is not canonical JSON") from exc


def _schema_resource(reference: Mapping[str, Any]) -> dict[str, Any]:
    name = str(reference["resource"])
    if Path(name).name != name:
        raise OperatorContractError(
            "OPERATOR_SCHEMA_INVALID", "Operator schema resource path is unsafe"
        )
    schema = load_json_object(_SCHEMA_ROOT / name, f"Operator schema {name}")
    if schema.get("$id") != reference["schema_version"]:
        raise OperatorContractError(
            "OPERATOR_SCHEMA_INVALID", "Operator schema identity changed"
        )
    try:
        JsonSchemaValidator(schema, name)
    except ContractError as exc:
        raise OperatorContractError(
            "OPERATOR_SCHEMA_INVALID", "Operator schema is invalid"
        ) from exc
    return schema


def _golden_resource(contract: Mapping[str, Any]) -> dict[str, Any]:
    resources = {item["resource"] for item in contract["golden_cases"]}
    if len(resources) != 1:
        raise OperatorContractError(
            "OPERATOR_GOLDEN_INVALID", "Operator golden cases require one resource"
        )
    name = str(next(iter(resources)))
    if Path(name).name != name:
        raise OperatorContractError(
            "OPERATOR_GOLDEN_INVALID", "Operator golden resource path is unsafe"
        )
    golden = load_json_object(_GOLDEN_ROOT / name, f"Operator golden {name}")
    try:
        validate_schema(golden, _GOLDEN_SCHEMA, "Operator golden")
    except AgentRuntimeContractError as exc:
        raise OperatorContractError("OPERATOR_GOLDEN_INVALID", str(exc)) from exc
    declared = [item["case_id"] for item in contract["golden_cases"]]
    actual = [item["case_id"] for item in golden["cases"]]
    if golden["operator_uri"] != contract["uri"] or declared != actual:
        raise OperatorContractError(
            "OPERATOR_GOLDEN_INVALID", "Operator golden identity or cases changed"
        )
    return golden


def _validate_with_schema(
    schema: Mapping[str, Any], value: Mapping[str, Any], reason_code: str
) -> None:
    try:
        JsonSchemaValidator(dict(schema), str(schema.get("$id", "Operator schema"))).validate(
            value
        )
    except ContractError as exc:
        raise OperatorContractError(reason_code, "value does not match Operator schema") from exc


def _unique_ids(values: list[dict[str, Any]], key: str, label: str) -> None:
    identities = [item[key] for item in values]
    if len(identities) != len(set(identities)):
        raise OperatorContractError(
            "OPERATOR_CONTRACT_INVALID", f"{label} contain duplicate identities"
        )


def _disjoint_claims(policy: Mapping[str, Any]) -> None:
    allowed = set(policy["allowed"])
    forbidden = set(policy["forbidden"])
    if allowed & forbidden:
        raise OperatorContractError(
            "OPERATOR_CLAIM_CONFLICT", "allowed and forbidden claims overlap"
        )


def _object(value: Any, label: str, reason_code: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise OperatorContractError(
            reason_code, f"{label} must be an object"
        )
    return copy.deepcopy(dict(value))


__all__ = [
    "GOLDEN_SCHEMA_VERSION",
    "OperatorContractError",
    "SCHEMA_VERSION",
    "builtin_operator_artifacts",
    "canonical_json_size",
    "compile_operator_contract",
    "validate_operator_input",
    "validate_operator_output",
]
