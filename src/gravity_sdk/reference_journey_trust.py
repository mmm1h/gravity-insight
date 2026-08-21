"""Same-layer Trust and Data Quality evaluation for the R01 Product."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .fingerprints import contract_fingerprint
from .analysis_playbook_catalog import (
    metric_anomaly_playbook_definition,
    playbook_definition_fingerprint,
)
from .models import load_operation_manifest
from .reference_journey_contract import reference_artifacts
from .result_audit import SCHEMA_VERSION as RESULT_AUDIT_SCHEMA_VERSION


TRUST_RESULT_SCHEMA_VERSION = "gravity.capability-trust-result.v1"
VALIDATION_SCHEMA_VERSION = "gravity.capability-validation.v1"
DATA_QUALITY_SCHEMA_VERSION = "gravity.data-quality-result.v1"
_PACKAGE_ROOT = Path(__file__).resolve().parent
_VALIDATION_FIELDS = frozenset(
    {
        "schema_version",
        "selector",
        "contract_digest",
        "provider_fingerprint",
        "validated_at",
        "expires_at",
        "trust_status",
        "completeness",
        "data_quality",
        "reason_codes",
    }
)


def evaluate_reference_trust(
    validation: Mapping[str, Any] | None = None,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Evaluate the exact Product contract without performing network I/O."""

    artifact = reference_artifacts()["capability_trust"]
    contract = artifact["contract"]
    expected_dependency = contract["dependencies"][0]
    operation = _operation_state(expected_dependency["operation_id"])
    definition_fingerprint = playbook_definition_fingerprint()
    reasons: list[str] = []
    status = "stable"
    if definition_fingerprint != contract["definition_fingerprint"]:
        status = "quarantined"
        reasons.append("CAPABILITY_FINGERPRINT_MISMATCH")
    elif (
        operation["operation_id"] != expected_dependency["operation_id"]
        or operation["contract_version"] != expected_dependency["contract_version"]
        or operation["contract_fingerprint"]
        != expected_dependency["contract_fingerprint"]
    ):
        status = "quarantined"
        reasons.append("CAPABILITY_FINGERPRINT_MISMATCH")
    elif operation["completeness"] != contract["required_completeness"]:
        status = "blocked"
        reasons.append("COMPLETENESS_INSUFFICIENT")
    elif validation is None:
        status = "unknown"
        reasons.append("CAPABILITY_VALIDATION_MISSING")
    else:
        validation_status, validation_reasons = _validation_status(
            validation,
            contract_digest=artifact["digest"],
            provider_fingerprint=operation["contract_fingerprint"],
            required_completeness=contract["required_completeness"],
            required_data_quality=contract["required_data_quality"],
            validation_ttl_seconds=contract["validation_ttl_seconds"],
            now=now or datetime.now(timezone.utc),
        )
        status = validation_status
        reasons.extend(validation_reasons)
    return {
        "schema_version": TRUST_RESULT_SCHEMA_VERSION,
        "identity_kind": contract["identity_kind"],
        "selector": contract["selector"],
        "lifecycle": contract["lifecycle"],
        "trust_status": status,
        "contract_digest": artifact["digest"],
        "definition_fingerprint": definition_fingerprint,
        "operation": operation,
        "validation": copy.deepcopy(dict(validation)) if validation is not None else None,
        "required_completeness": contract["required_completeness"],
        "required_data_quality": contract["required_data_quality"],
        "allowed_claims": copy.deepcopy(contract["allowed_claims"])
        if status == "stable"
        else [],
        "reason_codes": list(dict.fromkeys(reasons)),
        "network_called": False,
    }


def evaluate_playbook_data_quality(
    result: Mapping[str, Any], *, completeness: str
) -> dict[str, Any]:
    """Check the R01 result facts without inferring missing completeness."""

    playbook_ok = _playbook_result_is_valid(result)
    audits_ok = _query_audits_are_valid(
        result, required_ids=_required_query_step_ids()
    )
    checks: list[dict[str, Any]] = [
        {"check_id": "playbook-result", "status": "pass" if playbook_ok else "fail"},
        {"check_id": "query-result-audit", "status": "pass" if audits_ok else "fail"},
        {"check_id": "completeness", "status": completeness},
    ]
    reasons: list[str] = []
    if not playbook_ok or not audits_ok:
        reasons.append("DATA_QUALITY_FAILED")
    if completeness != "complete":
        reasons.append("DATA_QUALITY_UNPROVEN")
    return {
        "schema_version": DATA_QUALITY_SCHEMA_VERSION,
        "status": _data_quality_status(reasons),
        "checks": checks,
        "reason_codes": list(dict.fromkeys(reasons)),
    }


def _playbook_result_is_valid(result: Mapping[str, Any]) -> bool:
    return (
        isinstance(result, Mapping)
        and result.get("schema_version")
        == "gravity.metric-anomaly-localization-result.v1"
        and result.get("ok") is True
        and result.get("status") == "success"
        and isinstance(result.get("conclusion"), Mapping)
    )


def _query_audits_are_valid(
    result: Mapping[str, Any], *, required_ids: frozenset[str]
) -> bool:
    if not isinstance(result, Mapping):
        return False
    query_steps = [
        step
        for step in result.get("steps", ())
        if isinstance(step, Mapping) and step.get("kind") == "query"
    ]
    if not _query_ids_match(query_steps, required_ids=required_ids):
        return False
    return all(_query_step_audit_is_valid(step) for step in query_steps)


