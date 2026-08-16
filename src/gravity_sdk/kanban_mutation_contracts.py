"""Exact operation identities for marker-governed Kanban mutations."""

from __future__ import annotations

from .composite_catalog import stable_operation


def _operation(resource: str, action: str) -> str:
    return stable_operation("analysis", resource, action=action).operation_id


SPACE_CREATE = _operation("kanban_space", "create")
SPACE_UPDATE = _operation("kanban_space", "update")
SPACE_DELETE = _operation("kanban_space", "delete")
SPACE_TRANSFER = _operation("kanban_space", "move")

FOLDER_CREATE = _operation("kanban_folder", "create")
FOLDER_UPDATE = _operation("kanban_folder", "update")
FOLDER_DELETE = _operation("kanban_folder", "delete")
FOLDER_MOVE = _operation("kanban_folder", "move")

DASHBOARD_CREATE = _operation("kanban_dashboard", "create")
DASHBOARD_UPDATE = _operation("kanban_dashboard", "update")
DASHBOARD_RENAME = _operation("kanban_dashboard_name", "update")
DASHBOARD_DELETE = _operation("kanban_dashboard", "delete")
DASHBOARD_MOVE = _operation("kanban_dashboard", "move")
DASHBOARD_COPY = _operation("kanban_dashboard", "copy")
DASHBOARD_FOLDER_MOVE = _operation("kanban_dashboard_folder", "move")
DASHBOARD_ORDER = _operation("kanban_dashboard_order", "update")
NOTE_DELETE = _operation("kanban_note", "update")
REPORT_UNLINK = _operation("kanban_report_association", "delete")

TREE = _operation("dashboard_tree", "tree")
DETAIL = _operation("dashboard", "detail")
SPACE_MEMBERS = _operation("dashboard_space_members", "list")

KANBAN_MUTATION_OPERATIONS = frozenset(
    {
        SPACE_CREATE,
        SPACE_UPDATE,
        SPACE_DELETE,
        SPACE_TRANSFER,
        FOLDER_CREATE,
        FOLDER_UPDATE,
        FOLDER_DELETE,
        FOLDER_MOVE,
        DASHBOARD_CREATE,
        DASHBOARD_UPDATE,
        DASHBOARD_RENAME,
        DASHBOARD_DELETE,
        DASHBOARD_MOVE,
        DASHBOARD_COPY,
        DASHBOARD_FOLDER_MOVE,
        DASHBOARD_ORDER,
        NOTE_DELETE,
        REPORT_UNLINK,
    }
)


__all__ = [
    "DASHBOARD_COPY",
    "DASHBOARD_CREATE",
    "DASHBOARD_DELETE",
    "DASHBOARD_FOLDER_MOVE",
    "DASHBOARD_MOVE",
    "DASHBOARD_ORDER",
    "DASHBOARD_RENAME",
    "DASHBOARD_UPDATE",
    "DETAIL",
    "FOLDER_CREATE",
    "FOLDER_DELETE",
    "FOLDER_MOVE",
    "FOLDER_UPDATE",
    "KANBAN_MUTATION_OPERATIONS",
    "NOTE_DELETE",
    "REPORT_UNLINK",
    "SPACE_CREATE",
    "SPACE_DELETE",
    "SPACE_MEMBERS",
    "SPACE_TRANSFER",
    "SPACE_UPDATE",
    "TREE",
]
