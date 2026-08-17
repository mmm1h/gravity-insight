"""Governed realtime-event warehousing window writes with configuration readback."""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from .actionable_error_values import actual_value
from .errors import ContractChangedError, InputValidationError, MutationReadbackError
from .mutation_lifecycle import WRITE_LOCK
from .realtime_event_contracts import REALTIME_EVENT_LIST, REALTIME_EVENT_UPDATE
from .result_source import GOVERNED_PRODUCT, result_source


SCHEMA_VERSION = "gravity-insight.realtime-event-mutation.v1"
_SUCCESS = frozenset({"success", "empty", "contract_changed_additive"})
_DATETIME = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")
_REQUIRED = frozenset({"app_id", "is_enabled", "start_time", "end_time"})
_OPTIONAL = frozenset({"time_slot"})
_READBACK_SKEW_SECONDS = 120


def realtime_event_mutation_schema() -> dict[str, Any]:
    return {
        "schema_version": "gravity-insight.realtime-event-mutation-schema.v1",
        "offline": True,
        "network_called": False,
        "actions": {
            "update": {
                "required": sorted(_REQUIRED),
                "optional": sorted(_OPTIONAL),
                "confirmation_required": True,
            }
        },
    }


def run_realtime_event_mutation(
    client: Any, inputs: Mapping[str, Any], *, execute: bool = False
) -> dict[str, Any]:
    if not isinstance(inputs, Mapping):
        raise _realtime_input_error(
            actual_value(type(inputs).__name__),
            "an input object",
            "inputs",
            "Pass an object matching the offline realtime-event mutation schema.",
        )
    unknown = set(inputs) - _REQUIRED - _OPTIONAL
    missing = _REQUIRED - set(inputs)
    if missing or unknown:
        raise _realtime_input_error(
            actual_value({"missing": sorted(missing), "unknown": sorted(unknown)}),
            actual_value({"required": sorted(_REQUIRED), "optional": sorted(_OPTIONAL)}),
            "inputs",
            "Correct the selected action fields and rerun the dry-run.",
        )
    wire = _wire(inputs)
    raw_preview = client._preview_mutation(REALTIME_EVENT_UPDATE, wire)
    preview = _preview(
        raw_preview,
        wire,
        "Set one App realtime-event warehousing window; send at most one write.",
    )
    if not execute:
        return preview
    with WRITE_LOCK:
        mutation = client._execute_mutation(REALTIME_EVENT_UPDATE, wire)
        observed = _read_conf(client, wire["app_id"])
        _require_readback(observed, wire)
        return _completed(preview, mutation, observed)


def _wire(inputs: Mapping[str, Any]) -> dict[str, Any]:
    enabled = inputs["is_enabled"]
    if type(enabled) is not int or enabled not in {0, 1}:
        raise _realtime_input_error(
            actual_value(enabled),
            "0 or 1",
            "is_enabled",
            "Use 1 to open the warehousing window or 0 to close it.",
        )
    slot = inputs.get("time_slot", 2)
    if type(slot) is not int or slot != 2:
        raise _realtime_input_error(
            actual_value(slot),
            "2",
            "time_slot",
            "Use the frontend-fixed time_slot=2 and rerun the dry-run.",
        )
    return {
        "app_id": _app_id(inputs.get("app_id")),
        "is_enabled": enabled,
        "start_time": _timestamp(inputs.get("start_time"), "start_time"),
        "end_time": _timestamp(inputs.get("end_time"), "end_time"),
        "time_slot": slot,
    }


def _read_conf(client: Any, app_id: int) -> Mapping[str, Any]:
    value = client.read(REALTIME_EVENT_LIST, {"app_id": app_id})
    data = value.get("data") if isinstance(value, Mapping) else None
    conf = data.get("conf") if isinstance(data, Mapping) else None
    if (
        not isinstance(value, Mapping)
        or value.get("error") is not None
        or value.get("status") not in _SUCCESS
        or not isinstance(conf, Mapping)
    ):
        raise MutationReadbackError(
            "realtime-event configuration could not be read after the mutation",
            next_action="Read app.realtime_event.list for this App and inspect current state before another write.",
        )
    return conf


