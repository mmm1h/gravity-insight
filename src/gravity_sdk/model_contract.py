"""Model Artifact identity, lineage, evaluation, approval, and expiry contract."""

from __future__ import annotations

import copy
import json
import re
from datetime import date
from pathlib import Path
from typing import Any, Mapping

from .agent_runtime_contracts import (
    AgentRuntimeContractError,
    canonical_digest,
    load_json_object,
    validate_schema,
)


SCHEMA_VERSION = "gravity.model-artifact.v1"
_SCHEMA_NAME = "model-artifact-v1.schema.json"
_URI = re.compile(
    r"^model://[a-z0-9.-]+/[a-z0-9./-]+@(?P<version>[1-9][0-9]*)$"
)


class ModelContractError(AgentRuntimeContractError):
    """A Model Artifact is structurally invalid or internally contradictory."""

    def __init__(self, reason_code: str, message: str) -> None:
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {message}")


def compile_model_artifact(value: Mapping[str, Any]) -> dict[str, Any]:
    contract = _object(value)
    try:
        validate_schema(contract, _SCHEMA_NAME, "Model Artifact")
    except AgentRuntimeContractError as exc:
        raise ModelContractError("MODEL_CONTRACT_INVALID", str(exc)) from exc
    match = _URI.fullmatch(str(contract["uri"]))
    if match is None or int(match.group("version")) != contract["version"]:
        raise ModelContractError(
            "MODEL_IDENTITY_INVALID", "Model URI and version disagree"
        )
    fitting_start, fitting_end = _range(contract["lineage"]["fitting_window"])
    _validate_evaluation(contract, fitting_end)
    _validate_approval(contract["approval"], contract["evaluation"]["evaluated_at"])
    _validate_claims(contract["claim_policy"])
    try:
        json.dumps(contract, ensure_ascii=False, sort_keys=True, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ModelContractError(
            "MODEL_CONTRACT_INVALID", "Model Artifact must be canonical JSON"
        ) from exc
    lineage_digest = canonical_digest(contract["lineage"])
    evaluation_digest = canonical_digest(contract["evaluation"])
    return {
        "contract": contract,
        "digest": canonical_digest(contract),
        "lineage_digest": lineage_digest,
        "evaluation_digest": evaluation_digest,
        "fitting_window": {
            "start": fitting_start.isoformat(),
            "end": fitting_end.isoformat(),
        },
    }


def load_model_artifact(path: str | Path) -> dict[str, Any]:
    selected = Path(path)
    if selected.suffix.casefold() != ".json":
        raise ModelContractError(
            "MODEL_CONTRACT_INVALID", "Model Artifact source must be JSON"
        )
    return compile_model_artifact(load_json_object(selected, "Model Artifact"))


def _validate_evaluation(contract: Mapping[str, Any], fitting_end: date) -> None:
    evaluation = contract["evaluation"]
    evaluated = _optional_date(evaluation["evaluated_at"])
    expires = _optional_date(evaluation["expires_at"])
    _validate_evaluation_dates(evaluated, expires, fitting_end)
    status = evaluation["status"]
    if status == "validated":
        _validate_passed_evaluation(evaluation, evaluated, expires)
    elif status == "failed":
        _validate_failed_evaluation(evaluation, evaluated, expires)
    elif evaluated is not None or expires is not None or evaluation["metrics"]:
        raise ModelContractError(
            "MODEL_EVALUATION_INVALID",
            "unvalidated Model must not carry evaluation facts",
        )


def _validate_evaluation_dates(
    evaluated: date | None, expires: date | None, fitting_end: date
) -> None:
    if evaluated is not None and evaluated < fitting_end:
        raise ModelContractError(
            "MODEL_LINEAGE_INVALID", "evaluation predates the fitting window"
        )
    if evaluated is not None and expires is not None and expires < evaluated:
        raise ModelContractError(
            "MODEL_EVALUATION_INVALID", "evaluation expiry predates evaluation"
        )


def _validate_passed_evaluation(
    evaluation: Mapping[str, Any], evaluated: date | None, expires: date | None
) -> None:
    if evaluated is None or expires is None or not evaluation["metrics"]:
        raise ModelContractError(
            "MODEL_EVALUATION_INVALID",
            "validated Model requires dates and calibration metrics",
        )
    if any(not metric["passed"] for metric in evaluation["metrics"]):
        raise ModelContractError(
            "MODEL_EVALUATION_INVALID",
            "validated Model contains a failed calibration metric",
        )


def _validate_failed_evaluation(
    evaluation: Mapping[str, Any], evaluated: date | None, expires: date | None
) -> None:
    if (
        evaluated is None
        or expires is not None
        or not evaluation["metrics"]
        or all(metric["passed"] for metric in evaluation["metrics"])
    ):
        raise ModelContractError(
            "MODEL_EVALUATION_INVALID",
            "failed Model requires a dated failed calibration metric",
        )


def _validate_approval(approval: Mapping[str, Any], evaluated_at: Any) -> None:
    approved = approval["status"] == "approved"
    has_identity = bool(approval["approved_by"]) and approval["approved_at"] is not None
    if approved != has_identity:
        raise ModelContractError(
            "MODEL_APPROVAL_INVALID", "Model approval identity is inconsistent"
        )
    if approval["approved_at"] is not None:
        approved_at = _day(approval["approved_at"], "approved_at")
        if evaluated_at is not None and approved_at < _day(
            evaluated_at, "evaluated_at"
        ):
            raise ModelContractError(
                "MODEL_APPROVAL_INVALID", "Model approval predates evaluation"
            )


def _validate_claims(policy: Mapping[str, Any]) -> None:
    sets = [set(policy[name]) for name in ("validated", "scenario", "forbidden")]
    if any(sets[left] & sets[right] for left, right in ((0, 1), (0, 2), (1, 2))):
        raise ModelContractError(
            "MODEL_CLAIM_CONFLICT", "Model claim classes must be disjoint"
        )


def _range(value: Mapping[str, Any]) -> tuple[date, date]:
    start = _day(value["start"], "fitting_window.start")
    end = _day(value["end"], "fitting_window.end")
    if start > end:
        raise ModelContractError(
            "MODEL_LINEAGE_INVALID", "Model fitting window is reversed"
        )
    return start, end


def _optional_date(value: Any) -> date | None:
    return None if value is None else _day(value, "evaluation date")


def _day(value: Any, label: str) -> date:
    try:
        selected = date.fromisoformat(value)
    except (TypeError, ValueError):
        selected = None
    if selected is None or selected.isoformat() != value:
        raise ModelContractError(
            "MODEL_CONTRACT_INVALID", f"{label} must be canonical YYYY-MM-DD"
        )
    return selected


def _object(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ModelContractError(
            "MODEL_CONTRACT_INVALID", "Model Artifact must be an object"
        )
    return copy.deepcopy(dict(value))


__all__ = [
    "ModelContractError",
    "SCHEMA_VERSION",
    "compile_model_artifact",
    "load_model_artifact",
]
