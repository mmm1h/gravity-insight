"""Offline same-layer Capability Trust evaluation and dependency propagation."""

from __future__ import annotations

import copy
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta, timezone
from typing import Any

from .actionable_error_values import actual_value
from .agent_runtime_contracts import (
    AgentRuntimeContractError,
    validate_schema,
)
from .capability_contract import (
    capability_contracts,
    current_provider_fingerprint,
)
from .capability_validation import (
    CapabilityValidationError,
    CapabilityValidationStore,
    parse_utc_timestamp,
    validation_digest,
)
from .data_quality import (
    data_quality_result,
    meets_data_quality,
    validate_data_quality_result,
)
from .errors import InputValidationError


TRUST_RESULT_SCHEMA_VERSION = "gravity.capability-trust-result.v1"
_TRUST_SCHEMA = "capability-trust-result-v1.schema.json"
_IDENTITY_KINDS = frozenset({"operation", "product", "composite"})
_TRUST_STATUSES = frozenset(
    {"stable", "unknown", "degraded", "blocked", "quarantined"}
)
_STATUS_PRECEDENCE = ("quarantined", "blocked", "unknown", "degraded", "stable")
_COMPLETENESS_RANK = {"unknown": 0, "prefix": 1, "complete": 2}
ProviderResolver = Callable[[Mapping[str, Any]], str | None]
Clock = Callable[[], datetime]


