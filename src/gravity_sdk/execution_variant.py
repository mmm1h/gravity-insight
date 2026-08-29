"""Offline inspection and selection for fixed characterized Execution Variants."""

from __future__ import annotations

import copy
import os
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
from .execution_variant_selection import (
    AUTOMATIC_MODE,
    DISABLED_MODE,
    build_execution_variant_selection,
    validate_execution_variant_selection,
)


_SELECTION_MODE_ENV = "GRAVITY_EXECUTION_VARIANT_MODE"


class ExecutionVariantService:
    """Inspect and select within one closed fixed Variant set."""

    def __init__(self, trust_factory: Callable[[], Any] | None = None) -> None:
        self._trust_factory = trust_factory or _default_trust_service

    def __repr__(self) -> str:
        return "<ExecutionVariantService fixed offline selection>"

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
            "selection_status": "trust_gated",
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
            "selection_status": "trust_gated",
            "network_called": False,
        }

    def characterization(self, product_selector: str) -> dict[str, Any]:
        selected = _product_selector(product_selector)
        artifact = load_execution_variant_characterization()
        trust_service = self._trust_factory()
        trust_method = getattr(trust_service, "trust", None)
        if not callable(trust_method):
            raise ExecutionVariantContractError(
                "EXECUTION_VARIANT_CHARACTERIZATION_STALE",
                "Capability Trust owner is unavailable",
            )
        trust = trust_method("product", selected)
        return attach_current_variant_trust(artifact, trust)

    def select(
        self,
        product_selector: str = PRODUCT_SELECTOR,
        *,
        pinned_variant_uri: str | None = None,
    ) -> dict[str, Any]:
        selected = _product_selector(product_selector)
        characterization = self.characterization(selected)
        mode = _selection_mode()
        pin_requested = pinned_variant_uri is not None
        evaluated_pin = None
        if (
            characterization["current_trust"]["trust_status"] == "stable"
            and mode == AUTOMATIC_MODE
            and pin_requested
        ):
            evaluated_pin = _known_variant_uri(pinned_variant_uri)
        return build_execution_variant_selection(
            characterization,
            mode=mode,
            pin_requested=pin_requested,
            pinned_variant_uri=evaluated_pin,
        )


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


def _known_variant_uri(value: Any) -> str:
    selected = _variant_uri(value)
    if selected not in {
        item["variant_uri"] for item in execution_variant_descriptors()
    }:
        _unknown_variant(value)
    return selected


def _selection_mode() -> str:
    selected = os.environ.get(_SELECTION_MODE_ENV, AUTOMATIC_MODE)
    if selected not in {AUTOMATIC_MODE, DISABLED_MODE}:
        raise InputValidationError(
            f"actual value: {actual_value(selected)}; allowed values: automatic, disabled",
            field="execution_variant_mode",
            code="EXECUTION_VARIANT_MODE_INVALID",
            next_action=(
                f"Set {_SELECTION_MODE_ENV}=automatic or disabled, then retry."
            ),
        )
    return selected


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
    "validate_execution_variant_selection",
]
