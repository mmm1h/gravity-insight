"""Value-free equivalence evidence for fixed Execution Variant pairs."""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from typing import Any

from .agent_runtime_contracts import canonical_digest, load_json_object
from .execution_variant_contract import (
    CHARACTERIZATION_ID,
    CHARACTERIZATION_SCHEMA_VERSION,
    CORPUS_ID,
    ExecutionVariantContractError,
    execution_variant_descriptors,
    product_reference,
    rollback_contract,
    validate_characterization_schema,
)
from .paths import CONTRACT_ROOT


_ARTIFACT = (
    CONTRACT_ROOT
    / "execution-variants"
    / "analysis-query-event-direct-plan-v1.json"
)
_DIMENSIONS = {
    "input_semantics": "input_sha256",
    "output_semantics": "output_sha256",
    "completeness": "completeness_sha256",
    "data_quality": "data_quality_sha256",
    "allowed_claims": "allowed_claims_sha256",
    "privacy": "privacy_sha256",
    "freshness": "freshness_sha256",
    "request_count": "request_count",
    "journey_regression": "journey_sha256",
}


def execution_evidence(
    *,
    input_value: Any,
    output_value: Any,
    completeness: Any,
    data_quality: Any,
    allowed_claims: Any,
    privacy_classification: str,
    freshness: Any,
    request_count: int,
    journey_value: Any,
) -> dict[str, Any]:
    """Reduce one controlled execution to value-free semantic digests."""

    if type(request_count) is not int or not 0 <= request_count <= 100_000:
        raise ExecutionVariantContractError(
            "EXECUTION_VARIANT_CONTRACT_INVALID",
            "Variant request count is outside its bounded evidence range",
        )
    return {
        "input_sha256": canonical_digest(input_value),
        "output_sha256": canonical_digest(output_value),
        "completeness_sha256": canonical_digest(completeness),
        "data_quality_sha256": canonical_digest(data_quality),
        "allowed_claims_sha256": canonical_digest(allowed_claims),
        "privacy_sha256": canonical_digest(
            {
                "classification": privacy_classification,
                "safe_output": output_value,
            }
        ),
        "freshness_sha256": canonical_digest(freshness),
        "request_count": request_count,
        "journey_sha256": canonical_digest(journey_value),
    }


