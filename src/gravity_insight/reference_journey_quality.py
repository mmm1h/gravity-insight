"""R01 playbook-specific checks projected into the reusable DQ contract."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .analysis_playbook_catalog import metric_anomaly_playbook_definition
from .data_quality import data_quality_result
from .result_audit import SCHEMA_VERSION as RESULT_AUDIT_SCHEMA_VERSION


def evaluate_playbook_data_quality(
    result: Mapping[str, Any], *, completeness: str
) -> dict[str, Any]:
    """Check R01 facts without inferring missing Product completeness."""

    playbook_ok = _playbook_result_is_valid(result)
    audits_ok = _query_audits_are_valid(
        result, required_ids=_required_query_step_ids()
    )
    complete = completeness == "complete"
    checks = [
        {
            "check_id": "playbook-result",
            "status": "pass" if playbook_ok else "fail",
            "scope": "metric-anomaly-localization@1",
        },
        {
            "check_id": "query-result-audit",
            "status": "pass" if audits_ok else "fail",
            "scope": "metric-anomaly-localization@1",
        },
        {
            "check_id": "completeness",
            "status": "pass" if complete else "unknown",
            "scope": "metric-anomaly-localization@1",
        },
    ]
    reasons: list[str] = []
    if not playbook_ok or not audits_ok:
        reasons.append("DATA_QUALITY_FAILED")
    if not complete:
        reasons.append("DATA_QUALITY_UNPROVEN")
    return data_quality_result(checks, reason_codes=reasons)


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
        not isinstance(step_id, str) or not step_id for step_id in selected_ids
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


__all__ = ["evaluate_playbook_data_quality"]
