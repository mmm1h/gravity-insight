"""Versioned Journeys with explicit current or historical registration."""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from functools import lru_cache
from pathlib import Path
from typing import Any

from .agent_runtime_contracts import (
    AgentRuntimeContractError,
    canonical_digest,
    load_json_object,
    validate_schema,
)
from .capability_contract import capability_contract
from .journey_ledger import ledger_row, load_packaged_journey_ledger
from .contracts.envelope_obligations import (
    CompletenessState, DataCompleteness, DiagnosticEvidence, DiagnosticState,
    EnvelopeObligations, ExecutionState, ExecutionStatus, MutationCertainty,
    MutationState, SemanticState, SemanticValidity, serialize_envelope,
)


SCHEMA_VERSION = "gravity.journey.v2"
_SCHEMA_NAMES = {"gravity.journey.v1": "journey-v1.schema.json", SCHEMA_VERSION: "journey-v2.schema.json"}
_JOURNEY_ROOT = Path(__file__).resolve().parent / "contracts" / "journeys"


class JourneyContractError(AgentRuntimeContractError):
    """A Journey Contract or its structured-ledger binding is invalid."""


def journey_artifacts() -> tuple[dict[str, Any], ...]:
    return tuple(
        copy.deepcopy(artifact)
        for _, artifact in sorted(_artifacts().items())
    )


def journey_artifact(journey_id: str) -> dict[str, Any] | None:
    artifact = _artifacts().get(journey_id)
    return copy.deepcopy(artifact) if artifact is not None else None


def load_journey_contract(path: Path) -> dict[str, Any]:
    value = load_json_object(path, f"Journey Contract {path.name}")
    try:
        version = value.get("schema_version")
        schema = _SCHEMA_NAMES.get(version) if isinstance(version, str) else None
        if schema is None:
            raise JourneyContractError("Journey Contract schema version is unsupported")
        validate_schema(value, schema, f"Journey Contract {path.name}")
    except AgentRuntimeContractError as exc:
        raise JourneyContractError(str(exc)) from exc
    binding = value["display_binding"]
    if "legacy_display_key" in binding and value["display_name"] != binding["legacy_display_key"]:
        raise JourneyContractError("Journey display binding contradicts display_name")
    if "runtime_contract" in binding and binding["runtime_contract"] != value["journey_id"]:
        raise JourneyContractError("Journey runtime registration contradicts journey_id")
    budget = value["request_budget"]
    if budget["known_requests_min"] > budget["known_requests_max"]:
        raise JourneyContractError("Journey request budget range is invalid")
    return value


def validate_journey_bindings(
    contracts: Sequence[Mapping[str, Any]],
    ledger: Mapping[str, Any],
) -> tuple[dict[str, Any], ...]:
    ids: set[str] = set()
    displays: set[str] = set()
    bindings: list[dict[str, Any]] = []
    for contract in contracts:
        journey_id = str(contract["journey_id"])
        display = str(contract["display_name"])
        if journey_id in ids or display in displays:
            raise JourneyContractError("Journey identity or display binding is duplicated")
        ids.add(journey_id)
        displays.add(display)
        legacy = "legacy_display_key" in contract["display_binding"]
        row = ledger_row(dict(ledger), display) if legacy else None
        if legacy:
            if contract["display_binding"]["legacy_display_key"] != display:
                raise JourneyContractError("Journey display binding contradicts display_name")
            if row is None:
                raise JourneyContractError("Journey display binding is missing from the ledger")
            _validate_surface_binding(contract, row)
        elif contract["display_binding"].get("runtime_contract") != journey_id:
            raise JourneyContractError("Journey runtime registration contradicts journey_id")
        elif ledger_row(dict(ledger), display) is not None:
            raise JourneyContractError("A historical Journey display must retain its legacy binding")
        _validate_capability_requirements(contract)
        bindings.append(
            {
                "journey_id": journey_id,
                "display_name": display,
                "ledger_status": row["ledger_status"] if row is not None else None,
                "ledger_row_digest": row["row_digest"] if row is not None else None,
                "contract_digest": canonical_digest(contract),
                **({"registration_source": "runtime_contract"} if not legacy else {}),
            }
        )
    return tuple(bindings)


