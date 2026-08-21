"""Fail-closed evidence synthesis for metric-anomaly-localization@1."""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from typing import Any

from .analysis_playbook import RESULT_SCHEMA_VERSION
from .analysis_playbook_catalog import playbook_definition_fingerprint
from .errors import ContractChangedError, exit_code_for_error
from .result_audit import SCHEMA_VERSION as RESULT_AUDIT_SCHEMA_VERSION
from .reference_journey_operator import (
    ReferenceOperatorError,
    returned_dimension_change,
)
from .semantic_compose import SEMANTIC_COMPOSE_RESULT_SCHEMA_VERSION
from .semantic_compose_catalog import definition_by_id, definition_fingerprint


_QUERY_STEP_IDS = (
    "compare_current",
    "compare_reference",
    "validate_current",
    "validate_reference",
)
_METRIC_FIELD = "ap_cost"
_DIMENSION_FIELD = "click_company"


class _EvidenceError(RuntimeError):
    def __init__(self, step_id: str, reason: str) -> None:
        super().__init__(reason)
        self.step_id = step_id
        self.reason = reason


def build_metric_anomaly_result(
    definition: Mapping[str, Any],
    inputs: Mapping[str, Any],
    items: Mapping[str, Mapping[str, Any]],
    *,
    invalidated_steps: Sequence[str],
    reused_steps: Sequence[str],
    rerun_steps: Sequence[str],
) -> dict[str, Any]:
    """Use only complete, identity-matched facts; otherwise publish no claim."""

    execution = _execution(invalidated_steps, reused_steps, rerun_steps)
    blocked, evidence, evidence_error = _collect_evidence(definition, inputs, items)
    conclusion = None if blocked else _conclusion(evidence, inputs)
    claims = [] if conclusion is None else _scoped_claims(definition, evidence, inputs)
    steps = _public_steps(
        definition, inputs, items, reused_steps, evidence,
        conclusion=conclusion, blocked=blocked,
    )
    exit_code = _result_exit_code(items, evidence_error)
    return _result_envelope(
        definition, inputs, execution, steps, conclusion, claims, blocked, exit_code,
        network_called=bool(rerun_steps),
    )


def _result_envelope(
    definition: Mapping[str, Any], inputs: Mapping[str, Any],
    execution: Mapping[str, Any], steps: Sequence[Mapping[str, Any]],
    conclusion: Mapping[str, Any] | None, claims: Sequence[Mapping[str, Any]],
    blocked: Sequence[Mapping[str, Any]], exit_code: int, *, network_called: bool,
) -> dict[str, Any]:
    return {
        "schema_version": RESULT_SCHEMA_VERSION,
        "playbook": {
            "playbook_id": definition["playbook_id"],
            "version": definition["version"],
            "fingerprint": playbook_definition_fingerprint(definition),
            "goal": definition["goal"],
        },
        "ok": conclusion is not None,
        "status": "success" if conclusion is not None else "evidence_incomplete",
        "exit_code": exit_code,
        "network_called": network_called,
        "problem": inputs["question"],
        "hypothesis": copy.deepcopy(inputs["hypothesis"]),
        "scope": {
            "app": copy.deepcopy(inputs["app"]),
            "current_window": copy.deepcopy(inputs["current_window"]),
            "reference_window": copy.deepcopy(inputs["reference_window"]),
        },
        "execution": execution,
        "steps": steps,
        "conclusion": conclusion,
        "allowed_claims": claims,
        "stop": (
            {
                "triggered": False,
                "condition": None,
                "missing_steps": [],
                "next_action": None,
            }
            if conclusion is not None
            else {
                "triggered": True,
                "condition": "required_evidence_incomplete",
                "missing_steps": blocked,
                "next_action": "Correct or rerun only the listed step and its DAG descendants; do not form a final conclusion from the remaining steps.",
            }
        ),
    }


