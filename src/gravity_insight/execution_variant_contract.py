"""Closed Execution Variant descriptors for characterized Product paths."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from functools import lru_cache
from typing import Any

from .agent_runtime_contracts import (
    AgentRuntimeContractError,
    canonical_digest,
    validate_schema,
)
from .capability_contract import capability_contracts


VARIANT_SCHEMA_VERSION = "gravity.execution-variant.v1"
CHARACTERIZATION_SCHEMA_VERSION = "gravity.execution-variant-characterization.v1"
PRODUCT_SELECTOR = "analysis.query.spec:event"
DIRECT_VARIANT_URI = (
    "gravity.execution-variant/analysis-query-event/direct@1"
)
PLAN_VARIANT_URI = (
    "gravity.execution-variant/analysis-query-event/plan-adapter@1"
)
CHARACTERIZATION_ID = "analysis-query-event.direct-plan@1"
CORPUS_ID = "analysis-query-event.variant-equivalence@1"
REFERENCE_JOURNEY = "analysis.merge2.ap-cost-anomaly-localization"
_VARIANT_SCHEMA = "execution-variant-v1.schema.json"
_CHARACTERIZATION_SCHEMA = "execution-variant-characterization-v1.schema.json"
_RESULT_PROJECTION = "gravity.analysis-query-safe-projection@1"
_IMPLEMENTATIONS = {
    DIRECT_VARIANT_URI: {
        "topology": "direct_product",
        "owner": "gravity-runtime/analysis",
        "entrypoint": "gravity_insight.sdk_analysis.AnalysisSdkMixin.analysis_query",
        "fixed": True,
    },
    PLAN_VARIANT_URI: {
        "topology": "plan_adapter",
        "owner": "gravity-runtime/plan",
        "entrypoint": (
            "gravity_insight.plan_analysis_adapter.execute_analysis_query_plan"
        ),
        "fixed": True,
    },
}


class ExecutionVariantContractError(AgentRuntimeContractError):
    """A fixed Variant descriptor or Characterization is invalid or stale."""

    def __init__(self, reason_code: str, message: str) -> None:
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {message}")


def execution_variant_descriptors() -> tuple[dict[str, Any], ...]:
    """Return the two statically owned descriptors without executable hooks."""

    return copy.deepcopy(_descriptors())


def validate_execution_variant(value: Mapping[str, Any]) -> dict[str, Any]:
    selected = _mapping(value, "Execution Variant")
    try:
        validate_schema(selected, _VARIANT_SCHEMA, "Execution Variant")
    except AgentRuntimeContractError as exc:
        raise ExecutionVariantContractError(
            "EXECUTION_VARIANT_CONTRACT_INVALID", str(exc)
        ) from exc
    uri = str(selected["variant_uri"])
    implementation = _IMPLEMENTATIONS.get(uri)
    if implementation is None or selected["implementation"] != implementation:
        raise ExecutionVariantContractError(
            "EXECUTION_VARIANT_UNKNOWN",
            "Variant identity is not one of the two fixed Runtime entries",
        )
    product_artifact = _product_capability()
    product = product_artifact["contract"]
    expected_product = _product_reference(product_artifact)
    if selected["product"] != expected_product:
        raise ExecutionVariantContractError(
            "EXECUTION_VARIANT_CHARACTERIZATION_STALE",
            "Variant Product contract binding changed",
        )
    if selected["semantics"] != _semantics(product):
        raise ExecutionVariantContractError(
            "EXECUTION_VARIANT_CONTRACT_INVALID",
            "Variant semantic contract changed",
        )
    if selected["trust_requirement"] != {
        "identity_kind": "product",
        "selector": PRODUCT_SELECTOR,
        "minimum_trust": "stable",
    }:
        raise ExecutionVariantContractError(
            "EXECUTION_VARIANT_CONTRACT_INVALID",
            "Variant Trust requirement changed",
        )
    if selected["rollback"] != rollback_contract():
        raise ExecutionVariantContractError(
            "EXECUTION_VARIANT_CONTRACT_INVALID",
            "Variant rollback contract changed",
        )
    if selected["descriptor_sha256"] != descriptor_digest(selected):
        raise ExecutionVariantContractError(
            "EXECUTION_VARIANT_CONTRACT_INVALID",
            "Variant descriptor digest changed",
        )
    return selected


def validate_characterization_schema(value: Mapping[str, Any]) -> dict[str, Any]:
    selected = _mapping(value, "Execution Variant Characterization")
    try:
        validate_schema(
            selected,
            _CHARACTERIZATION_SCHEMA,
            "Execution Variant Characterization",
        )
    except AgentRuntimeContractError as exc:
        raise ExecutionVariantContractError(
            "EXECUTION_VARIANT_CONTRACT_INVALID", str(exc)
        ) from exc
    return selected


def descriptor_digest(value: Mapping[str, Any]) -> str:
    selected = dict(value)
    selected.pop("descriptor_sha256", None)
    return canonical_digest(selected)


def product_reference() -> dict[str, str]:
    return copy.deepcopy(_product_reference(_product_capability()))


def rollback_contract() -> dict[str, Any]:
    return {
        "canonical_variant_uri": DIRECT_VARIANT_URI,
        "strategy": "pin_canonical_direct",
        "capability_preserved": True,
    }


@lru_cache(maxsize=1)
def _descriptors() -> tuple[dict[str, Any], ...]:
    product_artifact = _product_capability()
    product = product_artifact["contract"]
    values = []
    for uri in (DIRECT_VARIANT_URI, PLAN_VARIANT_URI):
        descriptor = {
            "schema_version": VARIANT_SCHEMA_VERSION,
            "variant_uri": uri,
            "product": _product_reference(product_artifact),
            "implementation": copy.deepcopy(_IMPLEMENTATIONS[uri]),
            "semantics": _semantics(product),
            "trust_requirement": {
                "identity_kind": "product",
                "selector": PRODUCT_SELECTOR,
                "minimum_trust": "stable",
            },
            "rollback": rollback_contract(),
            "automatic_selection": False,
            "network_called": False,
        }
        descriptor["descriptor_sha256"] = descriptor_digest(descriptor)
        values.append(validate_execution_variant(descriptor))
    return tuple(values)


@lru_cache(maxsize=1)
def _product_capability() -> dict[str, Any]:
    selected = next(
        (
            artifact
            for artifact in capability_contracts()
            if artifact["contract"]["identity_kind"] == "product"
            and artifact["contract"]["selector"] == PRODUCT_SELECTOR
        ),
        None,
    )
    if selected is None:
        raise ExecutionVariantContractError(
            "EXECUTION_VARIANT_CHARACTERIZATION_STALE",
            "characterized Product Capability is unavailable",
        )
    return copy.deepcopy(selected)


def _product_reference(artifact: Mapping[str, Any]) -> dict[str, str]:
    contract = artifact["contract"]
    return {
        "identity_kind": "product",
        "selector": PRODUCT_SELECTOR,
        "contract_version": str(contract["contract_version"]),
        "contract_digest": str(artifact["digest"]),
    }


def _semantics(product: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "input_schema_version": "gravity-insight.analysis-query-spec.v1",
        "output_schema_version": "gravity-insight.read.v1",
        "result_projection": _RESULT_PROJECTION,
        "completeness_source": "product_capability_and_result",
        "data_quality_source": "product_capability_and_result",
        "allowed_claims": copy.deepcopy(product["allowed_claims"]),
        "privacy_classification": str(product["privacy_classification"]),
        "freshness": "same_upstream_response",
        "request_count": "same_compiled_operation_and_pagination",
        "journey_ids": [REFERENCE_JOURNEY],
    }


def _mapping(value: Mapping[str, Any], label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ExecutionVariantContractError(
            "EXECUTION_VARIANT_CONTRACT_INVALID", f"{label} must be an object"
        )
    return copy.deepcopy(dict(value))


__all__ = [
    "CHARACTERIZATION_ID",
    "CHARACTERIZATION_SCHEMA_VERSION",
    "CORPUS_ID",
    "DIRECT_VARIANT_URI",
    "ExecutionVariantContractError",
    "PLAN_VARIANT_URI",
    "PRODUCT_SELECTOR",
    "REFERENCE_JOURNEY",
    "VARIANT_SCHEMA_VERSION",
    "descriptor_digest",
    "execution_variant_descriptors",
    "product_reference",
    "rollback_contract",
    "validate_characterization_schema",
    "validate_execution_variant",
]
