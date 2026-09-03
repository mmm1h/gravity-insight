"""Marker-governed Kanban folder mutations."""

from __future__ import annotations

from typing import Any

from .errors import InputValidationError, MutationReadbackError
from .kanban_mutation_contracts import (
    FOLDER_CREATE,
    FOLDER_DELETE,
    FOLDER_MOVE,
    FOLDER_UPDATE,
)
from .kanban_mutation_support import (
    WRITE_LOCK,
    completed,
    create_preflight,
    descendants,
    find_object,
    idempotent,
    marked_name,
    marker_from_text,
    mutation_preview,
    positive_id,
    preserve_marker,
    read_tree,
    require_owned,
)


def create_folder(
    client: Any,
    *,
    app_id: int,
    space_id: int,
    name: str,
    idempotency_key: str | None = None,
    execute: bool = False,
) -> dict[str, Any]:
    app, space = positive_id(app_id, "app_id"), positive_id(space_id, "space_id")
    wire_name, marker = marked_name(
        "kanban_folder", name, {"app_id": app, "space_id": space, "name": name},
        idempotency_key=idempotency_key,
    )
    inputs = {"app_id": app, "space_id": space, "name": wire_name}
    preview = mutation_preview(
        client._preview_mutation(FOLDER_CREATE, inputs),
        target={"kind": "folder", "app_id": app, "space_id": space, "name": wire_name, "marker": marker},
        impact="Create one empty folder inside the exact Kanban space.",
    )
    if not execute:
        return preview
    with WRITE_LOCK:
        _tree, before = read_tree(client, app)
        find_object(before, "space", space)
        existing = create_preflight(before, "folder", marker, wire_name)
        if existing is not None:
            return idempotent(FOLDER_CREATE, existing)
        mutation = client._execute_mutation(FOLDER_CREATE, inputs)
        with MutationReadbackError.after_dispatch(mutation, marker):
            _tree, after = read_tree(client, app)
            created = create_preflight(after, "folder", marker, wire_name)
            if created is None or created.space_id != space:
                raise MutationReadbackError(
                    "created Kanban folder did not round-trip under the requested space",
                    next_action="Inspect this SDK marker and its current parent before another create.",
                )
        return completed(preview, mutation, created.public(), status="created")


def rename_folder(
    client: Any,
    *,
    app_id: int,
    space_id: int,
    folder_id: int,
    name: str,
    execute: bool = False,
) -> dict[str, Any]:
    app = positive_id(app_id, "app_id")
    space = positive_id(space_id, "space_id")
    selected_id = positive_id(folder_id, "folder_id")
    if execute:
        with WRITE_LOCK:
            return _rename_folder(client, app, space, selected_id, name, send=True)
    return _rename_folder(client, app, space, selected_id, name, send=False)


def _rename_folder(
    client: Any, app: int, space: int, folder_id: int, name: str, *, send: bool
) -> dict[str, Any]:
    _tree, objects = read_tree(client, app)
    preimage = find_object(objects, "folder", folder_id)
    _same_space(preimage.space_id, space, "space_id")
    ownership = require_owned(client, app, preimage)
    wire_name = preserve_marker(name, preimage.name)
    inputs = {"app_id": app, "id": folder_id, "name": wire_name, "space_id": space}
    preview = mutation_preview(
        client._preview_mutation(FOLDER_UPDATE, inputs),
        target={
            **preimage.public(),
            "new_name": wire_name,
            "ownership": ownership.public(),
        },
        preimage=preimage.public(),
        impact="Rename this exact folder without changing its dashboard membership.",
        reads_performed=1,
    )
    if not send:
        return preview
    mutation = client._execute_mutation(FOLDER_UPDATE, inputs)
    recovery_marker = marker_from_text(preimage.name)
    with MutationReadbackError.after_dispatch(mutation, recovery_marker):
        _tree, after = read_tree(client, app)
        updated = find_object(after, "folder", folder_id)
        if updated.name != wire_name or updated.space_id != space:
            raise MutationReadbackError(
                "Kanban folder rename did not round-trip",
                next_action="Read the exact folder and parent space before another write.",
            )
    return completed(
        preview,
        mutation,
        {**updated.public(), "ownership": ownership.public()},
        status="updated",
    )


def move_folder(
    client: Any,
    *,
    app_id: int,
    folder_id: int,
    from_space_id: int,
    to_space_id: int,
    execute: bool = False,
) -> dict[str, Any]:
    app = positive_id(app_id, "app_id")
    selected_id = positive_id(folder_id, "folder_id")
    source = positive_id(from_space_id, "from_space_id")
    destination = positive_id(to_space_id, "to_space_id")
    if execute:
        with WRITE_LOCK:
            return _move_folder(client, app, selected_id, source, destination, send=True)
    return _move_folder(client, app, selected_id, source, destination, send=False)