def build_execution_variant_characterization(
    cases: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    selected_cases = _cases(cases)
    dimensions, mismatches = _comparison(selected_cases)
    descriptors = execution_variant_descriptors()
    equivalent = not mismatches
    artifact = {
        "schema_version": CHARACTERIZATION_SCHEMA_VERSION,
        "characterization_id": CHARACTERIZATION_ID,
        "product": product_reference(),
        "variants": [
            {
                "variant_uri": item["variant_uri"],
                "descriptor_sha256": item["descriptor_sha256"],
            }
            for item in descriptors
        ],
        "corpus": {
            "corpus_id": CORPUS_ID,
            "corpus_sha256": canonical_digest(selected_cases),
            "case_count": len(selected_cases),
            "case_ids": [item["case_id"] for item in selected_cases],
            "cases": selected_cases,
        },
        "dimensions": dimensions,
        "equivalent": equivalent,
        "fixed": True,
        "mismatches": mismatches,
        "rollback": rollback_contract(),
        "current_trust": {
            "trust_status": "not_evaluated",
            "contract_digest": product_reference()["contract_digest"],
            "reason_codes": [],
        },
        "selection_status": "disabled_until_r14_d",
        "automatic_selection": False,
        "network_called": False,
    }
    artifact["artifact_sha256"] = characterization_digest(artifact)
    return validate_execution_variant_characterization(artifact)


def load_execution_variant_characterization() -> dict[str, Any]:
    try:
        value = load_json_object(_ARTIFACT, "Execution Variant Characterization")
    except Exception as exc:
        raise ExecutionVariantContractError(
            "EXECUTION_VARIANT_CHARACTERIZATION_STALE",
            "packaged Characterization is unavailable",
        ) from exc
    selected = validate_execution_variant_characterization(value)
    if (
        selected["equivalent"] is not True
        or selected["current_trust"]["trust_status"] != "not_evaluated"
    ):
        raise ExecutionVariantContractError(
            "EXECUTION_VARIANT_CHARACTERIZATION_STALE",
            "packaged Characterization is not a fixed equivalent baseline",
        )
    return selected


def attach_current_variant_trust(
    artifact: Mapping[str, Any], trust: Mapping[str, Any]
) -> dict[str, Any]:
    selected = validate_execution_variant_characterization(artifact)
    current = dict(trust) if isinstance(trust, Mapping) else {}
    product = selected["product"]
    if (
        current.get("identity_kind") != "product"
        or current.get("selector") != product["selector"]
        or current.get("contract_digest") != product["contract_digest"]
    ):
        raise ExecutionVariantContractError(
            "EXECUTION_VARIANT_CHARACTERIZATION_STALE",
            "current Product Trust does not match the characterized contract",
        )
    reasons = current.get("reason_codes", [])
    if not isinstance(reasons, list) or any(
        not isinstance(reason, str) for reason in reasons
    ):
        raise ExecutionVariantContractError(
            "EXECUTION_VARIANT_CONTRACT_INVALID",
            "current Product Trust reasons are invalid",
        )
    result = copy.deepcopy(selected)
    result["current_trust"] = {
        "trust_status": current.get("trust_status"),
        "contract_digest": current["contract_digest"],
        "reason_codes": list(dict.fromkeys(reasons)),
    }
    return validate_execution_variant_characterization(result)


def validate_execution_variant_characterization(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    selected = validate_characterization_schema(value)
    if selected["characterization_id"] != CHARACTERIZATION_ID:
        _invalid("Characterization identity changed")
    if selected["product"] != product_reference():
        _stale("Characterization Product contract changed")
    expected_variants = [
        {
            "variant_uri": item["variant_uri"],
            "descriptor_sha256": item["descriptor_sha256"],
        }
        for item in execution_variant_descriptors()
    ]
    if selected["variants"] != expected_variants:
        _stale("Characterization Variant descriptors changed")
    cases = _validated_corpus(selected["corpus"])
    _validate_comparison(selected, cases)
    if selected["current_trust"]["contract_digest"] != product_reference()[
        "contract_digest"
    ]:
        _stale("Characterization Trust binding changed")
    if selected["rollback"] != rollback_contract():
        _stale("Characterization rollback contract changed")
    if selected["artifact_sha256"] != characterization_digest(selected):
        _stale("Characterization artifact digest changed")
    return selected


def characterization_digest(value: Mapping[str, Any]) -> str:
    selected = copy.deepcopy(dict(value))
    selected.pop("artifact_sha256", None)
    selected.pop("current_trust", None)
    return canonical_digest(selected)


def _cases(values: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    if isinstance(values, (str, bytes)) or not 1 <= len(values) <= 16:
        _invalid("Characterization corpus must contain 1 through 16 cases")
    selected = [copy.deepcopy(dict(value)) for value in values]
    for value in selected:
        if set(value) != {"case_id", "baseline", "candidate"}:
            _invalid("Characterization case shape changed")
    case_ids = [value.get("case_id") for value in selected]
    if any(not isinstance(case_id, str) or not case_id for case_id in case_ids):
        _invalid("Characterization case IDs must be non-empty strings")
    if len(case_ids) != len(set(case_ids)):
        _invalid("Characterization case IDs must be unique")
    return selected


def _comparison(
    cases: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, str], list[dict[str, str]]]:
    mismatches = []
    dimensions = {}
    for dimension, field in _DIMENSIONS.items():
        changed = [
            str(case["case_id"])
            for case in cases
            if case["baseline"].get(field) != case["candidate"].get(field)
        ]
        dimensions[dimension] = "mismatch" if changed else "equivalent"
        mismatches.extend(
            {
                "case_id": case_id,
                "dimension": dimension,
                "reason_code": f"EXECUTION_VARIANT_{dimension.upper()}_MISMATCH",
            }
            for case_id in changed
        )
    return dimensions, mismatches


def _validated_corpus(corpus: Mapping[str, Any]) -> list[dict[str, Any]]:
    cases = corpus["cases"]
    case_ids = [item["case_id"] for item in cases]
    valid = corpus["corpus_id"] == CORPUS_ID
    valid = valid and corpus["case_count"] == len(cases)
    valid = valid and corpus["case_ids"] == case_ids
    valid = valid and len(case_ids) == len(set(case_ids))
    valid = valid and corpus["corpus_sha256"] == canonical_digest(cases)
    if not valid:
        _stale("Characterization corpus identity changed")
    return cases


def _validate_comparison(
    artifact: Mapping[str, Any], cases: Sequence[Mapping[str, Any]]
) -> None:
    dimensions, mismatches = _comparison(cases)
    valid = artifact["dimensions"] == dimensions
    valid = valid and artifact["mismatches"] == mismatches
    valid = valid and artifact["equivalent"] is (not mismatches)
    if not valid:
        _stale("Characterization equivalence result changed")


def _invalid(message: str) -> None:
    raise ExecutionVariantContractError(
        "EXECUTION_VARIANT_CONTRACT_INVALID", message
    )


def _stale(message: str) -> None:
    raise ExecutionVariantContractError(
        "EXECUTION_VARIANT_CHARACTERIZATION_STALE", message
    )


__all__ = [
    "attach_current_variant_trust",
    "build_execution_variant_characterization",
    "characterization_digest",
    "execution_evidence",
    "load_execution_variant_characterization",
    "validate_execution_variant_characterization",
]