def _execution(
    invalidated: Sequence[str], reused: Sequence[str], rerun: Sequence[str],
) -> dict[str, Any]:
    return {
        "invalidated_steps": list(invalidated),
        "reused_steps": list(reused),
        "rerun_steps": list(rerun),
        "query_steps_executed": len(rerun),
        "query_steps_reused": sum(step_id in _QUERY_STEP_IDS for step_id in reused),
    }


def _collect_evidence(
    definition: Mapping[str, Any], inputs: Mapping[str, Any],
    items: Mapping[str, Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, "_StepEvidence"], _EvidenceError | None]:
    blocked = _blocked_steps(items)
    evidence: dict[str, _StepEvidence] = {}
    latest_error: _EvidenceError | None = None
    blocked_ids = {str(item["step_id"]) for item in blocked}
    for step_id in _QUERY_STEP_IDS:
        if step_id in blocked_ids:
            continue
        try:
            evidence[step_id] = _step_evidence(step_id, definition, inputs, items[step_id])
        except _EvidenceError as exc:
            latest_error = exc
            blocked.append(_evidence_failure(exc))
    if not blocked:
        try:
            _cross_check(evidence, inputs)
        except _EvidenceError as exc:
            latest_error = exc
            blocked.append(_evidence_failure(exc))
    return blocked, evidence, latest_error


def _evidence_failure(error: _EvidenceError) -> dict[str, Any]:
    return {
        "step_id": error.step_id, "status": "evidence_invalid",
        "code": "PLAYBOOK_EVIDENCE_INVALID", "reason": error.reason,
    }


def _result_exit_code(
    items: Mapping[str, Mapping[str, Any]], error: _EvidenceError | None,
) -> int:
    selected = max(
        (int(item.get("exit_code", 0)) for item in items.values() if type(item.get("exit_code")) is int),
        default=0,
    )
    if error is None:
        return selected
    return max(selected, exit_code_for_error(ContractChangedError(error.reason)))


class _StepEvidence:
    def __init__(
        self, step_id: str, rows: list[Mapping[str, Any]], app_id: int,
        audit: Mapping[str, Any], step_index: int,
    ) -> None:
        self.step_id = step_id
        self.rows = rows
        self.app_id = app_id
        self.audit = audit
        self.step_index = step_index

    @property
    def rows_path(self) -> str:
        return f"/steps/{self.step_index}/plan_item/result/result/query/data/list"


def _step_evidence(
    step_id: str, definition: Mapping[str, Any], inputs: Mapping[str, Any],
    item: Mapping[str, Any],
) -> _StepEvidence:
    semantic = _validated_semantic(step_id, definition, item)
    _validate_members(step_id, semantic.get("semantic_members"), definition, inputs)
    generated = _validated_generated_query(step_id, semantic, inputs)
    rows, audit = _fact_rows(step_id, semantic)
    index = next(index for index, step in enumerate(definition["steps"]) if step["id"] == step_id)
    evidence = _StepEvidence(step_id, rows, int(generated["app"]), audit, index)
    _validate_rows(evidence)
    return evidence


def _validated_semantic(
    step_id: str, definition: Mapping[str, Any], item: Mapping[str, Any],
) -> Mapping[str, Any]:
    semantic = item.get("result")
    if not isinstance(semantic, Mapping) or semantic.get("schema_version") != SEMANTIC_COMPOSE_RESULT_SCHEMA_VERSION:
        raise _EvidenceError(step_id, "semantic result schema is missing or changed")
    if semantic.get("ok") is not True or semantic.get("status") != "success":
        raise _EvidenceError(step_id, "semantic result is not complete success")
    semantic_ref = definition["semantic_definition"]
    registered = definition_by_id(str(semantic_ref["definition_id"]), int(semantic_ref["version"]))
    expected = {
        "definition_id": semantic_ref["definition_id"],
        "version": semantic_ref["version"],
        "fingerprint": definition_fingerprint(registered),
    }
    if semantic.get("definition") != expected:
        raise _EvidenceError(step_id, "semantic definition identity does not match the playbook")
    return semantic


