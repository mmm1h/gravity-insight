"""Plan v1 boundary for strict Saved Analysis replay."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from .errors import ErrorCode, InputValidationError
from .domains import ANALYSIS_QUERY_OPERATIONS
from .plan import AdapterContext
from .plan_adapter_support import (
    input_error,
    validate_exact_targets,
    validate_selected_fields,
)
from .saved_analysis import PREVIEW_SCHEMA_VERSION, REPLAY_SCHEMA_VERSION
from .saved_analysis_artifact import validate_saved_window


SAVED_ANALYSIS_NAME = "saved_analysis"
SAVED_ANALYSIS_OUTPUT_FIELDS = frozenset(
    {
        "artifact_mode",
        "date_range",
        "kind",
        "limitations",
        "operation_id",
        "result",
        "saved_analysis",
        "source",
        "validation",
    }
)
_FIELDS = frozenset({"name", "app", "ref", "mode", "start", "end"})
_TARGETS = frozenset({"/app"})
_MODES = frozenset({"prepare", "run"})
_SCHEMAS = frozenset({PREVIEW_SCHEMA_VERSION, REPLAY_SCHEMA_VERSION})
_STRUCTURAL = frozenset(
    {
        "schema_version",
        "ok",
        "status",
        "exit_code",
        "network_called",
        "definition_network_called",
        "query_executed",
        "date_override_applied",
        "input_values_redacted",
        "replay_status",
        "next_action",
    }
)
_METADATA = frozenset(
    {
        "id",
        "name",
        "subject",
        "modify_time",
        "app_id",
        "kind",
        "subject_supported",
        "replay_supported",
    }
)
_ERROR_FIELDS = frozenset(
    {"code", "category", "field", "retryable", "retry_after_ms"}
)
_CODES = frozenset(item.value for item in ErrorCode) | frozenset(
    {"BATCH_RESULT_MISSING"}
)
_CATEGORIES = frozenset({"caller", "upstream", "local"})
_STATUSES = frozenset(
    {"compiled", "success", "empty", "error", "contract_changed", "partial"}
)
_LIMITATIONS = frozenset(
    {
        "dashboard conditions are not applied by the stable event contract",
        "property analysis has no date window in its stable contract",
        "dashboard conditions are not applied",
        "dashboard conditions are not applied by the stable retention contract",
        "dashboard conditions are not applied by the stable funnel contract",
        "dashboard conditions are not applied by the stable scatter contract",
    }
)


def validate_saved_analysis(
    request: Mapping[str, Any],
    context: AdapterContext,
    workspace: Any,
    _output_fields: frozenset[str],
) -> None:
    """Validate the full literal request before artifact catalog access."""

    if set(request) - _FIELDS:
        raise input_error(
            "saved_analysis request contains unavailable fields", "request"
        )
    if request.get("name") != SAVED_ANALYSIS_NAME:
        raise input_error("saved_analysis name is invalid", "name")
    validate_exact_targets(context, _TARGETS)
    if "/app" not in context.dynamic_targets:
        _validate_app(workspace, request.get("app"))
    _validate_reference(request.get("ref"))
    if request.get("mode", "run") not in _MODES:
        raise input_error("saved_analysis mode must be prepare or run", "mode")
    _validate_window(request.get("start"), request.get("end"))
    validate_selected_fields(
        context.output_fields,
        SAVED_ANALYSIS_OUTPUT_FIELDS,
        "output_fields",
    )


def execute_saved_analysis_plan(
    sdk: Any, request: Mapping[str, Any], context: AdapterContext
) -> dict[str, Any]:
    """Resolve one reference with an explicit window and scrub its result."""

    options = {
        "workspace": context.workspace,
        "max_pages": context.max_pages,
        "max_items": context.max_items,
        "start": request.get("start"),
        "end": request.get("end"),
    }
    if request.get("mode", "run") == "prepare":
        result = sdk.prepare_saved_analysis(
            request.get("app"), request.get("ref"), **options
        )
    else:
        result = sdk.run_saved_analysis(
            request.get("app"), request.get("ref"), **options
        )
    return safe_saved_analysis_envelope(result)


def is_saved_analysis_result(result: Any) -> bool:
    return isinstance(result, Mapping) and result.get("schema_version") in _SCHEMAS


def project_saved_analysis_result(
    result: Any, fields: tuple[str, ...], _context: AdapterContext
) -> dict[str, Any]:
    safe = safe_saved_analysis_envelope(result)
    if not fields:
        return safe
    allowed = _STRUCTURAL | set(fields)
    return {
        key: copy.deepcopy(value)
        for key, value in safe.items()
        if key in allowed
    }


def safe_saved_analysis_envelope(result: Any) -> dict[str, Any]:
    """Whitelist public fields and remove artifact/request/error spill."""

    if not isinstance(result, Mapping) or result.get("schema_version") not in _SCHEMAS:
        return _contract_failure()
    safe = _safe_top(result)
    if safe is None:
        return _contract_failure()
    safe["saved_analysis"] = _safe_metadata(result.get("saved_analysis"))
    safe["validation"] = _safe_validation(result.get("validation"))
    if "result" in result:
        safe["result"] = _safe_native(result.get("result"))
    return safe


def _safe_top(result: Mapping[str, Any]) -> dict[str, Any] | None:
    status = str(result.get("status") or "")
    if status not in _STATUSES:
        return None
    ok = result.get("ok") is True
    limitations = result.get("limitations")
    return {
        "schema_version": result["schema_version"],
        "ok": ok,
        "status": status,
        "exit_code": _safe_exit_code(result.get("exit_code"), ok),
        "source": _choice(result.get("source"), {"catalog", "definition"}),
        "network_called": result.get("network_called") is True,
        "definition_network_called": result.get("definition_network_called") is True,
        "query_executed": result.get("query_executed") is True,
        "artifact_mode": _choice(
            result.get("artifact_mode"), {"compact_spec", "web_artifact"}
        ),
        "kind": _choice(result.get("kind"), set(ANALYSIS_QUERY_OPERATIONS)),
        "operation_id": _choice(
            result.get("operation_id"), set(ANALYSIS_QUERY_OPERATIONS.values())
        ),
        "date_range": _safe_date_range(result.get("date_range")),
        "date_override_applied": result.get("date_override_applied") is True,
        "input_values_redacted": result.get("input_values_redacted") is True,
        "replay_status": _choice(
            result.get("replay_status"),
            {"supported", "unsupported", "requires_window"},
        ),
        "limitations": [
            item for item in limitations if item in _LIMITATIONS
        ] if isinstance(limitations, list) else [],
        "next_action": (
            "Consume the governed Saved Analysis result."
            if ok else "Correct the governed failure before retrying this Plan node."
        ),
    }


def _choice(value: Any, allowed: set[Any]) -> Any:
    return value if isinstance(value, str) and value in allowed else None


def _safe_exit_code(value: Any, ok: bool) -> int:
    return value if type(value) is int and value in {0, 2, 3, 4} else (0 if ok else 4)


def _safe_native(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        return _native_failure()
    status = str(value.get("status") or "error")
    ok = value.get("ok") is True and status in {"success", "empty"}
    return {
        "schema_version": "gravity-insight.read.v1",
        "operation_id": (
            value.get("operation_id")
            if isinstance(value.get("operation_id"), str)
            else None
        ),
        "ok": ok,
        "status": status,
        "data": copy.deepcopy(value.get("data")) if ok else None,
        "error": _safe_error(value.get("error")) if not ok else None,
    }


def _safe_metadata(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    return {
        key: copy.deepcopy(item)
        for key, item in value.items()
        if key in _METADATA
    }


def _safe_validation(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    dependencies = value.get("live_metadata_dependencies")
    status = value.get("status")
    return {
        "status": status if status in {"valid_offline", "needs_live_metadata"} else "valid_offline",
        "live_metadata_dependencies": [
            item for item in dependencies
            if isinstance(item, str)
            and len(item) <= 128
            and item.replace(".", "").replace("_", "").isalnum()
        ] if isinstance(dependencies, list) else [],
    }


def _safe_error(value: Any) -> dict[str, Any]:
    selected = {
        key: copy.deepcopy(item)
        for key, item in value.items()
        if key in _ERROR_FIELDS
    } if isinstance(value, Mapping) else {}
    code = str(selected.get("code") or ErrorCode.UPSTREAM_UNAVAILABLE.value)
    category = str(selected.get("category") or "upstream")
    selected.update(
        {
            "code": code if code in _CODES else ErrorCode.UPSTREAM_UNAVAILABLE.value,
            "category": category if category in _CATEGORIES else "local",
            "field": "result" if selected.get("field") is not None else None,
            "message": "Saved Analysis query failed.",
            "next_action": "Correct the governed failure before retrying this Plan node.",
        }
    )
    return selected


def _safe_date_range(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    start, end = value.get("start"), value.get("end")
    if not isinstance(start, str) or not isinstance(end, str):
        return None
    try:
        validate_saved_window(start, end)
    except InputValidationError:
        return None
    return {"start": start, "end": end, "inclusive": True}


def _contract_failure() -> dict[str, Any]:
    return {
        "schema_version": REPLAY_SCHEMA_VERSION,
        "ok": False,
        "status": "contract_changed",
        "exit_code": 3,
        "error": {
            "code": ErrorCode.CONTRACT_CHANGED.value,
            "category": "upstream",
            "message": "Saved Analysis result contract changed.",
            "next_action": "Stop this Plan until the Saved Analysis contract is re-verified.",
        },
    }


def _native_failure() -> dict[str, Any]:
    return {
        "schema_version": "gravity-insight.read.v1",
        "operation_id": None,
        "ok": False,
        "status": "contract_changed",
        "data": None,
        "error": _contract_failure()["error"],
    }


def _validate_app(workspace: Any, value: Any) -> None:
    try:
        workspace.resolve_app(value)
    except (KeyError, TypeError, ValueError):
        raise input_error(
            "saved_analysis app must select a configured workspace App", "app"
        ) from None


def _validate_reference(value: Any) -> None:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise input_error(
            "saved_analysis ref must be an explicit id or exact name", "ref"
        )
    rendered = str(value).strip()
    if not rendered or len(rendered) > 256:
        raise input_error(
            "saved_analysis ref must be a bounded id or exact name", "ref"
        )


def _validate_window(start: Any, end: Any) -> None:
    if not isinstance(start, str) or not isinstance(end, str):
        raise input_error(
            "saved_analysis requires literal start and end", "start/end"
        )
    try:
        validate_saved_window(start, end)
    except InputValidationError as exc:
        raise input_error(str(exc), "start/end") from None


__all__ = [
    "SAVED_ANALYSIS_NAME",
    "SAVED_ANALYSIS_OUTPUT_FIELDS",
    "execute_saved_analysis_plan",
    "is_saved_analysis_result",
    "project_saved_analysis_result",
    "safe_saved_analysis_envelope",
    "validate_saved_analysis",
]