def _move_folder(
    client: Any, app: int, folder_id: int, source: int, destination: int, *, send: bool
) -> dict[str, Any]:
    _tree, objects = read_tree(client, app)
    preimage = find_object(objects, "folder", folder_id)
    ownership = require_owned(client, app, preimage)
    _same_space(preimage.space_id, source, "from_space_id")
    destination_space = find_object(objects, "space", destination)
    require_owned(client, app, destination_space)
    children = descendants(objects, preimage)
    inputs = {
        "app_id": app,
        "form_folder_id": folder_id,
        "form_space_id": source,
        "to_space_id": destination,
    }
    cascade = {
        "kind": "move_with_descendants",
        "descendant_count": len(children),
        "dashboards_moved": len(children),
        "warning": f"Moving this folder also moves {len(children)} contained dashboards to space {destination}.",
    }
    preview = mutation_preview(
        client._preview_mutation(FOLDER_MOVE, inputs),
        target={
            **preimage.public(),
            "to_space_id": destination,
            "ownership": ownership.public(),
        },
        preimage=preimage.public(),
        cascade=cascade,
        impact=cascade["warning"],
        reads_performed=1,
    )
    if not send:
        return preview
    mutation = client._execute_mutation(FOLDER_MOVE, inputs)
    recovery_marker = marker_from_text(preimage.name)
    with MutationReadbackError.after_dispatch(mutation, recovery_marker):
        _tree, after = read_tree(client, app)
        moved = find_object(after, "folder", folder_id)
        moved_children = descendants(after, moved)
        if moved.space_id != destination or {item.object_id for item in moved_children} != {item.object_id for item in children}:
            raise MutationReadbackError(
                "folder move did not preserve the reviewed descendants at the destination",
                next_action="Read both spaces and inspect the folder/dashboard identities before another move.",
            )
    return completed(
        preview,
        mutation,
        {**moved.public(), "ownership": ownership.public()},
        status="moved",
    )


def delete_folder(
    client: Any,
    *,
    app_id: int,
    space_id: int,
    folder_id: int,
    execute: bool = False,
) -> dict[str, Any]:
    app = positive_id(app_id, "app_id")
    space = positive_id(space_id, "space_id")
    selected_id = positive_id(folder_id, "folder_id")
    if execute:
        with WRITE_LOCK:
            return _delete_folder(client, app, space, selected_id, send=True)
    return _delete_folder(client, app, space, selected_id, send=False)


def _delete_folder(
    client: Any, app: int, space: int, folder_id: int, *, send: bool
) -> dict[str, Any]:
    _tree, objects = read_tree(client, app)
    preimage = find_object(objects, "folder", folder_id)
    ownership = require_owned(client, app, preimage)
    _same_space(preimage.space_id, space, "space_id")
    dashboards = descendants(objects, preimage)
    inputs = {"app_id": app, "folder_id": folder_id, "space_id": space}
    cascade = {
        "kind": "relocate_not_cascade_delete",
        "descendant_count": len(dashboards),
        "folders_removed": 1,
        "dashboards_moved": len(dashboards),
        "dashboards_deleted": 0,
        "warning": f"Deleting this folder removes the folder and moves {len(dashboards)} dashboards to Ungrouped/Shared with me; it does not delete those dashboards.",
    }
    preview = mutation_preview(
        client._preview_mutation(FOLDER_DELETE, inputs),
        target={
            **preimage.public(),
            "marker": marker_from_text(preimage.name),
            "ownership": ownership.public(),
        },
        preimage=preimage.public(),
        cascade=cascade,
        impact=cascade["warning"],
        reads_performed=1,
    )
    if not send:
        return preview
    mutation = client._execute_mutation(FOLDER_DELETE, inputs)
    recovery_marker = marker_from_text(preimage.name)
    with MutationReadbackError.after_dispatch(mutation, recovery_marker):
        _tree, remaining = read_tree(client, app)
        if any(item.kind == "folder" and item.object_id == folder_id for item in remaining):
            raise MutationReadbackError(
                "Kanban folder still exists after delete acknowledgement",
                next_action="Read the exact marked folder before another explicit delete.",
            )
        remaining_dashboards = {item.object_id: item for item in remaining if item.kind == "dashboard"}
        if any(item.object_id not in remaining_dashboards for item in dashboards):
            raise MutationReadbackError(
                "folder deletion did not preserve every dashboard promised by the relocation contract",
                next_action="Stop writes and inspect the affected dashboards; do not retry the parent delete.",
            )
    return completed(
        preview,
        mutation,
        {
            **preimage.public(),
            "deleted": True,
            "relocated_dashboard_ids": [item.object_id for item in dashboards],
            "ownership": ownership.public(),
        },
        status="deleted",
    )


def _same_space(actual: int, expected: int, field: str) -> None:
    if actual != expected:
        raise InputValidationError(
            f"actual value: {actual}; allowed value: current parent space {expected}",
            field=field,
            next_action="Use the exact parent coordinates from the latest Kanban tree and run dry-run again.",
        )


__all__ = ["create_folder", "delete_folder", "move_folder", "rename_folder"]
