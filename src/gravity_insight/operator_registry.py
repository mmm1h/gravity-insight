"""Closed offline registry for explicitly installed deterministic Operators."""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

from .actionable_error_values import actual_value
from .errors import ErrorCategory, InputValidationError, exit_code_for_category
from .operator_contract import (
    OperatorContractError,
    builtin_operator_artifacts,
    canonical_json_size,
    compile_operator_contract,
    validate_operator_input,
    validate_operator_output,
)
from .operator_ids import RETURNED_DIMENSION_CHANGE_URI
from .operator_returned_dimension_change import (
    OperatorMethodError,
    returned_dimension_change,
)


_URI = re.compile(
    r"^operator://[a-z0-9.-]+/[a-z0-9./-]+@[1-9][0-9]*$"
)
_LOCAL_EXIT = exit_code_for_category(ErrorCategory.LOCAL)
_RUNNERS: dict[str, Callable[..., dict[str, Any]]] = {
    RETURNED_DIMENSION_CHANGE_URI: returned_dimension_change,
}


class OperatorRegistry:
    """Resolve and execute only Runtime-owned, statically mapped Operators."""

    def __init__(self) -> None:
        artifacts = builtin_operator_artifacts()
        self._artifacts = {
            artifact["contract"]["uri"]: artifact for artifact in artifacts
        }
        if set(self._artifacts) != set(_RUNNERS):
            raise OperatorContractError(
                "OPERATOR_IMPLEMENTATION_UNAVAILABLE",
                "Operator contracts and static Runtime runners disagree",
            )
        self._verify_golden_cases()

    def list(self) -> dict[str, Any]:
        operators = [
            _summary(self._artifacts[uri]) for uri in sorted(self._artifacts)
        ]
        return {
            "schema_version": "gravity.operator-list.v1",
            "status": "success",
            "count": len(operators),
            "operators": operators,
            "network_called": False,
        }

    def describe(self, uri: str) -> dict[str, Any]:
        selected = _operator_uri(uri)
        artifact = self._artifacts.get(selected)
        if artifact is None:
            return _gap(
                "gravity.operator-description.v1",
                selected,
                "missing",
                "OPERATOR_UNAVAILABLE",
            )
        return {
            "schema_version": "gravity.operator-description.v1",
            "status": "success",
            "ok": True,
            "operator": _public_artifact(artifact),
            "network_called": False,
        }

    def resolve(self, uri: str) -> dict[str, Any]:
        selected = _operator_uri(uri)
        artifact = self._artifacts.get(selected)
        if artifact is None:
            return _gap(
                "gravity.operator-resolution.v1",
                selected,
                "missing",
                "OPERATOR_UNAVAILABLE",
            )
        lifecycle = artifact["contract"]["lifecycle"]
        if lifecycle == "revoked":
            return _gap(
                "gravity.operator-resolution.v1",
                selected,
                "revoked",
                "OPERATOR_REVOKED",
            )
        warnings = ["OPERATOR_DEPRECATED"] if lifecycle == "deprecated" else []
        return {
            "schema_version": "gravity.operator-resolution.v1",
            "status": "available",
            "ok": True,
            "operator": _reference(artifact),
            "warnings": warnings,
            "reason_codes": [],
            "network_called": False,
        }

    def validate(self, value: Mapping[str, Any]) -> dict[str, Any]:
        try:
            artifact = compile_operator_contract(value)
            if artifact["contract"]["uri"] not in _RUNNERS:
                raise OperatorContractError(
                    "OPERATOR_IMPLEMENTATION_UNAVAILABLE",
                    "Runtime has no statically approved runner for this contract",
                )
        except OperatorContractError as exc:
            return _validation_failure(exc.reason_code)
        return {
            "schema_version": "gravity.operator-validation.v1",
            "status": "valid",
            "ok": True,
            "operator": _reference(artifact),
            "reason_codes": [],
            "network_called": False,
        }

    def dependencies(self, uris: Sequence[str]) -> dict[str, Any]:
        if isinstance(uris, (str, bytes)):
            raise InputValidationError(
                "actual value: string; Operator dependencies must be an array of URIs",
                field="operator_dependencies",
                next_action="Pass the Journey required_operators array unchanged.",
            )
        results = [self.resolve(uri) for uri in uris]
        reasons = [
            reason for result in results for reason in result.get("reason_codes", [])
        ]
        return {
            "schema_version": "gravity.operator-dependencies.v1",
            "status": "resolved" if not reasons else "blocked",
            "ok": not reasons,
            "dependencies": results,
            "reason_codes": list(dict.fromkeys(reasons)),
            "network_called": False,
        }

    def execute(self, uri: str, inputs: Mapping[str, Any]) -> dict[str, Any]:
        selected = _operator_uri(uri)
        resolution = self.resolve(selected)
        if not resolution["ok"]:
            return _execution_failure(
                selected,
                resolution["status"],
                resolution["reason_codes"],
                operator=resolution.get("operator"),
            )
        artifact = self._artifacts[selected]
        return self._execute_artifact(artifact, inputs)

    def artifact(self, uri: str) -> dict[str, Any] | None:
        selected = _operator_uri(uri)
        artifact = self._artifacts.get(selected)
        return copy.deepcopy(artifact) if artifact is not None else None

    def _execute_artifact(
        self, artifact: Mapping[str, Any], inputs: Mapping[str, Any]
    ) -> dict[str, Any]:
        uri = artifact["contract"]["uri"]
        try:
            normalized = validate_operator_input(artifact, inputs)
            _validate_safe_domain(artifact["contract"], normalized)
            method_inputs = {
                key: copy.deepcopy(value)
                for key, value in normalized.items()
                if key not in {"units", "additivity"}
            }
            result = _RUNNERS[uri](**method_inputs)
            selected = validate_operator_output(artifact, result)
            _validate_output_budget(artifact["contract"], selected)
        except (OperatorContractError, OperatorMethodError) as exc:
            return _execution_failure(
                uri,
                "invalid",
                [exc.reason_code],
                operator=_reference(artifact),
            )
        return {
            "schema_version": "gravity.operator-execution.v1",
            "status": "success",
            "ok": True,
            "operator": _reference(artifact),
            "result": selected,
            "reason_codes": [],
            "network_called": False,
        }

    def _verify_golden_cases(self) -> None:
        for artifact in self._artifacts.values():
            for case in artifact["golden"]["cases"]:
                result = self._execute_artifact(artifact, case["input"])
                if not result["ok"] or result["result"] != case["expected"]:
                    raise OperatorContractError(
                        "OPERATOR_GOLDEN_MISMATCH",
                        f"Operator golden case {case['case_id']} changed",
                    )


