"""Governed Analysis SDK default-value dictionary for one App."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from . import runtime
from .composite_catalog import stable_operation
from .errors import ErrorCode, ErrorDetail, exit_code_for_error
from .result_audit import project_result_audit
from .result_source import GOVERNED_PRODUCT, result_source


SCHEMA_VERSION = "gravity-insight.analysis-default-dictionary.v1"
OPERATION_ID = stable_operation("analysis", "default_val", action="list").operation_id
DICTIONARY_KEYS = frozenset({"api", "cocoscreator"})
_SUCCESS = frozenset({"success", "empty"})
_ERROR_CODES = frozenset(code.value for code in ErrorCode)


def analysis_default_dictionary(client: Any, app_id: int) -> dict[str, Any]:
    """Read the complete registered SDK-family dictionary in one request."""

    native = runtime.call_read(client, OPERATION_ID, {"app_id": app_id})
    return analysis_default_dictionary_result(native, app_id=app_id)


def analysis_default_dictionary_result(
    native: Any, *, app_id: int
) -> dict[str, Any]:
    """Project a raw operation envelope into the product contract."""

    if not isinstance(native, Mapping):
        return _contract_failure(native, app_id)
    status = str(native.get("status", "contract_changed"))
    if (
        native.get("schema_version") != "gravity-insight.read.v1"
        or native.get("operation_id") != OPERATION_ID
        or status not in _SUCCESS
    ):
        return _native_failure(native, app_id, status)
    data = _safe_dictionary(native.get("data"))
    if data is None:
        return _contract_failure(native, app_id)
    value_count = sum(len(values) for values in data.values())
    if status == "empty" and value_count:
        return _contract_failure(native, app_id)
    product_status = "empty" if value_count == 0 else "success"
    result = {
        "schema_version": SCHEMA_VERSION,
        "result_source": result_source(GOVERNED_PRODUCT),
        "ok": True,
        "status": product_status,
        "exit_code": 0,
        "operation_id": OPERATION_ID,
        "app_id": app_id,
        "dictionary_count": len(data),
        "value_count": value_count,
        "data": data,
        "error": None,
    }
    return project_result_audit(result, native)


def _safe_dictionary(value: Any) -> dict[str, list[str]] | None:
    if not isinstance(value, Mapping) or set(value) - DICTIONARY_KEYS:
        return None
    result: dict[str, list[str]] = {}
    for key, values in value.items():
        if not isinstance(values, list) or any(not isinstance(item, str) for item in values):
            return None
        result[str(key)] = copy.deepcopy(values)
    return result


def _native_failure(
    native: Mapping[str, Any], app_id: int, status: str
) -> dict[str, Any]:
    error = native.get("error")
    if not isinstance(error, Mapping):
        return _contract_failure(native, app_id)
    raw_code = error.get("code")
    code = raw_code if isinstance(raw_code, str) and raw_code in _ERROR_CODES else ErrorCode.CONTRACT_CHANGED
    retry_after = error.get("retry_after_ms")
    detail = ErrorDetail.create(
        code,
        "Analysis default dictionary could not complete its governed read.",
        operation_id=OPERATION_ID,
        field=error.get("field") if isinstance(error.get("field"), str) else None,
        retry_after_ms=retry_after if type(retry_after) is int and retry_after >= 0 else None,
        next_action=(
            str(error["next_action"])
            if isinstance(error.get("next_action"), str) and error["next_action"]
            else None
        ),
    )
    return project_result_audit(_failure(app_id, status, detail), native)


def _contract_failure(native: Any, app_id: int) -> dict[str, Any]:
    detail = ErrorDetail.create(
        ErrorCode.CONTRACT_CHANGED,
        "Analysis default dictionary result no longer matches its registered contract.",
        operation_id=OPERATION_ID,
        next_action="Stop automation, refresh the shape evidence, and retry after the contract is updated.",
    )
    return project_result_audit(_failure(app_id, "contract_changed", detail), native)


def _failure(app_id: int, status: str, detail: ErrorDetail) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "result_source": result_source(GOVERNED_PRODUCT),
        "ok": False,
        "status": status,
        "exit_code": exit_code_for_error(detail),
        "operation_id": OPERATION_ID,
        "app_id": app_id,
        "dictionary_count": 0,
        "value_count": 0,
        "data": {},
        "error": detail.to_dict(),
    }


__all__ = [
    "DICTIONARY_KEYS",
    "OPERATION_ID",
    "SCHEMA_VERSION",
    "analysis_default_dictionary",
    "analysis_default_dictionary_result",
]
