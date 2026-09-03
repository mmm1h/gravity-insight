"""Read-only admission and action planning for one complete Kanban board."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .errors import InputValidationError
from .kanban_board_plan_actions import build_actions, execution_estimate
from .kanban_board_plan_input import (
    board_input,
    note_inputs,
    prepare_charts,
    saved_inputs,
    target_input,
)
from .kanban_board_plan_result import (
    SCHEMA_VERSION,
    artifact_rejection,
    capacity_rejection,
    prepared_result,
)
from .kanban_board_plan_state import resolve_board_state
from .kanban_limits import (
    DASHBOARD_LAYOUT_MAX_ITEMS,
    PREPARE_MAX_ITEMS,
    PREPARE_MAX_PAGES,
    PREPARE_MAX_WORKERS,
)
from .kanban_mutation_support import positive_id


def prepare_kanban_board(
    client: Any,
    request: Mapping[str, Any],
    *,
    workspace: Any = None,
    max_pages: int = PREPARE_MAX_PAGES,
    max_items: int = PREPARE_MAX_ITEMS,
    max_workers: int = 6,
) -> dict[str, Any]:
    """Return a complete read-only board plan or an actionable rejection."""

    _bound(max_pages, "max_pages", PREPARE_MAX_PAGES)
    _bound(max_items, "max_items", PREPARE_MAX_ITEMS)
    _bound(max_workers, "max_workers", PREPARE_MAX_WORKERS)
    source = board_input(request)
    app_id = positive_id(source["app_id"], "app_id")
    target = target_input(source["target"])
    saved = saved_inputs(source["saved_definitions"])
    notes = note_inputs(source["notes"])
    desired_count = len(saved) + len(notes)
    if desired_count > DASHBOARD_LAYOUT_MAX_ITEMS:
        return capacity_rejection(len(saved), len(notes))
    charts, prepared = prepare_charts(saved, app_id=app_id, workspace=workspace)
    unsupported = [item for item in charts if item["supported"] is False]
    if unsupported:
        return artifact_rejection(charts, unsupported, len(notes))
    state = resolve_board_state(
        client,
        prepared,
        app_id=app_id,
        target=target,
        notes=notes,
        workspace=workspace,
        max_pages=max_pages,
        max_items=max_items,
        max_workers=max_workers,
    )
    actions = build_actions(
        state["decisions"], notes, state["target"], state["existing"]
    )
    execution = execution_estimate(actions, max_pages=max_pages)
    return prepared_result(state["decisions"], notes, state, actions, execution)


def _bound(value: Any, field: str, maximum: int) -> int:
    if type(value) is not int or not 1 <= value <= maximum:
        raise InputValidationError(
            f"{field} must be between 1 and {maximum}",
            field=field,
            next_action="Use the documented bounded prepare option and retry.",
        )
    return value


__all__ = ["SCHEMA_VERSION", "prepare_kanban_board"]