class CapabilityTrustService:
    """Evaluate Capability contracts and current Validation without network I/O."""

    def __init__(
        self,
        validation_store: CapabilityValidationStore | None = None,
        *,
        contracts: Mapping[tuple[str, str], Mapping[str, Any]] | None = None,
        provider_resolver: ProviderResolver = current_provider_fingerprint,
        clock: Clock | None = None,
    ) -> None:
        self._validation_store = (
            validation_store
            if validation_store is not None
            else CapabilityValidationStore.for_current_principal()
        )
        self._contracts = (
            {
                key: copy.deepcopy(dict(value))
                for key, value in contracts.items()
            }
            if contracts is not None
            else {
                (
                    str(artifact["contract"]["identity_kind"]),
                    str(artifact["contract"]["selector"]),
                ): artifact
                for artifact in capability_contracts()
            }
        )
        self._provider_resolver = provider_resolver
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def trust(self, identity_kind: str, selector: str) -> dict[str, Any]:
        key = _identity(identity_kind, selector)
        return self._evaluate(key, ())

    def validate(self, value: Mapping[str, Any]) -> dict[str, Any]:
        try:
            identity = (str(value["identity_kind"]), str(value["selector"]))
        except (KeyError, TypeError):
            raise InputValidationError(
                "actual value: invalid shape; Capability Validation must name "
                "identity_kind and selector",
                field="input",
            ) from None
        store = CapabilityValidationStore(values=[value])
        service = CapabilityTrustService(
            store,
            contracts=self._contracts,
            provider_resolver=self._provider_resolver,
            clock=self._clock,
        )
        return service.trust(*identity)

    def impact(self, request: Mapping[str, Any]) -> dict[str, Any]:
        from .capability_impact import capability_impact

        return capability_impact(request)

    def _evaluate(
        self,
        key: tuple[str, str],
        stack: tuple[tuple[str, str], ...],
    ) -> dict[str, Any]:
        artifact = self._contracts.get(key)
        if artifact is None:
            return _missing_result(*key)
        if key in stack:
            return _cycle_result(artifact)
        contract = artifact["contract"]
        provider, provider_status, provider_reasons = self._provider(contract)
        own_status, own_reasons, completeness, quality, validation = (
            self._own_validation(artifact, provider)
        )
        dependency_results: list[dict[str, Any]] = []
        dependency_statuses: list[str] = []
        dependency_reasons: list[str] = []
        for requirement in contract["dependencies"]:
            child = self._evaluate(
                (
                    str(requirement["identity_kind"]),
                    str(requirement["selector"]),
                ),
                (*stack, key),
            )
            dependency_results.append(_dependency_summary(child))
            status, reasons = assess_capability_requirement(child, requirement)
            dependency_statuses.append(status)
            dependency_reasons.extend(reasons)
        lifecycle_status, lifecycle_reasons = _lifecycle_status(contract["lifecycle"])
        status = _aggregate_trust_status(
            [
                provider_status,
                own_status,
                lifecycle_status,
                *dependency_statuses,
            ]
        )
        reasons = list(
            dict.fromkeys(
                [
                    *provider_reasons,
                    *own_reasons,
                    *lifecycle_reasons,
                    *dependency_reasons,
                ]
            )
        )
        result = {
            "schema_version": TRUST_RESULT_SCHEMA_VERSION,
            "identity_kind": contract["identity_kind"],
            "selector": contract["selector"],
            "contract_version": contract["contract_version"],
            "lifecycle": contract["lifecycle"],
            "trust_status": status,
            "contract_digest": artifact["digest"],
            "provider": {
                "kind": contract["provider"]["kind"],
                "expected_fingerprint": contract["provider"]["fingerprint"],
                "current_fingerprint": provider,
                "status": _provider_label(
                    contract["provider"]["fingerprint"], provider
                ),
            },
            "validation": validation,
            "completeness": completeness,
            "data_quality": quality,
            "dependencies": dependency_results,
            "allowed_claims": (
                copy.deepcopy(contract["allowed_claims"])
                if status == "stable"
                else []
            ),
            "reason_codes": reasons,
            "network_called": False,
        }
        _validate_trust_result(result)
        return result

    def _provider(
        self, contract: Mapping[str, Any]
    ) -> tuple[str | None, str, list[str]]:
        try:
            current = self._provider_resolver(contract)
        except (
            AgentRuntimeContractError,
            KeyError,
            OSError,
            RuntimeError,
            TypeError,
            ValueError,
        ):
            return None, "quarantined", ["CAPABILITY_PROVIDER_UNAVAILABLE"]
        expected = contract["provider"]["fingerprint"]
        if current is None:
            return None, "quarantined", ["CAPABILITY_PROVIDER_MISSING"]
        if current != expected:
            return current, "quarantined", ["CAPABILITY_FINGERPRINT_MISMATCH"]
        return current, "stable", []

    def _own_validation(
        self,
        artifact: Mapping[str, Any],
        current_provider: str | None,
    ) -> tuple[str, list[str], str, dict[str, Any], dict[str, Any] | None]:
        contract = artifact["contract"]
        unknown_quality = data_quality_result(())
        try:
            validation = self._validation_store.get(
                str(contract["identity_kind"]), str(contract["selector"])
            )
        except AgentRuntimeContractError:
            return (
                "quarantined",
                ["CAPABILITY_VALIDATION_INVALID"],
                contract["declared_completeness"],
                unknown_quality,
                None,
            )
        if validation is None:
            return (
                "unknown",
                ["CAPABILITY_VALIDATION_MISSING"],
                contract["declared_completeness"],
                unknown_quality,
                None,
            )
        return _evaluate_validation(
            validation,
            artifact=artifact,
            current_provider=current_provider,
            now=self._clock(),
        )


def _evaluate_validation(
    validation: Mapping[str, Any],
    *,
    artifact: Mapping[str, Any],
    current_provider: str | None,
    now: datetime,
) -> tuple[str, list[str], str, dict[str, Any], dict[str, Any]]:
    contract = artifact["contract"]
    quality = copy.deepcopy(validation["data_quality"])
    public = _public_validation(validation)
    gate = _validation_gate(
        validation,
        artifact=artifact,
        current_provider=current_provider,
        now=now,
    )
    if gate is not None:
        status, reason = gate
        if status == "unknown":
            return (
                status,
                [reason],
                validation["completeness"],
                quality,
                public,
            )
        return _validation_failure(reason, contract, quality, public)
    return _accepted_validation(validation, contract, quality, public)