def _validated_generated_query(
    step_id: str, semantic: Mapping[str, Any], inputs: Mapping[str, Any],
) -> Mapping[str, Any]:
    generated = semantic.get("generated_query")
    if not isinstance(generated, Mapping) or type(generated.get("app")) is not int:
        raise _EvidenceError(step_id, "generated query App identity is missing")
    query_inputs = generated.get("inputs")
    window = inputs["current_window"] if step_id.endswith("current") else inputs["reference_window"]
    expected_dates = [window["start"], window["end"]]
    if not isinstance(query_inputs, Mapping):
        raise _EvidenceError(step_id, "generated query inputs are missing")
    if query_inputs.get("date_list") != expected_dates or query_inputs.get("time_dims") != "total":
        raise _EvidenceError(step_id, "generated query window or grain changed")
    return generated


def _fact_rows(
    step_id: str, semantic: Mapping[str, Any],
) -> tuple[list[Mapping[str, Any]], Mapping[str, Any]]:
    result = semantic.get("result")
    query = result.get("query") if isinstance(result, Mapping) else None
    data = query.get("data") if isinstance(query, Mapping) else None
    rows = data.get("list") if isinstance(data, Mapping) else None
    if not isinstance(rows, list) or not rows or any(not isinstance(row, Mapping) for row in rows):
        raise _EvidenceError(step_id, "required fact rows are empty or malformed")
    audit = semantic.get("result_audit")
    if (
        not isinstance(audit, Mapping)
        or audit.get("schema_version") != RESULT_AUDIT_SCHEMA_VERSION
        or audit.get("fact_paths", {}).get("operation_id") != "/operation_id"
    ):
        raise _EvidenceError(step_id, "result_audit operation fact path is missing")
    if not isinstance(semantic.get("allowed_claims"), list) or not semantic["allowed_claims"]:
        raise _EvidenceError(step_id, "semantic result did not publish allowed claims")
    return [dict(row) for row in rows], dict(audit)


def _validate_members(
    step_id: str, value: Any, definition: Mapping[str, Any], inputs: Mapping[str, Any],
) -> None:
    if not isinstance(value, Mapping):
        raise _EvidenceError(step_id, "semantic member identities are missing")
    members = definition["members"]
    metric = value.get("metric")
    if not _member_matches(metric, members["metric"], _METRIC_FIELD):
        raise _EvidenceError(step_id, "semantic metric identity changed")
    _validate_group_members(step_id, value, members)
    _validate_member_filters(step_id, value.get("filters"), members, inputs)


def _validate_group_members(
    step_id: str, value: Mapping[str, Any], members: Mapping[str, Any],
) -> None:
    dimensions, joins = value.get("dimensions"), value.get("joins")
    if not isinstance(dimensions, list) or len(dimensions) != 1:
        raise _EvidenceError(step_id, "semantic dimension selection changed")
    if not _member_matches(dimensions[0], members["dimension"], _DIMENSION_FIELD):
        raise _EvidenceError(step_id, "semantic dimension identity changed")
    if not isinstance(joins, list) or len(joins) != 1:
        raise _EvidenceError(step_id, "semantic join selection changed")


def _validate_member_filters(
    step_id: str, filters: Any, members: Mapping[str, Any], inputs: Mapping[str, Any],
) -> None:
    if not isinstance(filters, list):
        raise _EvidenceError(step_id, "semantic filter selection changed")
    if step_id.startswith("validate_"):
        if (
            len(filters) != 1
            or not _member_matches(filters[0], members["filter"], _DIMENSION_FIELD)
            or filters[0].get("operator") != "IN"
            or filters[0].get("values") != inputs["hypothesis"]["values"]
        ):
            raise _EvidenceError(step_id, "semantic hypothesis filter changed")
    elif filters:
        raise _EvidenceError(step_id, "an unrequested semantic filter appeared")


