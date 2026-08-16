"""Governed note, report-association, layout, and ordering mutations."""

from __future__ import annotations

import copy
import json
from collections.abc import Mapping, Sequence
from typing import Any

from .actionable_error_values import actual_value
from .errors import InputValidationError, MutationReadbackError
from .kanban_mutation_contracts import (
    DASHBOARD_ORDER,
    DASHBOARD_UPDATE,
    NOTE_DELETE,
    REPORT_UNLINK,
)
from .kanban_mutation_support import (
    WRITE_LOCK,
    caller_text,
    completed,
    detail_notes,
    find_object,
    marked_name,
    marker_from_text,
    mutation_preview,
    positive_id,
    read_detail,
    read_tree,
    report_list,
    require_dashboard_authority,
    require_owned,
)
from .mutation_ownership import OwnerReference, require_mutation_authority


def replace_notes(
    client: Any,
    *,
    app_id: int,
    space_id: int,
    dashboard_id: int,
    notes: Sequence[Mapping[str, Any]],
    execute: bool = False,
) -> dict[str, Any]:
    app = positive_id(app_id, "app_id")
    space = positive_id(space_id, "space_id")
    dashboard = positive_id(dashboard_id, "dashboard_id")
    normalized = _notes(notes, dashboard)
    if execute:
        with WRITE_LOCK:
            return _replace_notes(client, app, space, dashboard, normalized, send=True)
    return _replace_notes(client, app, space, dashboard, normalized, send=False)


def _replace_notes(
    client: Any,
    app: int,
    space: int,
    dashboard: int,
    layout: list[dict[str, Any]],
    *,
    send: bool,
) -> dict[str, Any]:
    detail = read_detail(client, app, space, dashboard)
    if report_list(detail):
        raise InputValidationError(
            "actual value: dashboard contains embedded reports; allowed value: a note-only dashboard",
            field="dashboard_id",
            next_action="Choose an empty/note-only SDK dashboard; this action will not modify multidimensional report content.",
        )
    ownership = require_dashboard_authority(client, detail, dashboard)
    inputs = {
        "app_id": app,
        "id": dashboard,
        "report_list": [],
        "space_id": space,
        "ui_config": json.dumps(layout, ensure_ascii=False, separators=(",", ":")),
    }
    preview = mutation_preview(
        client._preview_mutation(DASHBOARD_UPDATE, inputs),
        target={
            "kind": "dashboard",
            "id": dashboard,
            "space_id": space,
            "note_count": len(layout),
            "ownership": ownership.public(),
        },
        preimage={"id": dashboard, "note_count": len(detail_notes(detail)), "report_count": 0},
        impact=f"Replace the note-only dashboard layout with {len(layout)} SDK-marked notes; report associations remain empty.",
        reads_performed=1,
    )
    if not send:
        return preview
    mutation = client._execute_mutation(DASHBOARD_UPDATE, inputs)
    after = read_detail(client, app, space, dashboard)
    actual = detail_notes(after)
    expected_markers = {marker_from_text(item["name"]) for item in layout}
    actual_markers = {marker_from_text(item.get("name")) for item in actual}
    if actual_markers != expected_markers or report_list(after):
        raise MutationReadbackError(
            "dashboard note replacement did not round-trip without report changes",
            next_action="Read the exact dashboard layout and report list before another content write.",
        )
    return completed(
        preview,
        mutation,
        {
            "kind": "dashboard",
            "id": dashboard,
            "space_id": space,
            "note_count": len(actual),
            "notes": [
                {"id": item.get("i"), "marker": marker_from_text(item.get("name"))}
                for item in actual
            ],
        },
        status="updated",
    )


def delete_note(
    client: Any,
    *,
    app_id: int,
    space_id: int,
    dashboard_id: int,
    note_id: str,
    execute: bool = False,
) -> dict[str, Any]:
    app = positive_id(app_id, "app_id")
    space = positive_id(space_id, "space_id")
    dashboard = positive_id(dashboard_id, "dashboard_id")
    selected_note = caller_text(note_id, "note_id", 64)
    if execute:
        with WRITE_LOCK:
            return _delete_note(client, app, space, dashboard, selected_note, send=True)
    return _delete_note(client, app, space, dashboard, selected_note, send=False)