def _validation_gate(
    validation: Mapping[str, Any],
    *,
    artifact: Mapping[str, Any],
    current_provider: str | None,
    now: datetime,
) -> tuple[str, str] | None:
    contract = artifact["contract"]
    if not (
        validation["identity_kind"] == contract["identity_kind"]
        and validation["selector"] == contract["selector"]
        and validation["contract_version"] == contract["contract_version"]
        and validation["contract_digest"] == artifact["digest"]
        and validation["provider_fingerprint"] == current_provider
    ):
        return "quarantined", "CAPABILITY_FINGERPRINT_MISMATCH"
    validated_at = parse_utc_timestamp(validation["validated_at"])
    expires_at = parse_utc_timestamp(validation["expires_at"])
    lifetime = expires_at - validated_at
    if lifetime > timedelta(seconds=contract["validation_ttl_seconds"]):
        return "quarantined", "CAPABILITY_VALIDATION_INVALID"
    current = now.astimezone(timezone.utc)
    if validated_at > current:
        return "quarantined", "CAPABILITY_VALIDATION_INVALID"
    if expires_at <= current:
        return "unknown", "CAPABILITY_VALIDATION_EXPIRED"
    if not _completeness_within_contract(
        validation["completeness"], contract["declared_completeness"]
    ):
        return "quarantined", "CAPABILITY_VALIDATION_CONTRADICTS_CONTRACT"
    return None


def _accepted_validation(
    validation: Mapping[str, Any],
    contract: Mapping[str, Any],
    quality: dict[str, Any],
    public: dict[str, Any],
) -> tuple[str, list[str], str, dict[str, Any], dict[str, Any]]:
    selected_status = str(validation["trust_status"])
    reasons = list(validation["reason_codes"])
    if selected_status == "stable" and not meets_data_quality(
        quality["status"], contract["required_data_quality"]
    ):
        reason = (
            "DATA_QUALITY_FAILED"
            if quality["status"] == "fail"
            else "DATA_QUALITY_UNPROVEN"
        )
        return (
            "blocked",
            [reason],
            validation["completeness"],
            quality,
            public,
        )
    if selected_status == "unknown" and not reasons:
        reasons = ["CAPABILITY_VALIDATION_UNKNOWN"]
    if selected_status in {"blocked", "quarantined", "degraded"} and not reasons:
        reasons = [f"CAPABILITY_VALIDATION_{selected_status.upper()}"]
    return (
        selected_status,
        reasons,
        validation["completeness"],
        quality,
        public,
    )


def _validation_failure(
    reason: str,
    contract: Mapping[str, Any],
    quality: Mapping[str, Any],
    public: Mapping[str, Any],
) -> tuple[str, list[str], str, dict[str, Any], dict[str, Any]]:
    return (
        "quarantined",
        [reason],
        contract["declared_completeness"],
        copy.deepcopy(dict(quality)),
        copy.deepcopy(dict(public)),
    )


def assess_capability_requirement(
    result: Mapping[str, Any], requirement: Mapping[str, Any]
) -> tuple[str, list[str]]:
    required_completeness = str(requirement["completeness"])
    if not meets_completeness(str(result["completeness"]), required_completeness):
        return "blocked", ["COMPLETENESS_INSUFFICIENT"]
    status = str(result["trust_status"])
    if status == "quarantined":
        return "blocked", ["DEPENDENCY_QUARANTINED"]
    if status == "blocked":
        return "blocked", ["DEPENDENCY_BLOCKED"]
    if status == "unknown":
        return "unknown", ["DEPENDENCY_VALIDATION_UNKNOWN"]
    if status == "degraded" and requirement["minimum_trust"] == "stable":
        return "blocked", ["DEPENDENCY_TRUST_INSUFFICIENT"]
    quality = str(result["data_quality"]["status"])
    if not meets_data_quality(quality, str(requirement["data_quality"])):
        reason = "DATA_QUALITY_FAILED" if quality == "fail" else "DATA_QUALITY_UNPROVEN"
        return "blocked", [reason]
    return "stable", []


