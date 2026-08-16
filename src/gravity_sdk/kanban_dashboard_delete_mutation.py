"""Owned Kanban dashboard deletion and bounded content preflight."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from .actionable_error_values import actual_value
from .errors import InputValidationError, MutationReadbackError
from .kanban_mutation_contracts import DASHBOARD_DELETE
from .kanban_mutation_support import (
    WRITE_LOCK,
    completed,
    detail_notes,
    find_object,
    mutation_preview,
    positive_id,
    read_detail,
    read_tree,
    report_list,
    require_owned,
)


def delete_dashboard(
    client: Any,
    *,
    app_id: int,
    space_id: int,
    dashboard_id: int,
    execute: bool = False,
) -> dict[str, Any]:
    return delete_dashboards(
        client,
        app_id=app_id,
        space_id=space_id,
        dashboard_ids=[dashboard_id],
        execute=execute,
    )


def delete_dashboards(
    client: Any,
    *,
    app_id: int,
    space_id: int,
    dashboard_ids: Sequence[int],
    execute: bool = False,
) -> dict[str, Any]:
    app = positive_id(app_id, "app_id")
    space = positive_id(space_id, "space_id")
    selected = _dashboard_ids(dashboard_ids)
    if execute:
        with WRITE_LOCK:
            return _delete_dashboards(client, app, space, selected, send=True)
    return _delete_dashboards(client, app, space, selected, send=False)


def _delete_dashboards(
    client: Any,
    app: int,
    space: int,
    dashboard_ids: list[int],
    *,
    send: bool,
) -> dict[str, Any]:
    _tree, objects = read_tree(client, app)
    preimages = [find_object(objects, "dashboard", item) for item in dashboard_ids]
    details = [read_detail(client, app, space, item) for item in dashboard_ids]
    ownership = []
    for preimage, selected_detail in zip(preimages, details):
        if preimage.space_id != space:
            raise InputValidationError(
                f"actual value: {space}; allowed value: current parent id {preimage.space_id}",
                field="space_id",
                next_action="Use the exact current parent coordinates from the latest Kanban tree and run dry-run again.",
            )
        ownership.append(
            require_owned(client, app, preimage, detail=selected_detail)
        )
    report_count = sum(len(report_list(item)) for item in details)
    note_count = sum(len(detail_notes(item)) for item in details)
    if report_count:
        raise InputValidationError(
            f"actual value: {report_count} embedded reports; allowed value: zero embedded reports before dashboard deletion",
            field="dashboard_ids",
            next_action="Preserve the dashboard and ask the report owners to detach its report content; the SDK will not delete a dashboard containing multidimensional reports.",
        )
    inputs = {"app_id": app, "dashboard_ids": dashboard_ids, "space_id": space}
    cascade = {
        "kind": "delete_embedded_notes",
        "descendant_count": note_count,
        "notes_deleted": note_count,
        "reports_deleted": 0,
        "warning": f"Deleting these {len(dashboard_ids)} dashboards also permanently deletes {note_count} embedded notes; no multidimensional report is present or deleted.",
    }
    preview = mutation_preview(
        client._preview_mutation(DASHBOARD_DELETE, inputs),
        target={
            "kind": "dashboard_batch",
            "dashboards": [
                {**item.public(), "ownership": decision.public()}
                for item, decision in zip(preimages, ownership)
            ],
        },
        preimage={"dashboards": [item.public() for item in preimages]},
        cascade=cascade,
        impact=cascade["warning"],
        reads_performed=1 + len(details),
    )
    if not send:
        return preview
    mutation = client._execute_mutation(DASHBOARD_DELETE, inputs)
    _tree, remaining = read_tree(client, app)
    remaining_ids = {
        item.object_id for item in remaining if item.kind == "dashboard"
    }
    if remaining_ids & set(dashboard_ids):
        raise MutationReadbackError(
            "one or more dashboards still exist after delete acknowledgement",
            next_action="Read the exact dashboard IDs and inspect references before another explicit delete.",
        )
    return completed(
        preview,
        mutation,
        {
            "kind": "dashboard_batch",
            "deleted_dashboard_ids": dashboard_ids,
            "ownership": [item.public() for item in ownership],
        },
        status="deleted",
    )


def _dashboard_ids(value: Any) -> list[int]:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes))
        or not 1 <= len(value) <= 100
    ):
        raise InputValidationError(
            f"actual value: {actual_value(value)}; allowed value: 1 through 100 dashboard IDs",
            field="dashboard_ids",
            next_action="Provide a non-empty bounded list from the latest Kanban tree and run dry-run again.",
        )
    selected = [positive_id(item, "dashboard_ids") for item in value]
    if len(selected) != len(set(selected)):
        raise InputValidationError(
            f"actual value: {actual_value(selected)}; allowed value: unique dashboard IDs",
            field="dashboard_ids",
            next_action="Remove duplicate dashboard IDs and run dry-run again.",
        )
    return selected


__all__ = ["delete_dashboard", "delete_dashboards"]