def _validate_safe_domain(
    contract: Mapping[str, Any], inputs: Mapping[str, Any]
) -> None:
    domain = contract["safe_domain"]
    if canonical_json_size(inputs, reason_code="OPERATOR_INPUT_INVALID") > domain[
        "max_input_bytes"
    ]:
        raise OperatorContractError(
            "OPERATOR_RESOURCE_LIMIT", "Operator input exceeds its byte budget"
        )
    for name in ("current_rows", "reference_rows"):
        if len(inputs[name]) < contract["requirements"]["minimum_rows_per_window"]:
            raise OperatorContractError(
                "OPERATOR_SAMPLE_INSUFFICIENT",
                "Operator rows do not meet the minimum sample requirement",
            )
        if len(inputs[name]) > domain["max_rows_per_window"]:
            raise OperatorContractError(
                "OPERATOR_RESOURCE_LIMIT", "Operator rows exceed the safe domain"
            )
    units = inputs["units"]
    if len({units["current"], units["reference"], units["output"]}) != 1:
        raise OperatorContractError(
            "OPERATOR_UNIT_MISMATCH", "Operator input units disagree"
        )
    if inputs["additivity"] not in contract["unit_policy"]["allowed_additivity"]:
        raise OperatorContractError(
            "OPERATOR_ADDITIVITY_UNSUPPORTED",
            "Operator additivity is outside the safe domain",
        )
    _validate_row_values(inputs, domain)