def _delete_note(
    client: Any, app: int, space: int, dashboard: int, note_id: str, *, send: bool
) -> dict[str, Any]:
    detail = read_detail(client, app, space, dashboard)
    matches = [item for item in detail_notes(detail) if item.get("i") == note_id]
    if len(matches) != 1:
        raise MutationReadbackError(
            "exact dashboard note preimage is missing or ambiguous",
            next_action="Read dashboard detail and choose one exact note `i` value before another write.",
        )
    marker = marker_from_text(matches[0].get("name"))
    ownership = require_mutation_authority(
        client,
        marker=marker,
        owner=OwnerReference(None, None, "not_exposed"),
        object_kind="Kanban note",
        object_id=note_id,
        field="note_id",
    )
    inputs = {"app_id": app, "id": dashboard, "i": note_id, "space_id": space}
    preview = mutation_preview(
        client._preview_mutation(NOTE_DELETE, inputs),
        target={
            "kind": "note",
            "id": note_id,
            "dashboard_id": dashboard,
            "marker": marker,
            "ownership": ownership.public(),
        },
        preimage={"id": note_id, "name": matches[0].get("name"), "marker": marker},
        impact="Permanently delete this exact SDK-marked dashboard note.",
        reads_performed=1,
    )
    if not send:
        return preview
    mutation = client._execute_mutation(NOTE_DELETE, inputs)
    after = read_detail(client, app, space, dashboard)
    if any(item.get("i") == note_id for item in detail_notes(after)):
        raise MutationReadbackError(
            "dashboard note still exists after delete acknowledgement",
            next_action="Read the exact dashboard layout before another explicit note delete.",
        )
    return completed(preview, mutation, {"kind": "note", "id": note_id, "deleted": True}, status="deleted")


def unlink_reports(
    client: Any,
    *,
    app_id: int,
    space_id: int,
    dashboard_id: int,
    report_ids: Sequence[int],
    execute: bool = False,
) -> dict[str, Any]:
    app = positive_id(app_id, "app_id")
    space = positive_id(space_id, "space_id")
    dashboard = positive_id(dashboard_id, "dashboard_id")
    selected = _id_list(report_ids, "report_ids")
    if execute:
        with WRITE_LOCK:
            return _unlink_reports(client, app, space, dashboard, selected, send=True)
    return _unlink_reports(client, app, space, dashboard, selected, send=False)


def _unlink_reports(
    client: Any,
    app: int,
    space: int,
    dashboard: int,
    report_ids: list[int],
    *,
    send: bool,
) -> dict[str, Any]:
    detail = read_detail(client, app, space, dashboard)
    ownership = require_dashboard_authority(client, detail, dashboard)
    existing = {int(item["report_id"]) for item in report_list(detail) if str(item.get("report_id", "")).isdecimal()}
    if not set(report_ids) <= existing:
        raise InputValidationError(
            f"actual value: {actual_value(report_ids)}; allowed values: exact report IDs currently attached to this dashboard",
            field="report_ids",
            next_action="Read dashboard detail, select only attached report IDs, and run dry-run again.",
        )
    inputs = {"app_id": app, "dashboard_id": dashboard, "ids": report_ids, "space_id": space}
    preview = mutation_preview(
        client._preview_mutation(REPORT_UNLINK, inputs),
        target={
            "kind": "dashboard_report_association",
            "dashboard_id": dashboard,
            "report_ids": report_ids,
            "ownership": ownership.public(),
        },
        impact=f"Remove {len(report_ids)} chart associations from this dashboard; the underlying saved reports are not deleted or modified.",
        reads_performed=1,
    )
    if not send:
        return preview
    mutation = client._execute_mutation(REPORT_UNLINK, inputs)
    after = read_detail(client, app, space, dashboard)
    remaining = {int(item["report_id"]) for item in report_list(after) if str(item.get("report_id", "")).isdecimal()}
    if set(report_ids) & remaining:
        raise MutationReadbackError(
            "dashboard report association still exists after unlink acknowledgement",
            next_action="Read the exact dashboard report list before another unlink.",
        )
    return completed(preview, mutation, {"dashboard_id": dashboard, "unlinked_report_ids": report_ids}, status="updated")


def save_order(
    client: Any,
    *,
    app_id: int,
    order_detail: Sequence[Mapping[str, Any]],
    execute: bool = False,
) -> dict[str, Any]:
    app = positive_id(app_id, "app_id")
    supplied = _order_detail(order_detail)
    if execute:
        with WRITE_LOCK:
            return _save_order(client, app, supplied, send=True)
    return _save_order(client, app, supplied, send=False)


