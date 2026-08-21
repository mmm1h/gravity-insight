"""Offline Model Artifact registry and production-claim readiness evaluation."""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Any, Callable

from .actionable_error_values import actual_value
from .errors import ErrorCategory, InputValidationError, exit_code_for_category
from .model_contract import (
    ModelContractError,
    compile_model_artifact,
    load_model_artifact,
)
from .operator_registry import OperatorRegistry


_URI = re.compile(r"^model://[a-z0-9.-]+/[a-z0-9./-]+@[1-9][0-9]*$")
_LOCAL_EXIT = exit_code_for_category(ErrorCategory.LOCAL)


class ModelRegistry:
    """Validate Model lifecycle facts without fitting, loading, or predicting."""

    def __init__(
        self,
        artifacts: Sequence[Mapping[str, Any] | str | Path] = (),
        *,
        operators: OperatorRegistry | None = None,
        trusted_artifact_digests: Sequence[str] = (),
        today: Callable[[], date] = date.today,
    ) -> None:
        compiled = [
            compile_model_artifact(item)
            if isinstance(item, Mapping)
            else load_model_artifact(item)
            for item in artifacts
        ]
        uris = [item["contract"]["uri"] for item in compiled]
        if len(uris) != len(set(uris)):
            raise ModelContractError(
                "MODEL_IDENTITY_CONFLICT", "Model URI is duplicated"
            )
        aliases = [item["contract"]["alias"] for item in compiled]
        if len(aliases) != len(set(aliases)):
            raise ModelContractError(
                "MODEL_ALIAS_CONFLICT", "Model alias is duplicated"
            )
        self._artifacts = {item["contract"]["uri"]: item for item in compiled}
        self._operators = operators or OperatorRegistry()
        self._trusted_artifact_digests = frozenset(trusted_artifact_digests)
        self._today = today

    def list(self) -> dict[str, Any]:
        models = [
            _summary(self._artifacts[uri]) for uri in sorted(self._artifacts)
        ]
        return {
            "schema_version": "gravity.model-list.v1",
            "status": "success",
            "count": len(models),
            "models": models,
            "network_called": False,
        }

    def describe(self, uri: str) -> dict[str, Any]:
        selected = _model_uri(uri)
        artifact = self._artifacts.get(selected)
        if artifact is None:
            return _gap(
                "gravity.model-description.v1",
                selected,
                ["MODEL_UNVALIDATED"],
            )
        return {
            "schema_version": "gravity.model-description.v1",
            "status": "success",
            "ok": True,
            "model": _public_artifact(artifact),
            "network_called": False,
        }

    def validate(self, value: Mapping[str, Any]) -> dict[str, Any]:
        try:
            artifact = compile_model_artifact(value)
        except ModelContractError as exc:
            return _validation_failure(exc.reason_code)
        return {
            "schema_version": "gravity.model-validation.v1",
            "status": "valid",
            "ok": True,
            "model": _reference(artifact),
            "reason_codes": [],
            "network_called": False,
        }

    def evaluate(
        self,
        uri: str,
        *,
        at: str | None = None,
        horizon_days: int | None = None,
        unit: str | None = None,
    ) -> dict[str, Any]:
        selected = _model_uri(uri)
        artifact = self._artifacts.get(selected)
        if artifact is None:
            return _gap(
                "gravity.model-evaluation.v1",
                selected,
                ["MODEL_UNVALIDATED"],
            )
        evaluation_date = _evaluation_date(at, self._today)
        reasons = _readiness_reasons(
            artifact,
            operators=self._operators,
            at=evaluation_date,
            horizon_days=horizon_days,
            unit=unit,
            source_trusted=artifact["digest"] in self._trusted_artifact_digests,
        )
        contract = artifact["contract"]
        approved = not reasons
        return {
            "schema_version": "gravity.model-evaluation.v1",
            "status": "approved" if approved else "blocked",
            "ok": approved,
            **({"exit_code": _LOCAL_EXIT} if not approved else {}),
            "uri": selected,
            "model": _reference(artifact),
            "evaluated_for": {
                "at": evaluation_date.isoformat(),
                "horizon_days": horizon_days,
                "unit": unit,
            },
            "production_claims_allowed": approved,
            "allowed_claims": copy.deepcopy(
                contract["claim_policy"]["validated" if approved else "scenario"]
            ),
            "forbidden_claims": copy.deepcopy(contract["claim_policy"]["forbidden"]),
            "reason_codes": reasons,
            "network_called": False,
        }

    def dependencies(self, uris: Sequence[str]) -> dict[str, Any]:
        if isinstance(uris, (str, bytes)):
            raise InputValidationError(
                "actual value: string; Model dependencies must be an array of URIs",
                field="model_dependencies",
                next_action="Pass the Journey required_models array unchanged.",
            )
        results = [self.evaluate(uri) for uri in uris]
        reasons = [
            reason for result in results for reason in result.get("reason_codes", [])
        ]
        return {
            "schema_version": "gravity.model-dependencies.v1",
            "status": "resolved" if not reasons else "blocked",
            "ok": not reasons,
            "dependencies": results,
            "reason_codes": list(dict.fromkeys(reasons)),
            "network_called": False,
        }


