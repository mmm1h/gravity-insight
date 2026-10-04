"""Value-free readback after a rejected export creation (#248).

Upstream rewrites the displayed task_name, but each task-list row keeps the
exact submitted body as a JSON string in ``args``.  Byte-for-byte canonical
equality with the body this SDK sent is therefore a certified request
identity; display names and timestamps never are.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from typing import Any

from .export_models import ExportRuntimeError, _export_error

# Task-list status codes whose job can still be resumed or downloaded.
_RESUMABLE_STATUSES = frozenset({0, 1, 2})
_ASSOCIATIONS = frozenset({"existing_identical_task", "not_found", "ambiguous", "unconfirmed"})


# Fixed upstream msg vocabulary; extra.error is never echoed. "参数错误" came
# with every code=1004 rejection reproduced on 2026-10-04 (#247, #248).
_REVIEWED_SEMANTIC_MESSAGES = {"参数错误": "invalid_parameter"}
_INVALID_PARAMETER = {
    "message": "Gravity export rejected the request; upstream reports invalid parameters",
    "next_action": (
        "Upstream reports invalid parameters for this request. Do not retry it "
        "unchanged or change business filters to work around it; compare this "
        "request with a same-shape request that succeeded and report the sanitized "
        "diagnostics to the maintainer."
    ),
    "details": {"semantic_message": "invalid_parameter"},
}


def reviewed_semantic_rejection(msg: Any) -> Mapping[str, Any]:
    """Return message/next_action/details overrides for a reviewed upstream msg."""
    return _INVALID_PARAMETER if _REVIEWED_SEMANTIC_MESSAGES.get(msg) == "invalid_parameter" else {}


def semantic_responsibility(details: Any) -> str:
    invalid = isinstance(details, Mapping) and details.get("semantic_message") == "invalid_parameter"
    return "upstream_reported_invalid_parameter" if invalid else "unclassified"


def semantic_reason(code: str, details: Any, default: str) -> str:
    if code == "EXPORT_SEMANTIC_REJECTED" and semantic_responsibility(details) != "unclassified":
        return semantic_responsibility(details)
    return default


def rejected_creation_error(
    error: ExportRuntimeError,
    contract: Any,
    contracts: Any,
    call: Callable[..., Any],
    submitted: Mapping[str, Any],
    timeout_seconds: float,
) -> ExportRuntimeError:
    recovery = contract.response["creation_recovery"]
    association = certify_creation(
        _readback(recovery, contracts, call, timeout_seconds), submitted,
        task_type=str(recovery.get("task_type", "")),
    )
    return _export_error(
        str(error), code=error.code, stage=error.stage, category=error.category,
        field=error.field, retryable=False,
        next_action=_recovery_action(association["association"], contract.operation_id),
        details={**error.details, "creation_recovery": association},
    )


def _readback(
    recovery: Mapping[str, Any], contracts: Any, call: Callable[..., Any], timeout_seconds: float
) -> Mapping[str, Any] | None:
    try:
        _, payload, _ = call(
            contracts.get(str(recovery["list_operation"])),
            {"page": 1, "page_size": int(recovery["page_size"])},
            timeout_seconds=min(timeout_seconds, 30.0), attempts=1,
        )
    except Exception:
        # A failed readback is uncertainty, never proof that no task exists.
        return None
    return payload


def _recovery_action(association: str, operation_id: str) -> str:
    if association == "existing_identical_task":
        return (
            "A task whose stored request equals this exact request already exists; "
            f"resume it with `gravity export wait --operation-id {operation_id} "
            "<job_id>` using the returned job_id. Do not create again."
        )
    if association == "ambiguous":
        return (
            "Several tasks store exactly this request; inspect `gravity export list` "
            "and resume one deliberately. Do not create again."
        )
    if association == "not_found":
        return (
            "No task with this exact request is in the newest export tasks; this "
            "rejected attempt left no recoverable job. Do not retry it unchanged; "
            "correct the request or report the sanitized diagnostics."
        )
    return (
        "The task-list readback was unavailable, so creation is unconfirmed. Run "
        "`gravity export list` before authorizing another job; do not guess an ID."
    )


def certify_creation(
    payload: Mapping[str, Any] | None, submitted: Mapping[str, Any], *, task_type: str
) -> dict[str, Any]:
    data = payload.get("data", payload) if isinstance(payload, Mapping) else None
    rows = data.get("list") if isinstance(data, Mapping) else None
    expected = _canonical(submitted)
    if not isinstance(rows, list) or expected is None:
        return _association("unconfirmed")
    page = data.get("page_info")
    total = page.get("total_number") if isinstance(page, Mapping) else None
    matches = [
        row for row in rows
        if isinstance(row, Mapping) and row.get("task_type") == task_type
        and _canonical_args(row.get("args")) == expected
    ]
    result = _matched_association(matches)
    result.update(
        match_count=len(matches), rows_checked=len(rows),
        readback_complete=type(total) is int and total == len(rows),
    )
    return result


def _matched_association(matches: list[Mapping[str, Any]]) -> dict[str, Any]:
    if not matches:
        return _association("not_found")
    if len(matches) > 1 or _task_id(matches[0]) is None:
        return _association("ambiguous")
    status = matches[0].get("status")
    return _association(
        "existing_identical_task", job_id=_task_id(matches[0]),
        resumable=type(status) is int and status in _RESUMABLE_STATUSES,
    )


def _association(kind: str, *, job_id: str | None = None, resumable: bool = False) -> dict[str, Any]:
    return {
        "association": kind, "job_id": job_id, "resumable": resumable,
        "match_count": 0, "rows_checked": 0, "readback_complete": False,
    }


def recovery_diagnostics(error: Any) -> dict[str, Any]:
    recovery = recovery_fields(error).get("creation_recovery")
    return {"creation_recovery": recovery} if recovery else {}


def recovery_fields(error: Any) -> dict[str, Any]:
    details = getattr(error, "details", {})
    recovery = details.get("creation_recovery") if isinstance(details, Mapping) else None
    if not isinstance(recovery, Mapping) or recovery.get("association") not in _ASSOCIATIONS:
        return {}
    job_id = recovery.get("job_id") if recovery["association"] == "existing_identical_task" else None
    job_id = _task_id({"id": job_id}) if job_id is not None else None
    return {
        "creation_recovery": {
            "association": recovery["association"],
            "match_basis": "exact_submitted_args",
            "match_count": _count(recovery.get("match_count")),
            "rows_checked": _count(recovery.get("rows_checked")),
            "readback_complete": recovery.get("readback_complete") is True,
        },
        "job_id": job_id,
        "resumable": bool(job_id and recovery.get("resumable") is True),
    }


def _canonical_args(raw: Any) -> str | None:
    if not isinstance(raw, str) or len(raw) > 131_072:
        return None
    try:
        parsed = json.loads(raw, object_pairs_hook=_unique_object)
    except (ValueError, TypeError, RecursionError):
        return None
    return _canonical(parsed) if isinstance(parsed, dict) else None


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate argument key")
        result[key] = value
    return result


def _canonical(value: Mapping[str, Any]) -> str | None:
    try:
        return json.dumps(dict(value), sort_keys=True, ensure_ascii=True, allow_nan=False, separators=(",", ":"))
    except (TypeError, ValueError):
        return None


def _task_id(row: Mapping[str, Any]) -> str | None:
    value = row.get("id")
    if type(value) is int and value > 0:
        return str(value)
    if isinstance(value, str) and value.isascii() and value.isalnum() and 0 < len(value) <= 64:
        return value
    return None


def _count(value: Any) -> int:
    return value if type(value) is int and value >= 0 else 0
