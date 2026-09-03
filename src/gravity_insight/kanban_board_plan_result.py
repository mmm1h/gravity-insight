"""Stable result envelopes for read-only Kanban board preparation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .errors import CALLER_ERROR_EXIT, ErrorCode, ErrorDetail
from .kanban_board_plan_state import public_target
from .kanban_limits import DASHBOARD_LAYOUT_MAX_ITEMS
from .kanban_schema import kanban_collection_constraints
from .result_source import GOVERNED_PRODUCT, result_source


SCHEMA_VERSION = "gravity-insight.kanban-board-plan.v1"


def prepared_result(
    decisions: Sequence[Mapping[str, Any]],
    notes: Sequence[Mapping[str, Any]],
    state: Mapping[str, Any],
    actions: Sequence[Mapping[str, Any]],
    execution: Mapping[str, Any],
) -> dict[str, Any]:
    final_count = len(decisions) + len(notes)
    result = _base(ok=True, status="prepared", exit_code=0)
    result.update(
        {
            "network_called": state["logical_reads"] > 0,
            "atomic_execution": False,
            "admission_scope": "caller_invoked_before_first_write",
            "target_policy": "exact_desired_reports_and_notes",
            "target": public_target(state["target"]),
            "counts": _counts(decisions, notes, state["existing"]),
            "capacity": _capacity(final_count),
            "action_batch_limits": kanban_collection_constraints()[
                "action_batch_limits"
            ],
            "saved_definitions": list(decisions),
            "unsupported_items": [],
            "actions": list(actions),
            "io_estimate": _io_estimate(state, execution),
            "confirmation_flow": {
                "per_mutation": ["dry-run", "human-review", "execute"],
                "deferred_bindings": True,
                "whole_board_execute_available": False,
            },
            "error": None,
            "next_action": (
                "Resolve actions in dependency order. For every mutation, run "
                "the existing action-specific dry-run and review it before execute."
            ),
        }
    )
    return result


def capacity_rejection(charts: int, notes: int) -> dict[str, Any]:
    used = charts + notes
    detail = ErrorDetail.create(
        ErrorCode.INPUT_INVALID,
        "Desired saved definitions and notes exceed the dashboard layout capacity.",
        field="saved_definitions/notes",
        next_action=(
            f"Provide at most {DASHBOARD_LAYOUT_MAX_ITEMS} total charts and notes; "
            "do not split link requests because capacity applies to the final layout."
        ),
        write_sent=False,
        automatic_retry=False,
    )
    return _rejection(
        detail,
        {"desired": {"charts": charts, "notes": notes, "layout_items": used}},
        _capacity(used),
        [],
        [],
    )


def artifact_rejection(
    charts: Sequence[Mapping[str, Any]],
    unsupported: Sequence[Mapping[str, Any]],
    notes: int,
) -> dict[str, Any]:
    first = unsupported[0]["error"]
    detail = ErrorDetail.create(
        first["code"],
        "One or more saved definitions are not artifact-compatible.",
        category=first["category"],
        field=first["field"],
        next_action="Correct every unsupported_items path, then prepare the complete board again.",
        write_sent=False,
        automatic_retry=False,
    )
    used = len(charts) + notes
    counts = {
        "desired": {"charts": len(charts), "notes": notes, "layout_items": used}
    }
    return _rejection(detail, counts, _capacity(used), charts, unsupported)


def _base(*, ok: bool, status: str, exit_code: int) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "result_source": result_source(GOVERNED_PRODUCT),
        "ok": ok,
        "status": status,
        "exit_code": exit_code,
        "effect": "read",
        "mode": "prepare",
        "write_sent": False,
        "mutation_calls": 0,
        "confirmation_required": False,
    }


def _counts(
    decisions: Sequence[Mapping[str, Any]],
    notes: Sequence[Mapping[str, Any]],
    existing: Mapping[str, Any],
) -> dict[str, Any]:
    final = {
        "charts": len(decisions),
        "notes": len(notes),
        "layout_items": len(decisions) + len(notes),
    }
    return {"desired": dict(final), "existing": existing["counts"], "final": final}


def _capacity(used: int) -> dict[str, Any]:
    return {
        "scope": "dashboard_total_layout",
        "maximum": DASHBOARD_LAYOUT_MAX_ITEMS,
        "used": used,
        "remaining": DASHBOARD_LAYOUT_MAX_ITEMS - used,
        "request_splitting_increases_capacity": False,
    }


def _io_estimate(
    state: Mapping[str, Any], execution: Mapping[str, Any]
) -> dict[str, Any]:
    return {
        "prepare": {
            "logical_reads_performed": state["logical_reads"],
            "http_reads_upper_bound": state["http_read_upper_bound"],
            "mutation_previews": 0,
            "mutation_writes": 0,
        },
        "planned_execution": dict(execution),
    }


def _rejection(
    detail: ErrorDetail,
    counts: Mapping[str, Any],
    capacity: Mapping[str, Any],
    charts: Sequence[Mapping[str, Any]],
    unsupported: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    result = _base(ok=False, status="rejected", exit_code=CALLER_ERROR_EXIT)
    result.update(
        {
            "network_called": False,
            "counts": dict(counts),
            "capacity": dict(capacity),
            "saved_definitions": list(charts),
            "unsupported_items": [
                {"index": item["index"], "key": item["key"], "error": item["error"]}
                for item in unsupported
            ],
            "actions": [],
            "io_estimate": _zero_io(),
            "error": detail.to_dict(),
            "next_action": detail.next_action,
        }
    )
    return result


def _zero_io() -> dict[str, Any]:
    return {
        "prepare": {
            "logical_reads_performed": 0,
            "http_reads_upper_bound": 0,
            "mutation_previews": 0,
            "mutation_writes": 0,
        },
        "planned_execution": {
            "action_count": 0,
            "preview_invocations": 0,
            "execute_invocations": 0,
            "http_reads_upper_bound": 0,
            "mutation_writes": {"minimum": 0, "maximum": 0},
        },
    }


__all__ = [
    "SCHEMA_VERSION", "artifact_rejection", "capacity_rejection",
    "prepared_result",
]