def _save_order(client: Any, app: int, supplied: list[dict[str, Any]], *, send: bool) -> dict[str, Any]:
    current, objects = read_tree(client, app)
    ownership = [require_owned(client, app, item) for item in objects]
    if _canonical_tree(current) != _canonical_tree(supplied):
        raise InputValidationError(
            "actual value: order_detail changes fields, membership, or parents; allowed value: the current tree with sibling arrays reordered only",
            field="order_detail",
            next_action="Start from the latest `analysis.dashboard.tree` result, change only sibling order, and run dry-run again.",
        )
    inputs = {"app_id": app, "order_detail": supplied}
    preview = mutation_preview(
        client._preview_mutation(DASHBOARD_ORDER, inputs),
        target={
            "kind": "kanban_order",
            "object_count": len(objects),
            "ownership": [item.public() for item in ownership],
        },
        impact="Persist sibling ordering only; object fields, parents, and membership are unchanged.",
        reads_performed=1,
    )
    if not send:
        return preview
    expected = _order_signature(supplied)
    mutation = client._execute_mutation(DASHBOARD_ORDER, inputs)
    after, _objects = read_tree(client, app)
    if _order_signature(after) != expected:
        raise MutationReadbackError(
            "Kanban order did not round-trip",
            next_action="Read the latest tree and review concurrent ordering changes before another save.",
        )
    return completed(preview, mutation, {"kind": "kanban_order", "saved": True}, status="updated")


def _notes(value: Any, dashboard_id: int) -> list[dict[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or len(value) > 20:
        raise InputValidationError(
            f"actual value: {actual_value({'type': type(value).__name__, 'length': len(value) if isinstance(value, Sequence) else None})}; allowed value: an array of at most 20 notes",
            field="notes",
            next_action="Provide zero through 20 note objects and run dry-run again.",
        )
    result = []
    for index, item in enumerate(value):
        if not isinstance(item, Mapping) or set(item) - {"title", "content", "idempotency_key"}:
            raise InputValidationError(
                f"actual value: {actual_value(sorted(item) if isinstance(item, Mapping) else type(item).__name__)}; allowed fields: title, content, idempotency_key",
                field=f"notes[{index}]",
                next_action="Remove unknown note fields and run dry-run again.",
            )
        title = caller_text(item.get("title"), f"notes[{index}].title", 96)
        content = caller_text(item.get("content"), f"notes[{index}].content", 4_000)
        key = item.get("idempotency_key")
        if key is not None:
            key = caller_text(key, f"notes[{index}].idempotency_key", 128)
        name, marker = marked_name(
            "kanban_note", title, {"dashboard_id": dashboard_id, "index": index, "title": title, "content": content},
            idempotency_key=key,
        )
        result.append({
            "i": f"notes_{marker[5:]}", "x": 0, "y": index * 3, "w": 4,
            "h": 2.4, "name": name, "content": content, "subject": "notes", "isSmall": False,
        })
    return result


def _id_list(value: Any, field: str) -> list[int]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or not 1 <= len(value) <= 100:
        raise InputValidationError(
            f"actual value: {actual_value(value)}; allowed value: 1 through 100 positive integer IDs",
            field=field,
            next_action=f"Provide a non-empty bounded {field} list from the latest dashboard detail and run dry-run again.",
        )
    selected = [positive_id(item, field) for item in value]
    if len(selected) != len(set(selected)):
        raise InputValidationError(
            f"actual value: {actual_value(selected)}; allowed value: unique IDs",
            field=field,
            next_action="Remove duplicate IDs and run dry-run again.",
        )
    return selected


def _order_detail(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or not value or len(value) > 1_000:
        raise InputValidationError(
            f"actual value: {actual_value({'type': type(value).__name__, 'length': len(value) if isinstance(value, Sequence) else None})}; allowed value: the non-empty current Kanban tree, at most 1000 roots",
            field="order_detail",
            next_action="Use the latest bounded Kanban tree and run dry-run again.",
        )
    try:
        return copy.deepcopy([dict(item) for item in value])
    except (TypeError, ValueError) as exc:
        raise InputValidationError(
            "actual value: order_detail contains a non-object root; allowed value: JSON objects only",
            field="order_detail",
            next_action="Remove non-object roots and run dry-run again.",
        ) from exc


def _canonical_tree(value: Any) -> Any:
    if isinstance(value, list):
        return sorted((_canonical_tree(item) for item in value), key=lambda item: str(item.get("id", "")) if isinstance(item, Mapping) else "")
    if not isinstance(value, Mapping):
        return value
    return {key: _canonical_tree(item) for key, item in sorted(value.items())}


def _order_signature(value: Sequence[Mapping[str, Any]]) -> list[Any]:
    def visit(rows: Sequence[Mapping[str, Any]]) -> list[Any]:
        result = []
        for row in rows:
            children = []
            for key in ("folder_or_dashboard", "dashboards"):
                nested = row.get(key)
                if isinstance(nested, list):
                    children.append((key, visit([item for item in nested if isinstance(item, Mapping)])))
            result.append((str(row.get("id")), children))
        return result
    return visit(value)


__all__ = ["delete_note", "replace_notes", "save_order", "unlink_reports"]