def _require_readback(conf: Mapping[str, Any], wire: Mapping[str, Any]) -> None:
    observed = {
        "app_id": conf.get("app_id"),
        "is_enabled": _flag(conf.get("is_enabled")),
        "start_time": conf.get("start_time"),
        "end_time": conf.get("end_time"),
    }
    expected = {
        "app_id": wire["app_id"],
        "is_enabled": wire["is_enabled"],
        "start_time": wire["start_time"],
        "end_time": wire["end_time"],
    }
    if (
        observed["app_id"] != expected["app_id"]
        or observed["is_enabled"] != expected["is_enabled"]
        or not _near(observed["start_time"], expected["start_time"])
        or not _near(observed["end_time"], expected["end_time"])
    ):
        raise ContractChangedError(
            "realtime-event configuration did not round-trip the acknowledged write; "
            f"actual value: {actual_value(observed)}; allowed value: {actual_value(expected)}",
            next_action="Stop writes and inspect app.realtime_event.list for this App before another update.",
        )


def _flag(value: Any) -> Any:
    if value in {0, 1} or type(value) is bool:
        return int(value)
    return value


def _near(actual: Any, expected: Any) -> bool:
    if actual == expected:
        return True
    if not isinstance(actual, str) or not isinstance(expected, str):
        return False
    try:
        left = datetime.strptime(actual, "%Y-%m-%d %H:%M:%S")
        right = datetime.strptime(expected, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return False
    return abs((left - right).total_seconds()) <= _READBACK_SKEW_SECONDS


def _preview(
    raw: Mapping[str, Any], target: Mapping[str, Any], impact: str
) -> dict[str, Any]:
    return {
        **copy.deepcopy(dict(raw)),
        "schema_version": SCHEMA_VERSION,
        "result_source": result_source(GOVERNED_PRODUCT),
        "dry_run": True,
        "confirmation_required": True,
        "automatic_retry": False,
        "target": copy.deepcopy(dict(target)),
        "impact": impact,
        "preconditions": [
            "Send at most one non-retried write.",
            "Read app.realtime_event.list after acknowledgement.",
            "Require conf.is_enabled/start_time/end_time to match the request.",
        ],
        "next_action": "Review this zero-network preview, then repeat with --execute.",
    }


def _completed(
    preview: Mapping[str, Any],
    mutation: Mapping[str, Any],
    target: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "result_source": result_source(GOVERNED_PRODUCT),
        "ok": True,
        "status": "updated",
        "operation_id": mutation.get("operation_id"),
        "effect": "mutation",
        "offline": False,
        "network_called": True,
        "dry_run": False,
        "confirmation_required": False,
        "automatic_retry": False,
        "attempts": mutation.get("attempts", 1),
        "target": copy.deepcopy(dict(target)),
        "mutation": copy.deepcopy(dict(mutation)),
        "error": None,
        "impact": preview.get("impact"),
    }


def _app_id(value: Any) -> int:
    if type(value) is not int or value < 1:
        raise _realtime_input_error(
            actual_value(value),
            "a positive integer App id",
            "app_id",
            "Use the exact App id from app.list and rerun the dry-run.",
        )
    return value


def _timestamp(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _DATETIME.fullmatch(value):
        raise _realtime_input_error(
            actual_value(value),
            "YYYY-MM-DD HH:MM:SS",
            field,
            "Use an Asia/Shanghai local datetime string and rerun the dry-run.",
        )
    return value


def _realtime_input_error(actual: str, allowed: str, field: str, next_action: str) -> InputValidationError:
    return InputValidationError(
        f"actual value: {actual}; allowed value: {allowed}",
        field=field,
        next_action=next_action,
    )


__all__ = [
    "SCHEMA_VERSION",
    "realtime_event_mutation_schema",
    "run_realtime_event_mutation",
]
