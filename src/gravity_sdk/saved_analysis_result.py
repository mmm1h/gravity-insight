"""Execution and safe result assembly for Saved Analysis replay."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .domains import ANALYSIS_QUERY_OPERATIONS
from .errors import ContractChangedError, ErrorCategory, exit_code_for_category
from .runtime import call_read
from .saved_analysis_support import SUCCESS_STATUSES, safe_query_envelope
from .result_source import GOVERNED_PRODUCT, result_source


_PRIMARY_RESULT_KEYS = {
    ANALYSIS_QUERY_OPERATIONS["event"]: ("list",),
    ANALYSIS_QUERY_OPERATIONS["property"]: ("list",),
    ANALYSIS_QUERY_OPERATIONS["retention"]: ("total",),
    ANALYSIS_QUERY_OPERATIONS["funnel"]: (
        "aggregate_by_date",
        "aggregate_date",
        "date_list",
    ),
    ANALYSIS_QUERY_OPERATIONS["scatter"]: ("aggregate_date", "zone_tags"),
}
_PRIMARY_TYPES = {
    ANALYSIS_QUERY_OPERATIONS["event"]: {"list": list},
    ANALYSIS_QUERY_OPERATIONS["property"]: {"list": list},
    ANALYSIS_QUERY_OPERATIONS["retention"]: {"total": list},
    ANALYSIS_QUERY_OPERATIONS["funnel"]: {
        "aggregate_by_date": (Mapping, type(None)),
        "aggregate_date": (Mapping, type(None)),
        "date_list": list,
    },
    ANALYSIS_QUERY_OPERATIONS["scatter"]: {
        "aggregate_date": list,
        "zone_tags": Mapping,
    },
}
_RESULT_KEYS = {
    ANALYSIS_QUERY_OPERATIONS["event"]: frozenset(
        {"list", "target_list", "default_limit", "date_list"}
    ),
    ANALYSIS_QUERY_OPERATIONS["property"]: frozenset({"list", "target"}),
    ANALYSIS_QUERY_OPERATIONS["retention"]: frozenset(
        {"total", "x", "y", "date_to_week", "date_to_month"}
    ),
    ANALYSIS_QUERY_OPERATIONS["funnel"]: frozenset(
        {"date_list", "aggregate_by_date", "aggregate_date", "window_funnel_mode"}
    ),
    ANALYSIS_QUERY_OPERATIONS["scatter"]: frozenset({"aggregate_date", "zone_tags"}),
}


def execute_compiled(client: Any, compiled: Any) -> dict[str, Any]:
    query = call_read(client, compiled.operation_id, compiled.inputs)
    safe = safe_query_envelope(query)
    returned = safe.get("operation_id")
    if returned not in (None, compiled.operation_id):
        raise ContractChangedError(
            "saved Analysis query returned a different operation identity",
            next_action="Stop replay until the saved Analysis result contract is re-verified.",
        )
    safe["operation_id"] = compiled.operation_id
    return safe


def replay_envelope(
    schema_version: str,
    compiled: Any,
    result: Mapping[str, Any],
    metadata: Mapping[str, Any],
    *,
    source: str,
    definition_network_called: bool,
) -> dict[str, Any]:
    status = str(result.get("status", "error"))
    ok = (
        result.get("ok") is True
        and status in SUCCESS_STATUSES
        and result.get("error") in (None, {})
    )
    return {
        "schema_version": schema_version,
        "result_source": result_source(GOVERNED_PRODUCT),
        "ok": ok,
        "status": status,
        "exit_code": 0 if ok else _exit_code(result),
        "source": source,
        "network_called": True,
        "definition_network_called": definition_network_called,
        "query_executed": True,
        "saved_analysis": {**metadata, "replay_supported": True},
        "artifact_mode": compiled.artifact_mode,
        "kind": compiled.kind,
        "operation_id": compiled.operation_id,
        "date_range": compiled.date_range,
        "date_override_applied": compiled.date_override_applied,
        "limitations": list(compiled.limitations),
        "validation": {
            "status": compiled.validation_status,
            "live_metadata_dependencies": list(
                compiled.live_metadata_dependencies
            ),
        },
        "result": dict(result),
        "next_action": (
            "Consume the governed Analysis result."
            if ok
            else "Follow result.error.next_action; do not consume a failed replay."
        ),
    }


def _exit_code(value: Mapping[str, Any]) -> int:
    error = value.get("error")
    category = error.get("category") if isinstance(error, Mapping) else None
    return exit_code_for_category(str(category), default=ErrorCategory.UPSTREAM)


def saved_result_item_count(operation_id: str, value: Any) -> int:
    """Count the proven primary container for each Analysis result family."""

    if isinstance(value, Mapping) and value.get("ok") is False:
        return 0
    if operation_id not in _PRIMARY_RESULT_KEYS:
        raise ContractChangedError("saved Analysis returned an unknown operation identity")
    data = value.get("data") if isinstance(value, Mapping) else None
    if not isinstance(data, Mapping):
        raise ContractChangedError("saved Analysis result data changed shape")
    if any(not isinstance(key, str) or key not in _RESULT_KEYS[operation_id] for key in data):
        raise ContractChangedError("saved Analysis result contains unregistered data fields")
    observed = False
    counts: list[int] = []
    for key in _PRIMARY_RESULT_KEYS.get(operation_id, ()):
        if key not in data:
            continue
        observed = True
        value = data[key]
        expected = _PRIMARY_TYPES[operation_id][key]
        if not isinstance(value, expected):
            raise ContractChangedError(
                "saved Analysis primary result container changed shape",
                next_action="Stop replay until the result contract is re-verified.",
            )
        counts.append(_container_width(value))
    if operation_id == ANALYSIS_QUERY_OPERATIONS["event"] and not observed:
        raise ContractChangedError("saved event Analysis result omitted its required list")
    return max(counts, default=0)


def _container_width(value: Any) -> int:
    if isinstance(value, list):
        nested = [
            _container_width(item)
            for item in value
            if isinstance(item, (Mapping, list))
        ]
        return max([len(value), *nested])
    if not isinstance(value, Mapping):
        return 0
    nested = [
        _container_width(item)
        for item in value.values()
        if isinstance(item, (Mapping, list))
    ]
    if not value:
        return 0
    return max([len(value), *nested])


__all__ = ["execute_compiled", "replay_envelope", "saved_result_item_count"]