def _readiness_reasons(
    artifact: Mapping[str, Any],
    *,
    operators: OperatorRegistry,
    at: date,
    horizon_days: int | None,
    unit: str | None,
    source_trusted: bool,
) -> list[str]:
    contract = artifact["contract"]
    reasons = _model_state_reasons(contract, at)
    if not source_trusted:
        reasons.append("MODEL_SOURCE_UNTRUSTED")
    operator = operators.resolve(contract["operator_uri"])
    if not operator["ok"]:
        reasons.append("MODEL_OPERATOR_UNAVAILABLE")
    reasons.extend(_evaluation_reasons(contract["evaluation"], at))
    reasons.extend(_scope_reasons(contract, horizon_days=horizon_days, unit=unit))
    return list(dict.fromkeys(reasons))


def _model_state_reasons(contract: Mapping[str, Any], at: date) -> list[str]:
    if contract["lifecycle"] == "revoked" or contract["approval"]["status"] == "revoked":
        return ["MODEL_REVOKED"]
    if contract["approval"]["status"] != "approved":
        return ["MODEL_UNAPPROVED"]
    if date.fromisoformat(contract["approval"]["approved_at"]) > at:
        return ["MODEL_NOT_YET_APPROVED"]
    return []


def _evaluation_reasons(evaluation: Mapping[str, Any], at: date) -> list[str]:
    if evaluation["status"] != "validated":
        return ["MODEL_UNVALIDATED"]
    if date.fromisoformat(evaluation["evaluated_at"]) > at:
        return ["MODEL_NOT_YET_VALIDATED"]
    if date.fromisoformat(evaluation["expires_at"]) < at:
        return ["MODEL_EXPIRED"]
    return []


def _scope_reasons(
    contract: Mapping[str, Any], *, horizon_days: int | None, unit: str | None
) -> list[str]:
    reasons: list[str] = []
    if horizon_days is not None:
        if type(horizon_days) is not int or horizon_days < 1:
            reasons.append("MODEL_HORIZON_INVALID")
        elif horizon_days > contract["safe_domain"]["horizon_days"]:
            reasons.append("MODEL_HORIZON_UNSAFE")
    if unit is not None and unit not in contract["safe_domain"]["units"]:
        reasons.append("MODEL_UNIT_UNSUPPORTED")
    if contract["lineage"]["sample_count"] < contract["safe_domain"]["minimum_samples"]:
        reasons.append("MODEL_SAMPLE_INSUFFICIENT")
    return reasons


def _evaluation_date(value: str | None, today: Callable[[], date]) -> date:
    if value is None:
        return today()
    try:
        selected = date.fromisoformat(value)
    except (TypeError, ValueError):
        selected = None
    if selected is None or selected.isoformat() != value:
        raise InputValidationError(
            f"actual value: {actual_value(value)}; at must be canonical YYYY-MM-DD",
            field="at",
            next_action="Retry `gravity models evaluate` with --at YYYY-MM-DD.",
        )
    return selected


def _summary(artifact: Mapping[str, Any]) -> dict[str, Any]:
    contract = artifact["contract"]
    return {
        "uri": contract["uri"],
        "version": contract["version"],
        "alias": contract["alias"],
        "owner": contract["owner"],
        "lifecycle": contract["lifecycle"],
        "operator_uri": contract["operator_uri"],
        "approval_status": contract["approval"]["status"],
        "evaluation_status": contract["evaluation"]["status"],
        "digest": artifact["digest"],
    }


def _reference(artifact: Mapping[str, Any]) -> dict[str, Any]:
    return {
        **_summary(artifact),
        "artifact_digest": artifact["contract"]["artifact"]["digest"],
        "lineage_digest": artifact["lineage_digest"],
        "evaluation_digest": artifact["evaluation_digest"],
        "safe_horizon_days": artifact["contract"]["safe_domain"]["horizon_days"],
    }


def _public_artifact(artifact: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "contract": copy.deepcopy(artifact["contract"]),
        "digest": artifact["digest"],
        "lineage_digest": artifact["lineage_digest"],
        "evaluation_digest": artifact["evaluation_digest"],
    }


def _validation_failure(reason: str) -> dict[str, Any]:
    return {
        "schema_version": "gravity.model-validation.v1",
        "status": "invalid",
        "ok": False,
        "exit_code": _LOCAL_EXIT,
        "model": None,
        "reason_codes": [reason],
        "network_called": False,
    }


def _gap(schema_version: str, uri: str, reasons: Sequence[str]) -> dict[str, Any]:
    return {
        "schema_version": schema_version,
        "status": "missing",
        "ok": False,
        "exit_code": _LOCAL_EXIT,
        "uri": uri,
        "model": None,
        "production_claims_allowed": False,
        "allowed_claims": [],
        "reason_codes": list(dict.fromkeys(reasons)),
        "network_called": False,
    }


def _model_uri(value: Any) -> str:
    if not isinstance(value, str) or _URI.fullmatch(value.strip()) is None:
        raise InputValidationError(
            f"actual value: {actual_value(value)}; uri must be an exact versioned Model URI",
            field="uri",
            next_action="Run `gravity models list` and use an exact uri.",
        )
    return value.strip()


__all__ = ["ModelRegistry"]
