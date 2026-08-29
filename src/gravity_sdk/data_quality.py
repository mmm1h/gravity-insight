"""Reusable Data Quality Result construction and conservative aggregation."""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping, Sequence
from typing import Any

from .agent_runtime_contracts import AgentRuntimeContractError, validate_schema


SCHEMA_VERSION = "gravity.data-quality-result.v1"
_SCHEMA_NAME = "data-quality-result-v1.schema.json"
_STATUS_PRECEDENCE = ("fail", "warn", "unknown", "pass")
_REASON_CODE = re.compile(r"^[A-Z][A-Z0-9_]{1,127}$")


class DataQualityError(AgentRuntimeContractError):
    """A Data Quality Result is malformed."""


def data_quality_result(
    checks: Sequence[Mapping[str, Any]],
    *,
    reason_codes: Sequence[str] = (),
) -> dict[str, Any]:
    selected = [copy.deepcopy(dict(item)) for item in checks]
    reasons = _reason_codes(reason_codes)
    if not selected:
        status = "unknown"
        reasons = list(dict.fromkeys([*reasons, "DATA_QUALITY_UNPROVEN"]))
    else:
        status = _aggregate_status(
            [str(item.get("status", "unknown")) for item in selected]
        )
    result = {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "checks": selected,
        "reason_codes": reasons,
    }
    validate_data_quality_result(result)
    return result


def aggregate_data_quality(
    results: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    reasons: list[str] = []
    if not results:
        return data_quality_result(())
    for result in results:
        validate_data_quality_result(result)
        checks.extend(copy.deepcopy(result["checks"]))
        reasons.extend(str(code) for code in result["reason_codes"])
    return data_quality_result(checks, reason_codes=reasons)


def validate_data_quality_result(value: Mapping[str, Any]) -> None:
    try:
        validate_schema(value, _SCHEMA_NAME, "Data Quality Result")
    except AgentRuntimeContractError as exc:
        raise DataQualityError(str(exc)) from exc
    statuses = [str(item["status"]) for item in value["checks"]]
    expected = "unknown" if not statuses else _aggregate_status(statuses)
    if value["status"] != expected:
        raise DataQualityError("Data Quality Result status contradicts its checks")
    _reason_codes(value["reason_codes"])


def meets_data_quality(actual: str, required: str) -> bool:
    allowed = {
        "pass": frozenset({"pass"}),
        "warn": frozenset({"pass", "warn"}),
        "unknown": frozenset({"pass", "warn", "fail", "unknown"}),
    }
    return actual in allowed.get(required, frozenset())


def _aggregate_status(statuses: Sequence[str]) -> str:
    selected = set(statuses)
    if selected - set(_STATUS_PRECEDENCE):
        raise DataQualityError("Data Quality check status is invalid")
    return next(status for status in _STATUS_PRECEDENCE if status in selected)


def _reason_codes(values: Sequence[str]) -> list[str]:
    if isinstance(values, (str, bytes)) or any(
        not isinstance(value, str) or _REASON_CODE.fullmatch(value) is None
        for value in values
    ):
        raise DataQualityError("Data Quality reason codes are invalid")
    return list(dict.fromkeys(values))


__all__ = [
    "DataQualityError",
    "SCHEMA_VERSION",
    "aggregate_data_quality",
    "data_quality_result",
    "meets_data_quality",
    "validate_data_quality_result",
]
