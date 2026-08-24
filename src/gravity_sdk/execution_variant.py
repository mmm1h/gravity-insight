"""Offline inspection service for fixed, characterized Execution Variants."""

from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Any

from .actionable_error_values import actual_value
from .errors import InputValidationError
from .execution_variant_characterization import (
    attach_current_variant_trust,
    load_execution_variant_characterization,
    validate_execution_variant_characterization,
)
from .execution_variant_contract import (
    ExecutionVariantContractError,
    PRODUCT_SELECTOR,
    execution_variant_descriptors,
    validate_execution_variant,
)


class ExecutionVariantService:
    """Inspect one closed Variant set without selecting or executing a path."""

    def __init__(self, trust_factory: Callable[[], Any] | None = None) -> None:
        self._trust_factory = trust_factory or _default_trust_service

    def __repr__(self) -> str:
        return "<ExecutionVariantService fixed inspection only>"

    def list(self, product_selector: str | None = None) -> dict[str, Any]:
        if product_selector is not None:
            _product_selector(product_selector)
        variants = [_summary(item) for item in execution_variant_descriptors()]
        return {
            "schema_version": "gravity.execution-variant-list.v1",
            "status": "success",
            "product_selector": PRODUCT_SELECTOR,
            "count": len(variants),
            "variants": variants,
            "selection_status": "disabled_until_r14_d",
            "network_called": False,
        }

    def describe(self, variant_uri: str) -> dict[str, Any]:
        selected = _variant_uri(variant_uri)
        descriptor = next(
            (
                item
                for item in execution_variant_descriptors()
                if item["variant_uri"] == selected
            ),
            None,
        )
        if descriptor is None:
            _unknown_variant(variant_uri)
        return {
            "schema_version": "gravity.execution-variant-description.v1",
            "status": "success",
            "ok": True,
            "variant": copy.deepcopy(descriptor),
            "selection_status": "disabled_until_r14_d",
            "network_called": False,
        }

    def characterization(self, product_selector: str) -> dict[str, Any]:
        selected = _product_selector(product_selector)
        trust_service = self._trust_factory()
        trust_method = getattr(trust_service, "trust", None)
        if not callable(trust_method):
            raise ExecutionVariantContractError(
                "EXECUTION_VARIANT_CHARACTERIZATION_STALE",
                "Capability Trust owner is unavailable",
            )
        trust = trust_method("product", selected)
        artifact = load_execution_variant_characterization()
        return attach_current_variant_trust(artifact, trust)


def _summary(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "variant_uri": value["variant_uri"],
        "product": copy.deepcopy(value["product"]),
        "topology": value["implementation"]["topology"],
        "fixed": value["implementation"]["fixed"],
        "automatic_selection": value["automatic_selection"],
        "descriptor_sha256": value["descriptor_sha256"],
    }


def _product_selector(value: Any) -> str:
    if value != PRODUCT_SELECTOR:
        raise InputValidationError(
            f"actual value: {actual_value(value)}; allowed value: {PRODUCT_SELECTOR}",
            field="product_selector",
            code="EXECUTION_VARIANT_PRODUCT_UNKNOWN",
            next_action="Run sdk.execution_variants.list() and use its exact Product selector.",
        )
    return PRODUCT_SELECTOR


def _variant_uri(value: Any) -> str:
    if not isinstance(value, str) or not value:
        _unknown_variant(value)
    return value


def _unknown_variant(value: Any) -> None:
    raise InputValidationError(
        f"actual value: {actual_value(value)}; allowed value: a URI from sdk.execution_variants.list()",
        field="variant_uri",
        code="EXECUTION_VARIANT_UNKNOWN",
        next_action="Inspect the offline Variant registry and use an exact URI.",
    )


def _default_trust_service() -> Any:
    from .capability_trust import CapabilityTrustService

    return CapabilityTrustService()


__all__ = [
    "ExecutionVariantContractError",
    "ExecutionVariantService",
    "validate_execution_variant",
    "validate_execution_variant_characterization",
]