def meets_completeness(actual: str, required: str) -> bool:
    if actual not in _COMPLETENESS_RANK or required not in _COMPLETENESS_RANK:
        return False
    return _COMPLETENESS_RANK[actual] >= _COMPLETENESS_RANK[required]


def _completeness_within_contract(actual: str, declared: str) -> bool:
    return meets_completeness(declared, actual)


def _public_validation(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "digest": validation_digest(value),
        "validated_at": value["validated_at"],
        "expires_at": value["expires_at"],
        "trust_status": value["trust_status"],
        "completeness": value["completeness"],
        "data_quality": copy.deepcopy(value["data_quality"]),
        "evidence_references": copy.deepcopy(value["evidence_references"]),
    }


def _dependency_summary(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "identity_kind": value["identity_kind"],
        "selector": value["selector"],
        "contract_version": value["contract_version"],
        "trust_status": value["trust_status"],
        "contract_digest": value["contract_digest"],
        "completeness": value["completeness"],
        "data_quality_status": value["data_quality"]["status"],
        "reason_codes": copy.deepcopy(value["reason_codes"]),
    }


def _lifecycle_status(lifecycle: str) -> tuple[str, list[str]]:
    if lifecycle == "revoked":
        return "blocked", ["CAPABILITY_REVOKED"]
    if lifecycle == "deprecated":
        return "degraded", ["CAPABILITY_DEPRECATED"]
    return "stable", []


def _aggregate_trust_status(statuses: list[str]) -> str:
    selected = set(statuses)
    if selected - _TRUST_STATUSES:
        return "quarantined"
    return next(status for status in _STATUS_PRECEDENCE if status in selected)


def _provider_label(expected: str, current: str | None) -> str:
    if current is None:
        return "missing"
    return "matched" if current == expected else "mismatch"


def _identity(identity_kind: Any, selector: Any) -> tuple[str, str]:
    kind = str(identity_kind)
    selected = str(selector).strip()
    if kind not in _IDENTITY_KINDS:
        raise InputValidationError(
            f"actual value: {actual_value(identity_kind)}; identity_kind must be "
            "operation, product, or composite",
            field="identity_kind",
        )
    if not selected or len(selected) > 256:
        raise InputValidationError(
            f"actual value: {actual_value(selector)}; selector must be a bounded "
            "Capability identity",
            field="selector",
        )
    return kind, selected


def _missing_result(identity_kind: str, selector: str) -> dict[str, Any]:
    result = {
        "schema_version": TRUST_RESULT_SCHEMA_VERSION,
        "identity_kind": identity_kind,
        "selector": selector,
        "contract_version": None,
        "lifecycle": None,
        "trust_status": "blocked",
        "contract_digest": None,
        "provider": {
            "kind": None,
            "expected_fingerprint": None,
            "current_fingerprint": None,
            "status": "unavailable",
        },
        "validation": None,
        "completeness": "unknown",
        "data_quality": data_quality_result(()),
        "dependencies": [],
        "allowed_claims": [],
        "reason_codes": ["CAPABILITY_TRUST_CONTRACT_MISSING"],
        "network_called": False,
    }
    _validate_trust_result(result)
    return result


def _cycle_result(artifact: Mapping[str, Any]) -> dict[str, Any]:
    contract = artifact["contract"]
    result = _missing_result(contract["identity_kind"], contract["selector"])
    result.update(
        {
            "contract_version": contract["contract_version"],
            "lifecycle": contract["lifecycle"],
            "trust_status": "quarantined",
            "contract_digest": artifact["digest"],
            "reason_codes": ["CAPABILITY_DEPENDENCY_CYCLE"],
        }
    )
    _validate_trust_result(result)
    return result


def _validate_trust_result(value: Mapping[str, Any]) -> None:
    validate_data_quality_result(value["data_quality"])
    validate_schema(value, _TRUST_SCHEMA, "Capability Trust Result")


__all__ = [
    "CapabilityTrustService",
    "TRUST_RESULT_SCHEMA_VERSION",
    "assess_capability_requirement",
    "meets_completeness",
]
