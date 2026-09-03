"""Public product router for governed Kanban mutations."""

from __future__ import annotations

import copy
from collections.abc import Callable, Mapping
from typing import Any

from .actionable_error_values import actual_value
from .errors import InputValidationError
from .kanban_content_mutation import (
    delete_note,
    replace_notes,
    save_order,
    unlink_reports,
)
from .kanban_dashboard_mutation import (
    copy_dashboard,
    create_dashboard,
    delete_dashboard,
    delete_dashboards,
    move_dashboard,
    move_dashboard_to_folder,
    rename_dashboard,
)
from .kanban_folder_mutation import create_folder, delete_folder, move_folder, rename_folder
from .kanban_report_link_mutation import link_reports
from .kanban_schema import (
    kanban_action_input_schema,
    kanban_collection_constraints,
    kanban_prepare_input_schema,
)
from .kanban_space_mutation import create_space, delete_space, rename_space, transfer_space


Handler = Callable[..., dict[str, Any]]

_ACTIONS: dict[str, tuple[Handler, frozenset[str], frozenset[str]]] = {
    "space.create": (create_space, frozenset({"app_id", "name"}), frozenset({"idempotency_key"})),
    "space.rename": (rename_space, frozenset({"app_id", "space_id", "name"}), frozenset()),
    "space.delete": (delete_space, frozenset({"app_id", "space_id"}), frozenset()),
    "space.transfer": (transfer_space, frozenset({"app_id", "space_id", "uid"}), frozenset()),
    "folder.create": (create_folder, frozenset({"app_id", "space_id", "name"}), frozenset({"idempotency_key"})),
    "folder.rename": (rename_folder, frozenset({"app_id", "space_id", "folder_id", "name"}), frozenset()),
    "folder.delete": (delete_folder, frozenset({"app_id", "space_id", "folder_id"}), frozenset()),
    "folder.move": (move_folder, frozenset({"app_id", "folder_id", "from_space_id", "to_space_id"}), frozenset()),
    "dashboard.create": (create_dashboard, frozenset({"app_id", "space_id", "folder_id", "name"}), frozenset({"idempotency_key"})),
    "dashboard.rename": (rename_dashboard, frozenset({"app_id", "space_id", "dashboard_id", "name"}), frozenset()),
    "dashboard.delete": (delete_dashboard, frozenset({"app_id", "space_id", "dashboard_id"}), frozenset()),
    "dashboard.delete-many": (delete_dashboards, frozenset({"app_id", "space_id", "dashboard_ids"}), frozenset()),
    "dashboard.move": (move_dashboard, frozenset({"app_id", "dashboard_id", "from_space_id", "to_space_id"}), frozenset({"to_folder_id"})),
    "dashboard.move-folder": (move_dashboard_to_folder, frozenset({"app_id", "space_id", "dashboard_id", "folder_id"}), frozenset()),
    "dashboard.copy": (copy_dashboard, frozenset({"app_id", "dashboard_id", "from_space_id", "to_space_id", "to_folder_id", "name"}), frozenset({"idempotency_key"})),
    "dashboard.notes.replace": (replace_notes, frozenset({"app_id", "space_id", "dashboard_id", "notes"}), frozenset()),
    "dashboard.report.link": (link_reports, frozenset({"app_id", "space_id", "dashboard_id", "report_ids"}), frozenset()),
    "dashboard.report.unlink": (unlink_reports, frozenset({"app_id", "space_id", "dashboard_id", "report_ids"}), frozenset()),
    "dashboard.order.save": (save_order, frozenset({"app_id", "order_detail"}), frozenset()),
    "note.delete": (delete_note, frozenset({"app_id", "space_id", "dashboard_id", "note_id"}), frozenset()),
}


def run_kanban_mutation(
    client: Any,
    action: str,
    inputs: Mapping[str, Any],
    *,
    execute: bool = False,
) -> dict[str, Any]:
    """Preview or explicitly execute one allowlisted Kanban product action."""

    if not isinstance(action, str) or action not in _ACTIONS:
        raise InputValidationError(
            f"actual value: {actual_value(action)}; allowed values: {actual_value(sorted(_ACTIONS))}",
            field="action",
            next_action="Choose one action from `gravity analysis dashboard kanban schema`, provide its exact inputs, and run dry-run again.",
        )
    if not isinstance(inputs, Mapping):
        raise InputValidationError(
            f"actual value: {actual_value({'type': type(inputs).__name__})}; allowed value: an input object",
            field="inputs",
            next_action="Provide a JSON object matching the selected Kanban action schema and run dry-run again.",
        )
    if not isinstance(execute, bool):
        raise InputValidationError(
            f"actual value: {actual_value(execute)}; allowed values: true or false",
            field="execute",
            next_action="Use dry-run/false for review or execute/true only after review.",
        )
    handler, required, optional = _ACTIONS[action]
    supplied = frozenset(inputs)
    missing = sorted(required - supplied)
    unknown = sorted(supplied - required - optional)
    if missing or unknown:
        raise InputValidationError(
            f"actual value: {actual_value({'missing': missing, 'unknown': unknown})}; allowed fields: {actual_value(sorted(required | optional))}",
            field="inputs",
            next_action="Add missing required fields, remove unknown fields, and run the same action in dry-run mode again.",
        )
    return handler(client, **copy.deepcopy(dict(inputs)), execute=execute)


def kanban_mutation_schema() -> dict[str, Any]:
    return {
        "schema_version": "gravity-insight.kanban-mutation-schema.v2",
        "ok": True,
        "status": "success",
        "effect": "mutation",
        "confirmation_flow": ["dry-run", "human-review", "same-action-and-inputs-with-execute"],
        "natural_language_auto_execute": False,
        "constraints": kanban_collection_constraints(),
        "whole_board_prepare": {
            "command": "gravity analysis dashboard kanban prepare --input <json|file|->",
            "effect": "read",
            "mutation_allowed": False,
            "execute_mode": False,
            "input_schema": kanban_prepare_input_schema(),
        },
        "actions": {
            action: {
                "required": sorted(required),
                "optional": sorted(optional),
                "input_schema": kanban_action_input_schema(
                    action, required, optional
                ),
            }
            for action, (_handler, required, optional) in sorted(_ACTIONS.items())
        },
    }


__all__ = ["kanban_mutation_schema", "run_kanban_mutation"]
