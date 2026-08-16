"""Marker-governed Kanban space mutations."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .errors import MutationReadbackError
from .kanban_mutation_contracts import (
    SPACE_CREATE,
    SPACE_DELETE,
    SPACE_MEMBERS,
    SPACE_TRANSFER,
    SPACE_UPDATE,
)
from .kanban_mutation_support import (
    WRITE_LOCK,
    completed,
    create_preflight,
    descendants,
    find_object,
    idempotent,
    marked_name,
    mutation_preview,
    positive_id,
    preserve_marker,
    read_tree,
    require_owned,
)


def create_space(
    client: Any,
    *,
    app_id: int,
    name: str,
    idempotency_key: str | None = None,
    execute: bool = False,
) -> dict[str, Any]:
    app = positive_id(app_id, "app_id")
    wire_name, marker = marked_name(
        "kanban_space", name, {"app_id": app, "name": name},
        idempotency_key=idempotency_key,
    )
    inputs = {"app_id": app, "name": wire_name}
    preview = mutation_preview(
        client._preview_mutation(SPACE_CREATE, inputs),
        target={"kind": "space", "app_id": app, "name": wire_name, "marker": marker},
        impact="Create one persistent Kanban space; no folder or dashboard is created implicitly.",
    )
    if not execute:
        return preview
    with WRITE_LOCK:
        _tree, before = read_tree(client, app)
        existing = create_preflight(before, "space", marker, wire_name)
        if existing is not None:
            return idempotent(SPACE_CREATE, existing)
        mutation = client._execute_mutation(SPACE_CREATE, inputs)
        _tree, after = read_tree(client, app)
        created = create_preflight(after, "space", marker, wire_name)
        if created is None:
            raise MutationReadbackError(
                "created Kanban space did not round-trip through the tree",
                next_action="Inspect this SDK marker before deciding whether another create is safe.",
            )
        return completed(preview, mutation, created.public(), status="created")


def rename_space(
    client: Any,
    *,
    app_id: int,
    space_id: int,
    name: str,
    execute: bool = False,
) -> dict[str, Any]:
    app, selected_id = positive_id(app_id, "app_id"), positive_id(space_id, "space_id")
    if execute:
        with WRITE_LOCK:
            return _rename_space(client, app, selected_id, name, send=True)
    return _rename_space(client, app, selected_id, name, send=False)


def _rename_space(
    client: Any, app: int, space_id: int, name: str, *, send: bool
) -> dict[str, Any]:
    _tree, objects = read_tree(client, app)
    preimage = find_object(objects, "space", space_id)
    wire_name = preserve_marker(name, preimage.name)
    inputs = {"app_id": app, "id": space_id, "name": wire_name}
    preview = mutation_preview(
        client._preview_mutation(SPACE_UPDATE, inputs),
        target={**preimage.public(), "new_name": wire_name},
        preimage=preimage.public(),
        impact="Rename this exact Kanban space without changing its descendants or ownership.",
        reads_performed=1,
    )
    if not send:
        return preview
    mutation = client._execute_mutation(SPACE_UPDATE, inputs)
    _tree, after = read_tree(client, app)
    updated = find_object(after, "space", space_id)
    if updated.name != wire_name:
        raise MutationReadbackError(
            "Kanban space rename did not round-trip",
            next_action="Read the exact space and review its current name before another write.",
        )
    return completed(preview, mutation, updated.public(), status="updated")


def delete_space(
    client: Any,
    *,
    app_id: int,
    space_id: int,
    execute: bool = False,
) -> dict[str, Any]:
    app, selected_id = positive_id(app_id, "app_id"), positive_id(space_id, "space_id")
    if execute:
        with WRITE_LOCK:
            return _delete_space(client, app, selected_id, send=True)
    return _delete_space(client, app, selected_id, send=False)


def _delete_space(client: Any, app: int, space_id: int, *, send: bool) -> dict[str, Any]:
    _tree, objects = read_tree(client, app)
    preimage = find_object(objects, "space", space_id)
    marker = require_owned(preimage)
    affected = descendants(objects, preimage)
    folders = [item for item in affected if item.kind == "folder"]
    dashboards = [item for item in affected if item.kind == "dashboard"]
    inputs = {"app_id": app, "space_id": space_id}
    cascade = {
        "kind": "relocate_not_cascade_delete",
        "descendant_count": len(affected),
        "folders_removed": len(folders),
        "dashboards_moved": len(dashboards),
        "dashboards_deleted": 0,
        "warning": f"Deleting this space removes {len(folders)} folder containers and moves {len(dashboards)} dashboards to each creator's My Dashboard/Ungrouped area; it does not delete those dashboards.",
    }
    preview = mutation_preview(
        client._preview_mutation(SPACE_DELETE, inputs),
        target={**preimage.public(), "marker": marker},
        preimage=preimage.public(),
        cascade=cascade,
        impact=cascade["warning"],
        reads_performed=1,
    )
    if not send:
        return preview
    mutation = client._execute_mutation(SPACE_DELETE, inputs)
    _tree, remaining = read_tree(client, app)
    if any(item.kind == "space" and item.object_id == space_id for item in remaining):
        raise MutationReadbackError(
            "Kanban space still exists after delete acknowledgement",
            next_action="Read the exact marked space and inspect its ownership before another explicit delete.",
        )
    remaining_dashboards = {item.object_id: item for item in remaining if item.kind == "dashboard"}
    missing = [item.object_id for item in dashboards if item.object_id not in remaining_dashboards]
    if missing:
        raise MutationReadbackError(
            "space deletion did not preserve every dashboard promised by the upstream relocation contract",
            next_action="Stop writes and inspect the affected dashboard IDs; do not retry the parent delete.",
        )
    target = _deleted_space_target(preimage, dashboards, remaining_dashboards)
    return completed(preview, mutation, target, status="deleted")


def _deleted_space_target(
    preimage: Any, dashboards: list[Any], remaining: Mapping[int, Any]
) -> dict[str, Any]:
    return {
        **preimage.public(),
        "deleted": True,
        "relocated_dashboard_ids": [item.object_id for item in dashboards],
        "relocated_dashboards": [remaining[item.object_id].public() for item in dashboards],
    }


def transfer_space(
    client: Any,
    *,
    app_id: int,
    space_id: int,
    uid: int,
    execute: bool = False,
) -> dict[str, Any]:
    app = positive_id(app_id, "app_id")
    selected_id = positive_id(space_id, "space_id")
    selected_uid = positive_id(uid, "uid")
    if execute:
        with WRITE_LOCK:
            return _transfer_space(client, app, selected_id, selected_uid, send=True)
    return _transfer_space(client, app, selected_id, selected_uid, send=False)


def _transfer_space(
    client: Any, app: int, space_id: int, uid: int, *, send: bool
) -> dict[str, Any]:
    _tree, objects = read_tree(client, app)
    preimage = find_object(objects, "space", space_id)
    marker = require_owned(preimage)
    inputs = {"app_id": app, "space_id": space_id, "uid": uid}
    preview = mutation_preview(
        client._preview_mutation(SPACE_TRANSFER, inputs),
        target={**preimage.public(), "marker": marker, "new_owner_uid": uid},
        preimage=preimage.public(),
        impact="Transfer ownership of this exact SDK-marked space and all contained hierarchy to one explicit user ID.",
        reads_performed=1,
    )
    if not send:
        return preview
    mutation = client._execute_mutation(SPACE_TRANSFER, inputs)
    membership = client.read(
        SPACE_MEMBERS, {"app_id": str(app), "space_id": str(space_id)}
    )
    data = membership.get("data") if isinstance(membership, Mapping) else None
    creator = data.get("creator") if isinstance(data, Mapping) else None
    creator_id = creator.get("uid", creator.get("id")) if isinstance(creator, Mapping) else None
    if str(creator_id) != str(uid):
        raise MutationReadbackError(
            "space transfer acknowledgement did not round-trip to the requested creator",
            next_action="Inspect the exact space membership and ownership before another transfer.",
        )
    return completed(preview, mutation, {**preimage.public(), "owner_uid": uid}, status="transferred")


__all__ = ["create_space", "delete_space", "rename_space", "transfer_space"]