def _member_matches(value: Any, reference: Mapping[str, Any], physical: str) -> bool:
    return (
        isinstance(value, Mapping)
        and value.get("definition_id") == reference["definition_id"]
        and value.get("version") == reference["version"]
        and value.get("physical_name") == physical
    )


def _validate_rows(evidence: _StepEvidence) -> None:
    seen: set[str] = set()
    for row in evidence.rows:
        _decimal(row.get(_METRIC_FIELD), evidence.step_id)
        key = row.get(_DIMENSION_FIELD)
        if not isinstance(key, str) or not key or key in seen:
            raise _EvidenceError(evidence.step_id, "dimension keys are missing or duplicated")
        seen.add(key)


def _cross_check(evidence: Mapping[str, _StepEvidence], inputs: Mapping[str, Any]) -> None:
    app_ids = {item.app_id for item in evidence.values()}
    if len(app_ids) != 1:
        raise _EvidenceError("conclusion", "query steps do not share one App identity")
    selected = str(inputs["hypothesis"]["values"][0])
    for period in ("current", "reference"):
        breakdown = _groups(evidence[f"compare_{period}"])
        validation = evidence[f"validate_{period}"]
        if len(validation.rows) != 1 or validation.rows[0].get(_DIMENSION_FIELD) != selected:
            raise _EvidenceError(validation.step_id, "selected hypothesis row is absent or ambiguous")
        if selected not in breakdown:
            raise _EvidenceError(f"compare_{period}", "selected hypothesis key is absent from the returned breakdown")
        if _decimal(validation.rows[0][_METRIC_FIELD], validation.step_id) != breakdown[selected]:
            raise _EvidenceError(validation.step_id, "filtered value does not match the same breakdown key")


def _conclusion(
    evidence: Mapping[str, _StepEvidence], inputs: Mapping[str, Any],
) -> dict[str, Any]:
    current = evidence["compare_current"]
    reference = evidence["compare_reference"]
    selected_current = evidence["validate_current"]
    selected_reference = evidence["validate_reference"]
    try:
        operator_result = returned_dimension_change(
            current_rows=current.rows,
            reference_rows=reference.rows,
            selected_key=str(inputs["hypothesis"]["values"][0]),
            selected_current=selected_current.rows[0][_METRIC_FIELD],
            selected_reference=selected_reference.rows[0][_METRIC_FIELD],
            current_rows_path=current.rows_path,
            reference_rows_path=reference.rows_path,
            selected_current_path=_fact(
                selected_current, 0, _METRIC_FIELD
            )["path"],
            selected_reference_path=_fact(
                selected_reference, 0, _METRIC_FIELD
            )["path"],
        )
        return {
            **operator_result,
            "schema_version": "gravity.metric-anomaly-conclusion.v1",
        }
    except ReferenceOperatorError as exc:
        raise _EvidenceError("conclusion", str(exc)) from exc


