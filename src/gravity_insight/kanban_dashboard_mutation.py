"""Marker-governed Kanban dashboard lifecycle and move mutations."""

from __future__ import annotations

from typing import Any

from .actionable_error_values import actual_value

from .errors import InputValidationError, MutationReadbackError
from .kanban_mutation_contracts import (
    DASHBOARD_COPY,
    DASHBOARD_CREATE,
    DASHBOARD_FOLDER_MOVE,
    DASHBOARD_MOVE,
    DASHBOARD_RENAME,
)
from .kanban_dashboard_delete_mutation import delete_dashboard, delete_dashboards
from .kanban_mutation_support import (
    WRITE_LOCK,
    completed,
    create_preflight,
    detail_notes,
    find_object,
    folder_ids_equal,
    idempotent,
    marked_name,
    marker_from_text,
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
        with MutationReadbackError.after_dispatch(mutation, marker):
            _tree, after = read_tree(client, app)
            created = create_preflight(after, "dashboard", marker, wire_name)
            if (
                created is None
                or created.space_id != space
                or not folder_ids_equal(created.folder_id, folder)
            ):
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
    ownership = require_owned(client, app, preimage)
    wire_name = preserve_marker(name, preimage.name)
    inputs = {
        "app_id": app,
        "id": dashboard_id,
        "name": wire_name,
        "space_id": space,
    }
    preview = mutation_preview(
        client._preview_mutation(DASHBOARD_RENAME, inputs),
        target={
            **preimage.public(),
            "new_name": wire_name,
            "ownership": ownership.public(),
        },
        preimage=preimage.public(),
        impact="Rename this exact dashboard without changing layout or embedded content.",
        reads_performed=1,
    )
    if not send:
        return preview
    mutation = client._execute_mutation(DASHBOARD_RENAME, inputs)
    recovery_marker = marker_from_text(preimage.name)
    with MutationReadbackError.after_dispatch(mutation, recovery_marker):
        _tree, after = read_tree(client, app)
        updated = find_object(after, "dashboard", dashboard_id)
        if updated.name != wire_name or updated.space_id != space:
            raise MutationReadbackError(
                "dashboard rename did not round-trip",
                next_action="Read the exact dashboard coordinates before another rename.",
            )
    return completed(
        preview,
        mutation,
        {**updated.public(), "ownership": ownership.public()},
        status="updated",
    )


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
    ownership = require_owned(client, app, preimage)
    _same_parent(preimage.space_id, space, "space_id")
    _validate_destination(objects, space, folder)
    if folder:
        require_owned(client, app, find_object(objects, "folder", folder))
    inputs = {
        "app_id": app,
        "dashboard_id": dashboard_id,
        "folder_id": folder,
        "space_id": space,
    }
    preview = mutation_preview(
        client._preview_mutation(DASHBOARD_FOLDER_MOVE, inputs),
        target={
            **preimage.public(),
            "to_folder_id": folder,
            "ownership": ownership.public(),
        },
        preimage=preimage.public(),
        impact="Move this exact SDK-marked dashboard within its current space; embedded notes remain attached.",
        reads_performed=1,
    )
    if not send:
        return preview
    mutation = client._execute_mutation(DASHBOARD_FOLDER_MOVE, inputs)
    recovery_marker = marker_from_text(preimage.name)
    with MutationReadbackError.after_dispatch(mutation, recovery_marker):
        _tree, after = read_tree(client, app)
        moved = find_object(after, "dashboard", dashboard_id)
        if moved.space_id != space or not folder_ids_equal(moved.folder_id, folder):
            raise MutationReadbackError(
                "dashboard folder move did not round-trip to the requested destination",
                next_action="Read the exact dashboard tree coordinates before another move.",
            )
    return completed(
        preview,
        mutation,
        {**moved.public(), "ownership": ownership.public()},
        status="moved",
    )


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
    ownership = require_owned(client, app, preimage)
    _same_parent(preimage.space_id, source, "from_space_id")
    _validate_destination(objects, destination, folder)
    _require_destination_authority(client, app, objects, destination, folder)
    inputs: dict[str, Any] = {
        "app_id": app,
        "dashboards": [{"dashboard_id": dashboard_id, "form_space_id": source}],
        "to_space_id": destination,
    }
    if folder:
        inputs["to_folder_id"] = folder
    preview = mutation_preview(
        client._preview_mutation(DASHBOARD_MOVE, inputs),
        target={
            **preimage.public(),
            "to_space_id": destination,
            "to_folder_id": folder,
            "ownership": ownership.public(),
        },
        preimage=preimage.public(),
        impact="Move this exact SDK-marked dashboard to the requested space/folder; embedded notes remain attached.",
        reads_performed=1,
    )
    if not send:
        return preview
    mutation = client._execute_mutation(DASHBOARD_MOVE, inputs)
    recovery_marker = marker_from_text(preimage.name)
    with MutationReadbackError.after_dispatch(mutation, recovery_marker):
        _tree, after = read_tree(client, app)
        moved = find_object(after, "dashboard", dashboard_id)
        if moved.space_id != destination or not folder_ids_equal(
            moved.folder_id, folder
        ):
            raise MutationReadbackError(
                "dashboard move did not round-trip to the requested destination",
                next_action="Read the source and destination spaces before another move.",
            )
    return completed(
        preview,
        mutation,
        {**moved.public(), "ownership": ownership.public()},
        status="moved",
    )


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
    ownership = require_owned(client, app, preimage, detail=detail)
    _require_destination_authority(client, app, objects, destination, folder)
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
        target={
            "kind": "dashboard",
            "name": wire_name,
            "marker": marker,
            "space_id": destination,
            "folder_id": folder,
            "source_ownership": ownership.public(),
        },
        preimage=preimage.public(),
        impact=f"Copy this empty dashboard and its {len(detail_notes(detail))} embedded notes; no report, material, or asset is created or modified.",
        reads_performed=2,
    )
    if not send:
        return preview
    if existing is not None:
        return idempotent(DASHBOARD_COPY, existing)
    mutation = client._execute_mutation(DASHBOARD_COPY, inputs)
    with MutationReadbackError.after_dispatch(mutation, marker):
        _tree, after = read_tree(client, app)
        created = create_preflight(after, "dashboard", marker, wire_name)
        if (
            created is None
            or created.space_id != destination
            or not folder_ids_equal(created.folder_id, folder)
        ):
            raise MutationReadbackError(
                "copied dashboard did not round-trip at the requested destination",
                next_action="Inspect this SDK marker before deciding whether another copy is safe.",
            )
    return completed(preview, mutation, created.public(), status="copied")


def _validate_destination(objects: list[Any], space_id: int, folder_id: int) -> None:
    find_object(objects, "space", space_id)
    if folder_id:
        folder = find_object(objects, "folder", folder_id)
        _same_parent(folder.space_id, space_id, "folder_id")


def _require_destination_authority(
    client: Any,
    app: int,
    objects: list[Any],
    space_id: int,
    folder_id: int,
) -> None:
    require_owned(client, app, find_object(objects, "space", space_id))
    if folder_id:
        require_owned(client, app, find_object(objects, "folder", folder_id))


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
