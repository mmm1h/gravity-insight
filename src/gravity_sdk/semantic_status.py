"""Classify upstream protocol status without treating business values as status."""

from __future__ import annotations

from typing import Any, Mapping

from .errors import SemanticRejectedError
from .models import OperationSpec, SemanticErrorRule
from .result_audit import bind_error_receipts


SEMANTIC_SUCCESS = "success"
SEMANTIC_EXPLICIT_EMPTY = "explicit_empty"
SEMANTIC_REJECTED = "rejected"
SEMANTIC_INVALID_ENVELOPE = "invalid_envelope"

SUCCESS_CODES = (None, 0, 200, "0", "200")
EXPLICIT_EMPTY_EXTRA_ERRORS = frozenset({"无数据"})
_ABSENT = object()


def classify_semantic_status(payload: Any) -> str:
    """Return the registered meaning of one response's protocol status.

    Only an exact observed no-data value with a success code and no meaningful
    business data is empty. Any unknown non-empty ``extra.error`` fails closed.
    """

    if not isinstance(payload, Mapping):
        return SEMANTIC_INVALID_ENVELOPE
    if payload.get("code") not in SUCCESS_CODES:
        return SEMANTIC_REJECTED
    extra = payload.get("extra")
    error = extra.get("error", _ABSENT) if isinstance(extra, Mapping) else _ABSENT
    if error is _ABSENT or not error:
        return SEMANTIC_SUCCESS
    if (
        isinstance(error, str)
        and error in EXPLICIT_EMPTY_EXTRA_ERRORS
        and not response_data_nonempty(payload)
    ):
        return SEMANTIC_EXPLICIT_EMPTY
    return SEMANTIC_REJECTED


def enforce_semantic_rules(
    operation: OperationSpec, payload: Mapping[str, Any], http_receipts: Any = ()
) -> str:
    semantic_status = classify_semantic_status(payload)
    rules = operation.semantic_error_rules or (
        SemanticErrorRule("code", "not_in", values=(0, 200)),
        SemanticErrorRule("extra.error"),
    )
    for rule in rules:
        if (
            semantic_status in {SEMANTIC_SUCCESS, SEMANTIC_EXPLICIT_EMPTY}
            and rule.path == "code"
        ):
            continue
        if semantic_status == SEMANTIC_EXPLICIT_EMPTY and rule.path == "extra.error":
            continue
        current = _path_get(payload, rule.path)
        exists = current is not _ABSENT
        triggered = {
            "equals": exists and current == rule.value,
            "not_equals": exists and current != rule.value,
            "exists": exists,
            "truthy": exists and bool(current),
            "falsy": exists and not bool(current),
            "in": exists and current in rule.values,
            "not_in": exists and current not in rule.values,
        }[rule.operator]
        if triggered:
            _raise_semantic(rule.message, http_receipts)
    if semantic_status == SEMANTIC_REJECTED:
        _raise_semantic("Gravity returned an unregistered semantic status", http_receipts)
    return semantic_status


def response_data_nonempty(payload: Any) -> bool:
    if not isinstance(payload, Mapping):
        return False
    data = payload.get("data")
    if data is None:
        return False
    if isinstance(data, Mapping):
        if "list" in data and isinstance(data["list"], list):
            return bool(data["list"])
        return any(_meaningful(item) for item in data.values())
    if isinstance(data, (list, str)):
        return bool(data)
    return True


def protocol_status_evidence(payload: Any, *, http_status: int | None) -> dict[str, Any]:
    """Retain only upstream protocol decision fields and their classification."""

    classification = (
        SEMANTIC_EXPLICIT_EMPTY
        if http_status == 204
        else classify_semantic_status(payload)
    )
    result: dict[str, Any] = {
        "classification": classification,
        "code": _evidence_field(payload, "code"),
        "msg": _evidence_field(payload, "msg"),
        "extra_error": _evidence_field(payload, "extra", "error"),
    }
    return result


def _evidence_field(payload: Any, *path: str) -> dict[str, Any]:
    current = payload
    for part in path:
        if not isinstance(current, Mapping) or part not in current:
            return {"present": False}
        current = current[part]
    if current is None or isinstance(current, (bool, int, float, str)):
        return {"present": True, "value": current}
    return {
        "present": True,
        "value_persisted": False,
        "value_type": "object" if isinstance(current, Mapping) else "array",
        "truthy": bool(current),
    }


def _path_get(value: Any, path: str) -> Any:
    current = value
    for part in path.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return _ABSENT
        current = current[part]
    return current


def _raise_semantic(message: str, http_receipts: Any) -> None:
    error = SemanticRejectedError(message)
    bind_error_receipts(error, http_receipts)
    raise error


def _meaningful(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, Mapping):
        return any(_meaningful(item) for item in value.values())
    if isinstance(value, (list, str)):
        return bool(value)
    return True