def _public_steps(
    definition: Mapping[str, Any], inputs: Mapping[str, Any],
    items: Mapping[str, Mapping[str, Any]], reused: Sequence[str],
    evidence: Mapping[str, _StepEvidence], *, conclusion: Mapping[str, Any] | None,
    blocked: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for index, step in enumerate(definition["steps"]):
        step_id = str(step["id"])
        base = {
            "id": step_id,
            "kind": step["kind"],
            "product": step["product"],
            "contract": step["contract"],
            "depends_on": list(step["depends_on"]),
        }
        if step["kind"] == "query":
            item = copy.deepcopy(items.get(step_id))
            status = str(item.get("status", "missing")) if isinstance(item, Mapping) else "missing"
            fact_paths = {
                "rows": f"/steps/{index}/plan_item/result/result/query/data/list",
                "operation_id": f"/steps/{index}/plan_item/result/operation_id",
                "result_audit": f"/steps/{index}/plan_item/result/result_audit",
            }
            result.append({
                **base,
                "status": status,
                "execution": "reused" if step_id in reused else "executed",
                "fact_paths": fact_paths,
                "result_audit": copy.deepcopy(evidence[step_id].audit) if step_id in evidence else None,
                "plan_item": item,
            })
        elif step_id == "hypothesis":
            result.append({
                **base, "status": "success",
                "execution": "reused" if step_id in reused else "local",
                "fact_paths": {}, "result": copy.deepcopy(inputs["hypothesis"]),
            })
        elif step_id.startswith("breakdown_"):
            source_id = step_id.replace("breakdown_", "compare_")
            source = evidence.get(source_id)
            result.append({
                **base,
                "status": "success" if source is not None else "blocked",
                "execution": "reused" if step_id in reused else "local",
                "fact_paths": ({"rows": source.rows_path} if source is not None else {}),
                "result": (
                    {
                        "returned_rows": copy.deepcopy(source.rows),
                        "returned_sum": _render_decimal(sum(_groups(source).values(), Decimal(0))),
                    }
                    if source is not None else None
                ),
            })
        else:
            result.append({
                **base,
                "status": "success" if conclusion is not None else "blocked",
                "execution": "local",
                "fact_paths": {},
                "result": copy.deepcopy(conclusion),
                "blocked_by": [str(item["step_id"]) for item in blocked],
            })
    return result


def _blocked_steps(items: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for step_id in _QUERY_STEP_IDS:
        item = items.get(step_id)
        if isinstance(item, Mapping) and item.get("ok") is True and item.get("status") == "success":
            continue
        error = item.get("error") if isinstance(item, Mapping) else None
        result.append({
            "step_id": step_id,
            "status": str(item.get("status", "missing")) if isinstance(item, Mapping) else "missing",
            "code": error.get("code") if isinstance(error, Mapping) else "PLAYBOOK_STEP_INCOMPLETE",
        })
    return result


def _groups(evidence: _StepEvidence) -> dict[str, Decimal]:
    return {
        str(row[_DIMENSION_FIELD]): _decimal(row[_METRIC_FIELD], evidence.step_id)
        for row in evidence.rows
    }


def _decimal(value: Any, step_id: str) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise _EvidenceError(step_id, "metric value is missing or non-numeric")
    try:
        selected = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise _EvidenceError(step_id, "metric value is missing or non-numeric") from None
    if not selected.is_finite():
        raise _EvidenceError(step_id, "metric value is not finite")
    return selected


def _render_decimal(value: Decimal) -> str:
    rendered = format(value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered or "0"


def _fact(evidence: _StepEvidence, row: int, field: str) -> dict[str, str]:
    return {
        "step_id": evidence.step_id,
        "path": f"{evidence.rows_path}/{row}/{field}",
    }


def _all_metric_facts(evidence: _StepEvidence) -> list[dict[str, str]]:
    return [_fact(evidence, index, _METRIC_FIELD) for index in range(len(evidence.rows))]


def _scoped_claims(
    definition: Mapping[str, Any], evidence: Mapping[str, _StepEvidence],
    inputs: Mapping[str, Any],
) -> list[dict[str, Any]]:
    app_id = evidence["compare_current"].app_id
    scope = {
        "app_id": app_id,
        "metric": definition["members"]["metric"],
        "dimension": definition["members"]["dimension"],
        "current_window": copy.deepcopy(inputs["current_window"]),
        "reference_window": copy.deepcopy(inputs["reference_window"]),
        "hypothesis_values": list(inputs["hypothesis"]["values"]),
    }
    return [{**copy.deepcopy(claim), "scope": copy.deepcopy(scope)} for claim in definition["allowed_claims"]]


__all__ = ["build_metric_anomaly_result"]
