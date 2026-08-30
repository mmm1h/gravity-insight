"""Deterministic Trust-gated decisions for the fixed Execution Variant set."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from .agent_runtime_contracts import (
    AgentRuntimeContractError,
    canonical_digest,
    validate_schema,
)
from .execution_variant_characterization import (
    load_execution_variant_characterization,
    validate_execution_variant_characterization,
)
from .execution_variant_contract import (
    DIRECT_VARIANT_URI,
    ExecutionVariantContractError,
    execution_variant_descriptors,
    rollback_contract,
)


SELECTION_SCHEMA_VERSION = "gravity.execution-variant-selection.v1"
AUTOMATIC_MODE = "automatic"
DISABLED_MODE = "disabled"
_SELECTION_SCHEMA = "execution-variant-selection-v1.schema.json"
_CURRENT_TRUST_STATUSES = {
    "stable",
    "unknown",
    "degraded",
    "blocked",
    "quarantined",
}
_TOPOLOGY_HOPS = {"direct_product": 1, "plan_adapter": 2}


def build_execution_variant_selection(
    characterization: Mapping[str, Any],
    *,
    mode: str,
    pin_requested: bool,
    pinned_variant_uri: str | None,
) -> dict[str, Any]:
    """Build one value-free selection after the service evaluates its gates."""

    selected = _fixed_characterization(characterization)
    result = _selection_payload(
        selected,
        current_trust=selected["current_trust"],
        mode=mode,
        pin_requested=pin_requested,
        pinned_variant_uri=pinned_variant_uri,
    )
    return validate_execution_variant_selection(result)


def validate_execution_variant_selection(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    selected = _mapping(value, "Execution Variant Selection")
    try:
        validate_schema(selected, _SELECTION_SCHEMA, "Execution Variant Selection")
    except AgentRuntimeContractError as exc:
        raise ExecutionVariantContractError(
            "EXECUTION_VARIANT_SELECTION_INVALID", str(exc)
        ) from exc

    characterization = load_execution_variant_characterization()
    expected = _selection_payload(
        characterization,
        current_trust=selected["current_trust"],
        mode=selected["mode"],
        pin_requested=selected["pin"]["requested"],
        pinned_variant_uri=selected["pin"]["variant_uri"],
    )
    if selected != expected:
        _invalid("Selection fields contradict the fixed decision policy")
    return selected


def selection_digest(value: Mapping[str, Any]) -> str:
    selected = copy.deepcopy(dict(value))
    selected.pop("decision_sha256", None)
    return canonical_digest(selected)


def _selection_payload(
    characterization: Mapping[str, Any],
    *,
    current_trust: Mapping[str, Any],
    mode: str,
    pin_requested: bool,
    pinned_variant_uri: str | None,
) -> dict[str, Any]:
    if mode not in {AUTOMATIC_MODE, DISABLED_MODE}:
        _invalid("Selection mode must be automatic or disabled")
    if type(pin_requested) is not bool:
        _invalid("Pin requested state must be boolean")

    trust = _selection_trust(
        current_trust, characterization["product"]["contract_digest"]
    )
    trust_stable = trust["trust_status"] == "stable"
    decision = _decision(
        trust_stable=trust_stable,
        mode=mode,
        pin_requested=pin_requested,
        pinned_variant_uri=pinned_variant_uri,
    )

    result = {
        "schema_version": SELECTION_SCHEMA_VERSION,
        "status": "success",
        "selection_status": decision["selection_status"],
        "product": copy.deepcopy(characterization["product"]),
        "characterization": _characterization_reference(characterization),
        "mode": mode,
        "pin": {
            "requested": pin_requested,
            "evaluated": decision["pin_evaluated"],
            "variant_uri": pinned_variant_uri,
        },
        "selected_variant_uri": decision["selected_variant_uri"],
        "canonical_variant_uri": DIRECT_VARIANT_URI,
        "current_trust": copy.deepcopy(trust),
        "candidates": _candidates(
            trust_stable=trust_stable,
            mode=mode,
            pin_requested=pin_requested,
            pinned_variant_uri=pinned_variant_uri,
        ),
        "objective_facts": {
            "trust_hard_gate": "passed" if trust_stable else "failed",
            "request_count": "equivalent",
            "freshness": "same_product_trust_and_upstream_response",
            "latency_evidence": "unavailable",
            "cost_evidence": "unavailable",
            "secondary_objective": "minimum_local_topology",
            "secondary_objective_evaluated": decision["automatic_selection"],
        },
        "gates": _gates(
            trust_stable=trust_stable,
            mode=mode,
            pin_requested=pin_requested,
        ),
        "reason_codes": decision["reason_codes"],
        "rollback": rollback_contract(),
        "automatic_selection": decision["automatic_selection"],
        "network_called": False,
    }
    result["decision_sha256"] = selection_digest(result)
    return result


def _decision(
    *,
    trust_stable: bool,
    mode: str,
    pin_requested: bool,
    pinned_variant_uri: str | None,
) -> dict[str, Any]:
    selection_enabled = trust_stable and mode == AUTOMATIC_MODE
    if selection_enabled and pin_requested:
        if pinned_variant_uri not in _variant_uris():
            _invalid("Evaluated pin is not one of the fixed Variants")
        return {
            "selected_variant_uri": pinned_variant_uri,
            "selection_status": "pinned_selection",
            "reason_codes": ["EXECUTION_VARIANT_PIN_SELECTED"],
            "automatic_selection": False,
            "pin_evaluated": True,
        }
    if selection_enabled:
        if pinned_variant_uri is not None:
            _invalid("A Variant URI cannot exist without a requested pin")
        return {
            "selected_variant_uri": _minimum_topology_variant(),
            "selection_status": "automatic_selection",
            "reason_codes": [
                "EXECUTION_VARIANT_REQUEST_COUNT_EQUIVALENT",
                "EXECUTION_VARIANT_FRESHNESS_TRUST_BOUND",
                "EXECUTION_VARIANT_LATENCY_EVIDENCE_UNAVAILABLE",
                "EXECUTION_VARIANT_COST_EVIDENCE_UNAVAILABLE",
                "EXECUTION_VARIANT_MINIMUM_LOCAL_TOPOLOGY",
            ],
            "automatic_selection": True,
            "pin_evaluated": True,
        }
    if pinned_variant_uri is not None:
        _invalid("A pin cannot be evaluated before Trust and kill-switch gates")
    return {
        "selected_variant_uri": DIRECT_VARIANT_URI,
        "selection_status": "canonical_fallback",
        "reason_codes": [
            (
                "EXECUTION_VARIANT_TRUST_NOT_STABLE"
                if not trust_stable
                else "EXECUTION_VARIANT_MODE_DISABLED"
            ),
            "EXECUTION_VARIANT_CANONICAL_FALLBACK",
        ],
        "automatic_selection": False,
        "pin_evaluated": False,
    }


def _fixed_characterization(value: Mapping[str, Any]) -> dict[str, Any]:
    selected = validate_execution_variant_characterization(value)
    baseline = load_execution_variant_characterization()
    valid = selected["artifact_sha256"] == baseline["artifact_sha256"]
    valid = valid and selected["equivalent"] is True
    valid = valid and selected["fixed"] is True
    valid = valid and selected["mismatches"] == []
    valid = valid and set(selected["dimensions"].values()) == {"equivalent"}
    if not valid:
        raise ExecutionVariantContractError(
            "EXECUTION_VARIANT_CHARACTERIZATION_STALE",
            "Selection requires the exact fixed equivalent Characterization",
        )
    return selected


def _selection_trust(
    value: Mapping[str, Any], contract_digest: str
) -> dict[str, Any]:
    selected = _mapping(value, "current Product Trust")
    if set(selected) != {"trust_status", "contract_digest", "reason_codes"}:
        _invalid("Current Product Trust summary shape changed")
    if selected.get("trust_status") not in _CURRENT_TRUST_STATUSES:
        _invalid("Current Product Trust has not been evaluated")
    if selected.get("contract_digest") != contract_digest:
        _invalid("Current Product Trust contract binding changed")
    reasons = selected.get("reason_codes")
    if not isinstance(reasons, list) or len(reasons) != len(set(reasons)):
        _invalid("Current Product Trust reasons are invalid")
    return selected


def _characterization_reference(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "characterization_id": value["characterization_id"],
        "artifact_sha256": value["artifact_sha256"],
        "corpus_sha256": value["corpus"]["corpus_sha256"],
        "fixed": value["fixed"],
        "equivalent": value["equivalent"],
    }


def _candidates(
    *,
    trust_stable: bool,
    mode: str,
    pin_requested: bool,
    pinned_variant_uri: str | None,
) -> list[dict[str, Any]]:
    values = []
    for descriptor in execution_variant_descriptors():
        uri = descriptor["variant_uri"]
        if not trust_stable:
            eligible = False
            reasons = ["EXECUTION_VARIANT_TRUST_NOT_STABLE"]
        elif mode == DISABLED_MODE:
            eligible = False
            reasons = ["EXECUTION_VARIANT_MODE_DISABLED"]
        elif pin_requested and uri != pinned_variant_uri:
            eligible = False
            reasons = ["EXECUTION_VARIANT_NOT_PINNED"]
        else:
            eligible = True
            reasons = []
        topology = descriptor["implementation"]["topology"]
        values.append(
            {
                "variant_uri": uri,
                "descriptor_sha256": descriptor["descriptor_sha256"],
                "topology": topology,
                "local_topology_hops": _TOPOLOGY_HOPS[topology],
                "canonical": uri == DIRECT_VARIANT_URI,
                "eligible": eligible,
                "eligibility_reason_codes": reasons,
            }
        )
    return values


def _gates(
    *, trust_stable: bool, mode: str, pin_requested: bool
) -> list[dict[str, str]]:
    values = [{"gate": "characterization", "outcome": "passed"}]
    values.append(
        {
            "gate": "product_trust",
            "outcome": "passed" if trust_stable else "failed",
        }
    )
    if not trust_stable:
        values.extend(
            {"gate": gate, "outcome": "not_evaluated"}
            for gate in ("kill_switch", "pin", "secondary_objective")
        )
        return values
    values.append(
        {
            "gate": "kill_switch",
            "outcome": "passed" if mode == AUTOMATIC_MODE else "disabled",
        }
    )
    if mode == DISABLED_MODE:
        values.extend(
            {"gate": gate, "outcome": "not_evaluated"}
            for gate in ("pin", "secondary_objective")
        )
        return values
    values.append(
        {
            "gate": "pin",
            "outcome": "selected" if pin_requested else "not_requested",
        }
    )
    values.append(
        {
            "gate": "secondary_objective",
            "outcome": "not_evaluated" if pin_requested else "selected",
        }
    )
    return values


def _minimum_topology_variant() -> str:
    return min(
        execution_variant_descriptors(),
        key=lambda item: (
            _TOPOLOGY_HOPS[item["implementation"]["topology"]],
            item["variant_uri"],
        ),
    )["variant_uri"]


def _variant_uris() -> set[str]:
    return {item["variant_uri"] for item in execution_variant_descriptors()}


def _mapping(value: Mapping[str, Any], label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        _invalid(f"{label} must be an object")
    return copy.deepcopy(dict(value))


def _invalid(message: str) -> None:
    raise ExecutionVariantContractError(
        "EXECUTION_VARIANT_SELECTION_INVALID", message
    )


__all__ = [
    "AUTOMATIC_MODE",
    "DISABLED_MODE",
    "SELECTION_SCHEMA_VERSION",
    "build_execution_variant_selection",
    "selection_digest",
    "validate_execution_variant_selection",
]