def _validate_row_values(
    inputs: Mapping[str, Any], domain: Mapping[str, Any]
) -> None:
    dimension = inputs.get("dimension", "click_company")
    metric = inputs.get("metric", "ap_cost")
    for row in [*inputs["current_rows"], *inputs["reference_rows"]]:
        key = row.get(dimension)
        if isinstance(key, str) and len(key.encode("utf-8")) > domain[
            "max_dimension_key_bytes"
        ]:
            raise OperatorContractError(
                "OPERATOR_RESOURCE_LIMIT", "Operator dimension key is too large"
            )
        _validate_decimal_digits(row.get(metric), domain["max_decimal_digits"])
    _validate_decimal_digits(inputs["selected_current"], domain["max_decimal_digits"])
    _validate_decimal_digits(inputs["selected_reference"], domain["max_decimal_digits"])


def _validate_decimal_digits(value: Any, maximum: int) -> None:
    if isinstance(value, bool) or value is None:
        return
    try:
        selected = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return
    if selected.is_finite() and _decimal_span(selected) > maximum:
        raise OperatorContractError(
            "OPERATOR_RESOURCE_LIMIT", "Operator decimal precision is too large"
        )


def _decimal_span(value: Decimal) -> int:
    parts = value.as_tuple()
    digits = len(parts.digits)
    exponent = int(parts.exponent)
    return max(digits, digits + exponent, -exponent)


def _validate_output_budget(
    contract: Mapping[str, Any], output: Mapping[str, Any]
) -> None:
    if canonical_json_size(output, reason_code="OPERATOR_OUTPUT_INVALID") > contract[
        "safe_domain"
    ]["max_output_bytes"]:
        raise OperatorContractError(
            "OPERATOR_RESOURCE_LIMIT", "Operator output exceeds its byte budget"
        )


def _summary(artifact: Mapping[str, Any]) -> dict[str, Any]:
    contract = artifact["contract"]
    return {
        "uri": contract["uri"],
        "version": contract["version"],
        "owner": contract["owner"],
        "lifecycle": contract["lifecycle"],
        "method": copy.deepcopy(contract["method"]),
        "digest": artifact["digest"],
        "assumptions_digest": artifact["assumptions_digest"],
    }


def _reference(artifact: Mapping[str, Any]) -> dict[str, Any]:
    contract = artifact["contract"]
    return {
        **_summary(artifact),
        "input_schema": copy.deepcopy(contract["schemas"]["input"]),
        "output_schema": copy.deepcopy(contract["schemas"]["output"]),
        "limitations": copy.deepcopy(contract["claim_policy"]["limitations"]),
    }


def _public_artifact(artifact: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "contract": copy.deepcopy(artifact["contract"]),
        "digest": artifact["digest"],
        "component_digests": copy.deepcopy(artifact["component_digests"]),
        "assumptions_digest": artifact["assumptions_digest"],
    }


def _execution_failure(
    uri: str,
    status: str,
    reasons: Sequence[str],
    *,
    operator: Mapping[str, Any] | None,
) -> dict[str, Any]:
    return {
        "schema_version": "gravity.operator-execution.v1",
        "status": status,
        "ok": False,
        "exit_code": _LOCAL_EXIT,
        "uri": uri,
        "operator": copy.deepcopy(operator),
        "result": None,
        "reason_codes": list(dict.fromkeys(reasons)),
        "network_called": False,
    }


def _validation_failure(reason: str) -> dict[str, Any]:
    return {
        "schema_version": "gravity.operator-validation.v1",
        "status": "invalid",
        "ok": False,
        "exit_code": _LOCAL_EXIT,
        "operator": None,
        "reason_codes": [reason],
        "network_called": False,
    }


def _gap(
    schema_version: str, uri: str, status: str, reason: str
) -> dict[str, Any]:
    return {
        "schema_version": schema_version,
        "status": status,
        "ok": False,
        "exit_code": _LOCAL_EXIT,
        "uri": uri,
        "operator": None,
        "reason_codes": [reason],
        "network_called": False,
    }


def _operator_uri(value: Any) -> str:
    if not isinstance(value, str) or _URI.fullmatch(value.strip()) is None:
        raise InputValidationError(
            f"actual value: {actual_value(value)}; uri must be an exact versioned Operator URI",
            field="uri",
            next_action="Run `gravity operators list` and use an exact uri.",
        )
    return value.strip()


__all__ = ["OperatorRegistry"]