def verify_journey_registry() -> dict[str, Any]:
    ledger = load_packaged_journey_ledger()
    artifacts = journey_artifacts()
    bindings = validate_journey_bindings(
        [artifact["contract"] for artifact in artifacts], ledger
    )
    return serialize_envelope({
        "schema_version": "gravity.journey-registry-verification.v2",
        "status": "valid",
        "ledger_digest": ledger["snapshot_digest"],
        "ledger_row_count": ledger["row_count"],
        "machine_contract_count": len(artifacts),
        "bindings": [copy.deepcopy(item) for item in bindings],
        "reason_codes": [],
        "network_called": False,
    }, EnvelopeObligations(
        ExecutionStatus(ExecutionState.NOT_STARTED, "JOURNEY_REGISTRY_VERIFICATION_ONLY"),
        DataCompleteness(CompletenessState.NOT_APPLICABLE, "REGISTRY_METADATA_ONLY"),
        SemanticValidity(SemanticState.NOT_APPLICABLE, ()),
        DiagnosticEvidence(DiagnosticState.NONE),
        MutationCertainty(MutationState.NOT_APPLICABLE, "REGISTRY_READ_ONLY"),
    ))


@lru_cache(maxsize=1)
def _artifacts() -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for path in sorted(_JOURNEY_ROOT.glob("*.json")):
        document = load_json_object(path, f"Journey artifact {path.name}")
        if document.get("artifact_kind") != "journey":
            continue
        contract = load_journey_contract(path)
        journey_id = str(contract["journey_id"])
        if journey_id in result:
            raise JourneyContractError("Journey ID is duplicated")
        result[journey_id] = {
            "contract": contract,
            "digest": canonical_digest(contract),
        }
    if not result:
        raise JourneyContractError("Journey registry is empty")
    validate_journey_bindings(
        [artifact["contract"] for artifact in result.values()],
        load_packaged_journey_ledger(),
    )
    return result


def _validate_capability_requirements(contract: Mapping[str, Any]) -> None:
    for requirement in contract["required_capabilities"]:
        artifact = capability_contract(
            str(requirement["identity_kind"]), str(requirement["selector"])
        )
        if artifact is None:
            raise JourneyContractError("Journey Capability Contract is missing")
        if artifact["contract"]["contract_version"] != requirement["contract_version"]:
            raise JourneyContractError("Journey Capability version drifted")


def _validate_surface_binding(
    contract: Mapping[str, Any], row: Mapping[str, Any]
) -> None:
    for name in ("cli", "sdk", "plan", "agent"):
        declared = str(contract["surfaces"][name])
        evidence = _ledger_surface(str(row["surfaces"][name]))
        if declared == "available" and evidence != "available":
            raise JourneyContractError("Journey surface contradicts the ledger")
        if declared == "missing" and evidence != "missing":
            raise JourneyContractError("Journey missing surface contradicts the ledger")
        if declared == "not_applicable" and evidence != "not_applicable":
            raise JourneyContractError("Journey surface applicability contradicts the ledger")
    if row["ledger_status"].startswith("完全缺失") and any(
        value == "available" for value in contract["surfaces"].values()
    ):
        raise JourneyContractError("missing Journey cannot declare an available surface")


def _ledger_surface(value: str) -> str:
    selected = value.strip()
    if selected.startswith("有") or selected.startswith(
        ("复用既有 Plan", "编译为既有 Plan")
    ):
        return "available"
    if selected.startswith(("设计不适用", "设计不新增卡")):
        return "not_applicable"
    if selected.startswith("无"):
        return "missing"
    return "declared"


__all__ = [
    "JourneyContractError",
    "SCHEMA_VERSION",
    "journey_artifact",
    "journey_artifacts",
    "load_journey_contract",
    "validate_journey_bindings",
    "verify_journey_registry",
]
