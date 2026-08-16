"""Marker-governed Kanban dashboard lifecycle and move mutations."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from .actionable_error_values import actual_value

from .errors import InputValidationError, MutationReadbackError
from .kanban_mutation_contracts import (
    DASHBOARD_COPY,
    DASHBOARD_CREATE,
    DASHBOARD_DELETE,
    DASHBOARD_FOLDER_MOVE,
    DASHBOARD_MOVE,
    DASHBOARD_RENAME,
)
from .kanban_mutation_support import (
    WRITE_LOCK,
    completed,
    create_preflight,
    detail_notes,
    find_object,
    idempotent,
    marked_name,
    mutation_preview,
    nonnegative_id,
    positive_id,
    preserve_marker,
    read_detail,
    read_tree,
    report_list,
    require_owned,
)


def create_dashboard(
    client: Any,
    *,
    app_id: int,
    space_id: int,
    folder_id: int,
    name: str,
    idempotency_key: str | None = None,
    execute: bool = False,
) -> dict[str, Any]:
    app = positive_id(app_id, "app_id")
    space = positive_id(space_id, "space_id")
    folder = nonnegative_id(folder_id, "folder_id")
    wire_name, marker = marked_name(
        "kanban_dashboard",
        name,
        {"app_id": app, "space_id": space, "folder_id": folder, "name": name},
        idempotency_key=idempotency_key,
    )
    inputs = {
        "app_id": app,
        "space_id": space,
        "folder_id": folder,
        "name": wire_name,
    }
    preview = mutation_preview(
        client._preview_mutation(DASHBOARD_CREATE, inputs),
        target={
            "kind": "dashboard",
            "app_id": app,
            "space_id": space,
            "folder_id": folder,
            "name": wire_name,
            "marker": marker,
        },
        impact="Create one empty persistent dashboard; no multidimensional report, material, or asset is created.",
    )
    if not execute:
        return preview
    with WRITE_LOCK:
        _tree, before = read_tree(client, app)
        _validate_destination(before, space, folder)
        existing = create_preflight(before, "dashboard", marker, wire_name)
        if existing is not None:
            return idempotent(DASHBOARD_CREATE, existing)
        mutation = client._execute_mutation(DASHBOARD_CREATE, inputs)
        _tree, after = read_tree(client, app)
        created = create_preflight(after, "dashboard", marker, wire_name)
        if created is None or created.space_id != space or created.folder_id != folder:
            raise MutationReadbackError(
                "created dashboard did not round-trip under the requested parent",
                next_action="Inspect this SDK marker and its current space/folder before another create.",
            )
        return completed(preview, mutation, created.public(), status="created")


def rename_dashboard(
    client: Any,
    *,
    app_id: int,
    space_id: int,
    dashboard_id: int,
    name: str,
    execute: bool = False,
) -> dict[str, Any]:
    app = positive_id(app_id, "app_id")
    space = positive_id(space_id, "space_id")
    selected_id = positive_id(dashboard_id, "dashboard_id")
    if execute:
        with WRITE_LOCK:
            return _rename_dashboard(client, app, space, selected_id, name, send=True)
    return _rename_dashboard(client, app, space, selected_id, name, send=False)


def _rename_dashboard(
    client: Any, app: int, space: int, dashboard_id: int, name: str, *, send: bool
) -> dict[str, Any]:
    _tree, objects = read_tree(client, app)
    preimage = find_object(objects, "dashboard", dashboard_id)
    _same_parent(preimage.space_id, space, "space_id")
    wire_name = preserve_marker(name, preimage.name)
    inputs = {
        "app_id": app,
        "id": dashboard_id,
        "name": wire_name,
        "space_id": space,
    }
    preview = mutation_preview(
        client._preview_mutation(DASHBOARD_RENAME, inputs),
        target={**preimage.public(), "new_name": wire_name},
        preimage=preimage.public(),
        impact="Rename this exact dashboard without changing layout or embedded content.",
        reads_performed=1,
    )
    if not send:
        return preview
    mutation = client._execute_mutation(DASHBOARD_RENAME, inputs)
    _tree, after = read_tree(client, app)
    updated = find_object(after, "dashboard", dashboard_id)
    if updated.name != wire_name or updated.space_id != space:
        raise MutationReadbackError(
            "dashboard rename did not round-trip",
            next_action="Read the exact dashboard coordinates before another rename.",
        )
    return completed(preview, mutation, updated.public(), status="updated")


def move_dashboard_to_folder(
    client: Any,
    *,
    app_id: int,
    space_id: int,
    dashboard_id: int,
    folder_id: int,
    execute: bool = False,
) -> dict[str, Any]:
    app = positive_id(app_id, "app_id")
    space = positive_id(space_id, "space_id")
    selected_id = positive_id(dashboard_id, "dashboard_id")
    folder = nonnegative_id(folder_id, "folder_id")
    if execute:
        with WRITE_LOCK:
            return _move_to_folder(client, app, space, selected_id, folder, send=True)
    return _move_to_folder(client, app, space, selected_id, folder, send=False)


def _move_to_folder(
    client: Any, app: int, space: int, dashboard_id: int, folder: int, *, send: bool
) -> dict[str, Any]:
    _tree, objects = read_tree(client, app)
    preimage = find_object(objects, "dashboard", dashboard_id)
    require_owned(preimage)
    _same_parent(preimage.space_id, space, "space_id")
    _validate_destination(objects, space, folder)
    inputs = {
        "app_id": app,
        "dashboard_id": dashboard_id,
        "folder_id": folder,
        "space_id": space,
    }
    preview = mutation_preview(
        client._preview_mutation(DASHBOARD_FOLDER_MOVE, inputs),
        target={**preimage.public(), "to_folder_id": folder},
        preimage=preimage.public(),
        impact="Move this exact SDK-marked dashboard within its current space; embedded notes remain attached.",
        reads_performed=1,
    )
    if not send:
        return preview
    mutation = client._execute_mutation(DASHBOARD_FOLDER_MOVE, inputs)
    _tree, after = read_tree(client, app)
    moved = find_object(after, "dashboard", dashboard_id)
    folder_matches = (
        moved.folder_id == folder
        if folder
        else preimage.folder_id is None or moved.folder_id != preimage.folder_id
    )
    if moved.space_id != space or not folder_matches:
        raise MutationReadbackError(
            "dashboard folder move did not round-trip to the requested destination",
            next_action="Read the exact dashboard tree coordinates before another move.",
        )
    return completed(preview, mutation, moved.public(), status="moved")


def move_dashboard(
    client: Any,
    *,
    app_id: int,
    dashboard_id: int,
    from_space_id: int,
    to_space_id: int,
    to_folder_id: int = 0,
    execute: bool = False,
) -> dict[str, Any]:
    app = positive_id(app_id, "app_id")
    selected_id = positive_id(dashboard_id, "dashboard_id")
    source = positive_id(from_space_id, "from_space_id")
    destination = positive_id(to_space_id, "to_space_id")
    folder = nonnegative_id(to_folder_id, "to_folder_id")
    if execute:
        with WRITE_LOCK:
            return _move_dashboard(client, app, selected_id, source, destination, folder, send=True)
    return _move_dashboard(client, app, selected_id, source, destination, folder, send=False)


def _move_dashboard(
    client: Any,
    app: int,
    dashboard_id: int,
    source: int,
    destination: int,
    folder: int,
    *,
    send: bool,
) -> dict[str, Any]:
    _tree, objects = read_tree(client, app)
    preimage = find_object(objects, "dashboard", dashboard_id)
    require_owned(preimage)
    _same_parent(preimage.space_id, source, "from_space_id")
    _validate_destination(objects, destination, folder)
    inputs: dict[str, Any] = {
        "app_id": app,
        "dashboards": [{"dashboard_id": dashboard_id, "form_space_id": source}],
        "to_space_id": destination,
    }
    if folder:
        inputs["to_folder_id"] = folder
    preview = mutation_preview(
        client._preview_mutation(DASHBOARD_MOVE, inputs),
        target={**preimage.public(), "to_space_id": destination, "to_folder_id": folder},
        preimage=preimage.public(),
        impact="Move this exact SDK-marked dashboard to the requested space/folder; embedded notes remain attached.",
        reads_performed=1,
    )
    if not send:
        return preview
    mutation = client._execute_mutation(DASHBOARD_MOVE, inputs)
    _tree, after = read_tree(client, app)
    moved = find_object(after, "dashboard", dashboard_id)
    folder_matches = (
        moved.folder_id == folder
        if folder
        else destination != source
        or preimage.folder_id is None
        or moved.folder_id != preimage.folder_id
    )
    if moved.space_id != destination or not folder_matches:
        raise MutationReadbackError(
            "dashboard move did not round-trip to the requested destination",
            next_action="Read the source and destination spaces before another move.",
        )
    return completed(preview, mutation, moved.public(), status="moved")


def copy_dashboard(
    client: Any,
    *,
    app_id: int,
    dashboard_id: int,
    from_space_id: int,
    to_space_id: int,
    to_folder_id: int,
    name: str,
    idempotency_key: str | None = None,
    execute: bool = False,
) -> dict[str, Any]:
    app = positive_id(app_id, "app_id")
    selected_id = positive_id(dashboard_id, "dashboard_id")
    source = positive_id(from_space_id, "from_space_id")
    destination = positive_id(to_space_id, "to_space_id")
    folder = nonnegative_id(to_folder_id, "to_folder_id")
    if execute:
        with WRITE_LOCK:
            return _copy_dashboard(
                client, app, selected_id, source, destination, folder, name,
                idempotency_key=idempotency_key, send=True,
            )
    return _copy_dashboard(
        client, app, selected_id, source, destination, folder, name,
        idempotency_key=idempotency_key, send=False,
    )


def _copy_dashboard(
    client: Any,
    app: int,
    dashboard_id: int,
    source: int,
    destination: int,
    folder: int,
    name: str,
    *,
    idempotency_key: str | None,
    send: bool,
) -> dict[str, Any]:
    _tree, objects = read_tree(client, app)
    preimage = find_object(objects, "dashboard", dashboard_id)
    _same_parent(preimage.space_id, source, "from_space_id")
    _validate_destination(objects, destination, folder)
    detail = read_detail(client, app, source, dashboard_id)
    reports = report_list(detail)
    if reports:
        raise InputValidationError(
            f"actual value: {len(reports)} embedded reports; allowed value: an empty dashboard for SDK copy",
            field="dashboard_id",
            next_action="Choose an empty dashboard or remove report associations with their owner; the SDK will not copy multidimensional report content.",
        )
    wire_name, marker = marked_name(
        "kanban_dashboard_copy",
        name,
        {"app_id": app, "source_dashboard_id": dashboard_id, "to_space_id": destination, "to_folder_id": folder, "name": name},
        idempotency_key=idempotency_key,
    )
    inputs: dict[str, Any] = {
        "app_id": app,
        "form_space_id": source,
        "id": dashboard_id,
        "name": wire_name,
        "to_space_id": destination,
    }
    if folder:
        inputs["to_folder_id"] = folder
    existing = create_preflight(objects, "dashboard", marker, wire_name)
    preview = mutation_preview(
        client._preview_mutation(DASHBOARD_COPY, inputs),
        target={"kind": "dashboard", "name": wire_name, "marker": marker, "space_id": destination, "folder_id": folder},
        preimage=preimage.public(),
        impact=f"Copy this empty dashboard and its {len(detail_notes(detail))} embedded notes; no report, material, or asset is created or modified.",
        reads_performed=2,
    )
    if not send:
        return preview
    if existing is not None:
        return idempotent(DASHBOARD_COPY, existing)
    mutation = client._execute_mutation(DASHBOARD_COPY, inputs)
    _tree, after = read_tree(client, app)
    created = create_preflight(after, "dashboard", marker, wire_name)
    if created is None or created.space_id != destination or created.folder_id != (folder or None):
        raise MutationReadbackError(
            "copied dashboard did not round-trip at the requested destination",
            next_action="Inspect this SDK marker before deciding whether another copy is safe.",
        )
    return completed(preview, mutation, created.public(), status="copied")


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
    client: Any, app: int, space: int, dashboard_ids: list[int], *, send: bool
) -> dict[str, Any]:
    _tree, objects = read_tree(client, app)
    preimages = [find_object(objects, "dashboard", item) for item in dashboard_ids]
    for preimage in preimages:
        require_owned(preimage)
        _same_parent(preimage.space_id, space, "space_id")
    details = [read_detail(client, app, space, item) for item in dashboard_ids]
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
        target={"kind": "dashboard_batch", "dashboards": [item.public() for item in preimages]},
        preimage={"dashboards": [item.public() for item in preimages]},
        cascade=cascade,
        impact=cascade["warning"],
        reads_performed=1 + len(details),
    )
    if not send:
        return preview
    mutation = client._execute_mutation(DASHBOARD_DELETE, inputs)
    _tree, remaining = read_tree(client, app)
    remaining_ids = {item.object_id for item in remaining if item.kind == "dashboard"}
    if remaining_ids & set(dashboard_ids):
        raise MutationReadbackError(
            "one or more dashboards still exist after delete acknowledgement",
            next_action="Read the exact marked dashboard IDs and inspect references before another explicit delete.",
        )
    return completed(
        preview,
        mutation,
        {"kind": "dashboard_batch", "deleted_dashboard_ids": dashboard_ids},
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
            next_action="Use a bounded dashboard ID list from the latest Kanban tree and run dry-run again.",
        )
    selected = [positive_id(item, "dashboard_ids") for item in value]
    if len(selected) != len(set(selected)):
        raise InputValidationError(
            f"actual value: {actual_value(selected)}; allowed value: unique dashboard IDs",
            field="dashboard_ids",
            next_action="Remove duplicate dashboard IDs and run dry-run again.",
        )
    return selected


def _validate_destination(objects: list[Any], space_id: int, folder_id: int) -> None:
    find_object(objects, "space", space_id)
    if folder_id:
        folder = find_object(objects, "folder", folder_id)
        _same_parent(folder.space_id, space_id, "folder_id")


def _same_parent(actual: int, expected: int, field: str) -> None:
    if actual != expected:
        raise InputValidationError(
            f"actual value: {expected}; allowed value: current parent id {actual}",
            field=field,
            next_action="Use the exact current parent coordinates from the latest Kanban tree and run dry-run again.",
        )


__all__ = [
    "copy_dashboard",
    "create_dashboard",
    "delete_dashboard",
    "delete_dashboards",
    "move_dashboard",
    "move_dashboard_to_folder",
    "rename_dashboard",
]
