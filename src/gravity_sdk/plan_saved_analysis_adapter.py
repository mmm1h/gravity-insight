"""Plan v1 boundary for strict Saved Analysis replay."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from .errors import ErrorCategory, ErrorCode, ErrorDetail, InputValidationError, PaginationError, exit_code_for_category, exit_code_for_error
from .domains import ANALYSIS_QUERY_OPERATIONS
from .plan import AdapterContext
from .plan_adapter_support import (
    input_error,
    validate_exact_targets,
    validate_selected_fields,
)
from .saved_analysis import PREVIEW_SCHEMA_VERSION, REPLAY_SCHEMA_VERSION
from .saved_analysis_artifact import validate_saved_window
from .saved_analysis_result import saved_result_item_count
from .saved_analysis_support import SUBJECT_KINDS


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
        "error",
        "next_action",
    }
)
_ERROR_EXIT_CODES = frozenset(
    exit_code_for_category(category) for category in ErrorCategory
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
    {
        "compiled", "success", "empty", "error", "contract_changed",
        "contract_changed_additive", "partial", "semantic_error", "unavailable",
        "parent_required", "permission_unavailable",
    }
)
_NATIVE_STATUSES = _STATUSES - {"compiled"}
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
    mode = request.get("mode", "run")
    if not isinstance(mode, str) or mode not in _MODES:
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
        "max_workers": 1,
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
    safe = safe_saved_analysis_envelope(result)
    if not _matches_request(safe, request, context):
        return _contract_failure()
    native = safe.get("result")
    operation_id = safe.get("operation_id")
    if (
        safe.get("ok") is True
        and isinstance(operation_id, str)
        and saved_result_item_count(operation_id, native) > context.max_items
    ):
        raise PaginationError(
            "saved Analysis query exceeded its Plan item safety bound",
            next_action="Increase this node max_items within the documented limit.",
        )
    return safe


def is_saved_analysis_result(result: Any) -> bool:
    schema = result.get("schema_version") if isinstance(result, Mapping) else None
    return isinstance(schema, str) and schema in _SCHEMAS


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

    schema = result.get("schema_version") if isinstance(result, Mapping) else None
    if not isinstance(schema, str) or schema not in _SCHEMAS:
        return _contract_failure()
    safe = _safe_top(result)
    if safe is None:
        return _contract_failure()
    if not _valid_plan_source(safe):
        return _contract_failure()
    metadata = _safe_metadata(result.get("saved_analysis"))
    expected_operation = ANALYSIS_QUERY_OPERATIONS.get(safe["kind"])
    if not _valid_identity(safe, metadata, expected_operation):
        return _contract_failure()
    assert metadata is not None
    safe["saved_analysis"] = metadata
    validation = _safe_validation(result.get("validation"))
    if validation is None:
        return _contract_failure()
    safe["validation"] = validation
    if safe["schema_version"] == PREVIEW_SCHEMA_VERSION:
        return safe if _valid_preview(safe, result) else _contract_failure()
    return _safe_replay(safe, result, expected_operation)


def _valid_plan_source(value: Mapping[str, Any]) -> bool:
    return (
        value["source"] == "catalog"
        and value["network_called"] is True
        and value["definition_network_called"] is True
    )


def _valid_identity(
    safe: Mapping[str, Any], metadata: Mapping[str, Any] | None, operation: Any
) -> bool:
    return bool(
        metadata is not None
        and operation is not None
        and safe["operation_id"] == operation
        and safe["artifact_mode"] is not None
        and (safe["artifact_mode"] == "compact_spec" or safe["date_range"] is not None)
        and metadata.get("kind") == safe["kind"]
        and SUBJECT_KINDS.get(metadata.get("subject")) == safe["kind"]
        and metadata.get("subject_supported") is True
        and metadata.get("replay_supported") is True
        and {"id", "name", "subject", "app_id"}.issubset(metadata)
    )


def _valid_preview(safe: Mapping[str, Any], result: Mapping[str, Any]) -> bool:
    return (
        safe["status"] == "compiled"
        and safe["ok"] is True
        and safe["exit_code"] == 0
        and safe["query_executed"] is False
        and "result" not in result
    )


def _safe_replay(
    safe: dict[str, Any], result: Mapping[str, Any], operation: Any
) -> dict[str, Any]:
    if "result" not in result or safe["query_executed"] is not True:
        return _contract_failure()
    native = _safe_native(result.get("result"))
    if native is None or native["operation_id"] != operation:
        return _contract_failure()
    safe["result"] = native
    if native["ok"] is not True:
        safe.update(_nested_failure(native))
        return safe
    if safe["ok"] is not True or safe["status"] != native["status"] or safe["exit_code"] != 0:
        return _contract_failure()
    return safe


def _nested_failure(native: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "ok": False,
        "status": str(native["status"]),
        "exit_code": _error_exit_code(native["error"]),
        "error": copy.deepcopy(native["error"]),
        "next_action": "Correct the governed failure before retrying this Plan node.",
    }


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
            item for item in limitations
            if isinstance(item, str) and item in _LIMITATIONS
        ] if isinstance(limitations, list) else [],
        "next_action": (
            "Review the governed preview, then run the same explicit Saved Analysis node."
            if ok and result["schema_version"] == PREVIEW_SCHEMA_VERSION
            else "Consume the governed Saved Analysis result."
            if ok
            else "Correct the governed failure before retrying this Plan node."
        ),
    }


def _choice(value: Any, allowed: set[Any]) -> Any:
    return value if isinstance(value, str) and value in allowed else None


def _safe_exit_code(value: Any, ok: bool) -> int:
    valid = {0, *_ERROR_EXIT_CODES}
    if type(value) is int and value in valid:
        return value
    return 0 if ok else exit_code_for_category(ErrorCategory.LOCAL)


def _error_exit_code(value: Any) -> int:
    category = value.get("category") if isinstance(value, Mapping) else None
    return exit_code_for_category(str(category), default=ErrorCategory.LOCAL)


def _safe_native(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None if value is None else _native_failure()
    status = _native_status(value)
    if status is None:
        return _native_failure()
    data = value.get("data")
    success_status = status in {"success", "empty"}
    if not _native_data_valid(data, success_status):
        return _native_failure()
    error = value.get("error")
    ok = value.get("ok") is True and success_status and error in (None, {})
    if success_status and not ok:
        return _native_failure()
    return {
        "schema_version": "gravity-insight.read.v1",
        "operation_id": (
            value.get("operation_id")
            if isinstance(value.get("operation_id"), str)
            else None
        ),
        "ok": ok,
        "status": status,
        "data": copy.deepcopy(data) if ok else None,
        "error": _safe_error(value.get("error")) if not ok else None,
    }


def _native_status(value: Mapping[str, Any]) -> str | None:
    status = value.get("status")
    return status if (
        value.get("schema_version") == "gravity-insight.read.v1"
        and isinstance(status, str)
        and status in _NATIVE_STATUSES
    ) else None


def _native_data_valid(value: Any, success: bool) -> bool:
    return isinstance(value, Mapping) if success else value is None


def _safe_metadata(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    result: dict[str, Any] = {}
    for key, item in value.items():
        if key not in _METADATA:
            continue
        if key in {"subject_supported", "replay_supported"}:
            if item is not None and not isinstance(item, bool):
                return None
        elif key == "kind":
            if not isinstance(item, str) or item not in ANALYSIS_QUERY_OPERATIONS:
                return None
        elif not isinstance(item, (str, int)) or isinstance(item, bool) or len(str(item)) > 256:
            return None
        result[key] = copy.deepcopy(item)
    return result


def _safe_validation(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    dependencies = value.get("live_metadata_dependencies")
    status = value.get("status")
    if not isinstance(status, str) or status not in {"valid_offline", "needs_live_metadata"} or not isinstance(
        dependencies, list
    ):
        return None
    if any(
        not isinstance(item, str)
        or len(item) > 128
        or not item.replace(".", "").replace("_", "").isalnum()
        for item in dependencies
    ):
        return None
    return {
        "status": status,
        "live_metadata_dependencies": list(dependencies),
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
            "retryable": selected.get("retryable") is True,
            "retry_after_ms": (
                selected.get("retry_after_ms")
                if type(selected.get("retry_after_ms")) is int
                and selected["retry_after_ms"] >= 0
                else None
            ),
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
    detail = ErrorDetail.create(
        ErrorCode.CONTRACT_CHANGED,
        "Saved Analysis result contract changed.",
        next_action="Stop this Plan until the Saved Analysis contract is re-verified.",
    )
    return {
        "schema_version": REPLAY_SCHEMA_VERSION,
        "ok": False,
        "status": "contract_changed",
        "exit_code": exit_code_for_error(detail),
        "error": {
            "code": ErrorCode.CONTRACT_CHANGED.value,
            "category": "upstream",
            "message": "Saved Analysis result contract changed.",
            "next_action": "Stop this Plan until the Saved Analysis contract is re-verified.",
        },
    }


def _matches_request(
    safe: Mapping[str, Any], request: Mapping[str, Any], context: AdapterContext
) -> bool:
    mode = request.get("mode", "run")
    expected_schema = PREVIEW_SCHEMA_VERSION if mode == "prepare" else REPLAY_SCHEMA_VERSION
    metadata = safe.get("saved_analysis")
    date_range = safe.get("date_range")
    if not isinstance(metadata, Mapping) or not isinstance(date_range, Mapping):
        return False
    try:
        app_id = str(context.workspace.resolve_app(request.get("app")))
    except (KeyError, TypeError, ValueError):
        return False
    raw_reference = request.get("ref")
    reference = str(raw_reference).strip()
    matches_reference = (
        metadata.get("id") == reference
        if isinstance(raw_reference, int) and not isinstance(raw_reference, bool)
        else reference in {str(metadata.get("id")), str(metadata.get("name"))}
    )
    return (
        safe.get("schema_version") == expected_schema
        and metadata.get("app_id") == app_id
        and matches_reference
        and date_range.get("start") == request.get("start")
        and date_range.get("end") == request.get("end")
    )


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