def _query_ids_match(
    steps: list[Mapping[str, Any]], *, required_ids: frozenset[str]
) -> bool:
    selected_ids = [step.get("id") for step in steps]
    if not required_ids or any(
        not isinstance(step_id, str) or not step_id
        for step_id in selected_ids
    ):
        return False
    return (
        len(steps) == len(required_ids)
        and frozenset(selected_ids) == required_ids
        and len(set(selected_ids)) == len(selected_ids)
    )


def _query_step_audit_is_valid(step: Mapping[str, Any]) -> bool:
    audit = step.get("result_audit")
    return (
        isinstance(audit, Mapping)
        and audit.get("schema_version") == RESULT_AUDIT_SCHEMA_VERSION
        and step.get("status") == "success"
    )


def _required_query_step_ids() -> frozenset[str]:
    definition = metric_anomaly_playbook_definition()
    return frozenset(
        str(step["id"])
        for step in definition["steps"]
        if step.get("kind") == "query"
    )


def _data_quality_status(reasons: list[str]) -> str:
    if "DATA_QUALITY_FAILED" in reasons:
        return "fail"
    return "unknown" if reasons else "pass"


def _operation_state(operation_id: str) -> dict[str, Any]:
    operations = load_operation_manifest(_PACKAGE_ROOT / "manifests" / "report.json")
    matches = [item for item in operations if item.operation_id == operation_id]
    if len(matches) != 1:
        return {
            "operation_id": operation_id,
            "contract_version": None,
            "contract_fingerprint": None,
            "completeness": "unknown",
            "pagination_evidence": "none",
        }
    operation = matches[0]
    return {
        "operation_id": operation.operation_id,
        "contract_version": operation.contract_version,
        "contract_fingerprint": contract_fingerprint(operation),
        "completeness": operation.pagination.completeness,
        "pagination_evidence": operation.pagination.pagination_evidence,
    }


def _validation_status(
    value: Mapping[str, Any],
    *,
    contract_digest: str,
    provider_fingerprint: str,
    required_completeness: str,
    required_data_quality: str,
    validation_ttl_seconds: int,
    now: datetime,
) -> tuple[str, list[str]]:
    shape = _validation_shape_status(value)
    if shape is not None:
        return shape
    identity = _validation_identity_status(
        value,
        contract_digest=contract_digest,
        provider_fingerprint=provider_fingerprint,
    )
    if identity is not None:
        return identity
    freshness = _validation_freshness_status(
        value,
        now=now,
        validation_ttl_seconds=validation_ttl_seconds,
    )
    if freshness is not None:
        return freshness
    return _validation_requirement_status(
        value,
        required_completeness=required_completeness,
        required_data_quality=required_data_quality,
    )


def _validation_shape_status(
    value: Mapping[str, Any],
) -> tuple[str, list[str]] | None:
    if set(value) == _VALIDATION_FIELDS and value.get("schema_version") == VALIDATION_SCHEMA_VERSION:
        return None
    return "quarantined", ["CAPABILITY_VALIDATION_INVALID"]


def _validation_identity_status(
    value: Mapping[str, Any],
    *,
    contract_digest: str,
    provider_fingerprint: str,
) -> tuple[str, list[str]] | None:
    matches = (
        value.get("selector") == "metric-anomaly-localization@1"
        and value.get("contract_digest") == contract_digest
        and value.get("provider_fingerprint") == provider_fingerprint
    )
    if matches:
        return None
    return "quarantined", ["CAPABILITY_FINGERPRINT_MISMATCH"]


def _validation_freshness_status(
    value: Mapping[str, Any], *, now: datetime, validation_ttl_seconds: int
) -> tuple[str, list[str]] | None:
    try:
        validated_at = _timestamp(value["validated_at"])
        expires_at = _timestamp(value["expires_at"])
    except (KeyError, ValueError):
        return "quarantined", ["CAPABILITY_VALIDATION_INVALID"]
    lifetime = expires_at - validated_at
    if lifetime <= timedelta(0) or lifetime > timedelta(
        seconds=validation_ttl_seconds
    ):
        return "quarantined", ["CAPABILITY_VALIDATION_INVALID"]
    current = now.astimezone(timezone.utc)
    if validated_at > current or expires_at <= current:
        return "unknown", ["CAPABILITY_VALIDATION_EXPIRED"]
    return None


def _validation_requirement_status(
    value: Mapping[str, Any],
    *,
    required_completeness: str,
    required_data_quality: str,
) -> tuple[str, list[str]]:
    reason_codes = value.get("reason_codes")
    if not isinstance(reason_codes, list) or any(
        not isinstance(item, str) or not item for item in reason_codes
    ):
        return "quarantined", ["CAPABILITY_VALIDATION_INVALID"]
    if value.get("trust_status") != "stable":
        selected = str(value.get("trust_status"))
        return (
            "quarantined" if selected == "quarantined" else "blocked",
            list(reason_codes or ["CAPABILITY_VALIDATION_BLOCKED"]),
        )
    if reason_codes:
        return "quarantined", ["CAPABILITY_VALIDATION_INVALID"]
    if value.get("completeness") != required_completeness:
        return "blocked", ["COMPLETENESS_INSUFFICIENT"]
    if value.get("data_quality") != required_data_quality:
        return "blocked", ["DATA_QUALITY_UNPROVEN"]
    return "stable", []


def _timestamp(value: Any) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("timestamp must use UTC Z form")
    parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    if parsed.tzinfo is None or parsed.isoformat().replace("+00:00", "Z") != value:
        raise ValueError("timestamp is not canonical")
    return parsed


__all__ = [
    "DATA_QUALITY_SCHEMA_VERSION",
    "TRUST_RESULT_SCHEMA_VERSION",
    "VALIDATION_SCHEMA_VERSION",
    "evaluate_playbook_data_quality",
    "evaluate_reference_trust",
]
