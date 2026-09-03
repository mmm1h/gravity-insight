"""Bounded read-only catalog and target decisions for Kanban board plans."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from .errors import (
    ContractChangedError,
    GravityInsightError,
    InputValidationError,
    MutationReadbackError,
    ObjectAlreadyExistsError,
)
from .kanban_board_plan_input import public_chart
from .kanban_content_mutation import compile_notes
from .kanban_limits import DASHBOARD_LAYOUT_MAX_ITEMS
from .kanban_mutation_support import (
    create_preflight,
    detail_notes,
    find_object,
    folder_ids_equal,
    marked_name,
    normalize_report_id,
    read_detail,
    read_tree,
    report_list,
    require_dashboard_authority,
)
from .mutation_ownership import (
    create_user_owner,
    require_mutation_authority,
    single_creator_owner,
)
from .report_mutation_support import marker
from .saved_analysis_catalog import GET_OPERATION_ID, list_saved_analyses
from .saved_analysis_support import decoded_config, require_success


def resolve_board_state(
    client: Any,
    prepared: Sequence[Mapping[str, Any]],
    *,
    app_id: int,
    target: Mapping[str, Any],
    notes: Sequence[Mapping[str, Any]],
    workspace: Any,
    max_pages: int,
    max_items: int,
    max_workers: int,
) -> dict[str, Any]:
    rows, catalog_reads = _catalog(
        client, prepared, app_id, workspace, max_pages, max_items, max_workers
    )
    decisions, detail_reads = _saved_decisions(
        client, prepared, rows, app_id=str(app_id)
    )
    target_state, target_reads = _target_decision(client, app_id, target)
    existing = _existing_state(target_state)
    _validate_existing_transition(decisions, notes, target_state, existing)
    return {
        "decisions": decisions,
        "target": target_state,
        "existing": existing,
        "logical_reads": catalog_reads + detail_reads + target_reads,
        "http_read_upper_bound": (
            (max_pages if catalog_reads else 0) + detail_reads + target_reads
        ),
    }


def _catalog(
    client: Any,
    prepared: Sequence[Mapping[str, Any]],
    app_id: int,
    workspace: Any,
    max_pages: int,
    max_items: int,
    max_workers: int,
) -> tuple[list[Mapping[str, Any]], int]:
    if not prepared:
        return [], 0
    value = list_saved_analyses(
        client, app_id, workspace=workspace, max_pages=max_pages,
        max_items=max_items, max_workers=max_workers,
    )
    rows = [item for item in value["items"] if item.get("is_deleted") is not True]
    return rows, 1


def _saved_decisions(
    client: Any,
    prepared: Sequence[Mapping[str, Any]],
    rows: Sequence[Mapping[str, Any]],
    *,
    app_id: str,
) -> tuple[list[dict[str, Any]], int]:
    decisions, selected_ids, reads = [], set(), 0
    for index, chart in enumerate(prepared):
        decision, detail_read = _saved_decision(
            client, chart, rows, app_id=app_id, index=index
        )
        report_id = decision.get("report_id")
        if isinstance(report_id, str) and report_id in selected_ids:
            raise InputValidationError(
                "more than one desired definition resolves to the same saved Analysis",
                field=f"saved_definitions[{index}].report_id",
                next_action="Use each saved Analysis at most once in the desired board.",
            )
        if isinstance(report_id, str):
            selected_ids.add(report_id)
        decisions.append(decision)
        reads += detail_read
    return decisions, reads


def _saved_decision(
    client: Any,
    chart: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
    *,
    app_id: str,
    index: int,
) -> tuple[dict[str, Any], int]:
    selected = _select_saved(chart, rows, index)
    if selected is None:
        _require_unique_name(chart, rows, index)
        return _create_decision(chart), 0
    analysis_id = str(selected["id"])
    detail = _read_saved_detail(client, app_id, analysis_id)
    expected_remark = _marked_remark(
        marker(selected, ("name", "remark"))
        or marker(detail, ("name", "remark")),
        chart["remark"],
    )
    same = _same_saved_definition(detail, chart, expected_remark)
    result = public_chart(chart) | {
        "decision": "reuse" if same else "update",
        "report_id": analysis_id,
        "report_id_binding": None,
        "decision_reason": (
            "exact_definition_current" if same else "exact_definition_differs"
        ),
    }
    if not same:
        result["ownership"] = _saved_authority(
            client, selected, detail, analysis_id
        ).public()
    return result, 1


def _select_saved(
    chart: Mapping[str, Any], rows: Sequence[Mapping[str, Any]], index: int
) -> Mapping[str, Any] | None:
    explicit = chart.get("report_id")
    if explicit is not None:
        matches = [row for row in rows if str(row.get("id")) == explicit]
        if len(matches) != 1:
            raise InputValidationError(
                "report_id is missing or ambiguous in the complete saved Analysis catalog",
                field=f"saved_definitions[{index}].report_id",
                next_action="Use one exact accessible report ID from this App.",
            )
        return matches[0]
    matches = [
        row for row in rows
        if marker(row, ("name", "remark")) == chart["marker"]
    ]
    if len(matches) > 1:
        raise MutationReadbackError(
            "more than one saved Analysis has the planned SDK marker",
            next_action="Resolve duplicate markers before preparing the board again.",
        )
    return matches[0] if matches else None


def _require_unique_name(
    chart: Mapping[str, Any], rows: Sequence[Mapping[str, Any]], index: int
) -> None:
    if any(row.get("name") == chart["name"] for row in rows):
        raise ObjectAlreadyExistsError(
            "a different saved Analysis already uses the desired name",
            field=f"saved_definitions[{index}].name",
            next_action="Provide its report_id to update/reuse it, or choose another name.",
        )


def _create_decision(chart: Mapping[str, Any]) -> dict[str, Any]:
    return public_chart(chart) | {
        "decision": "create",
        "report_id": None,
        "report_id_binding": {
            "$ref": f"saved_definitions.{chart['key']}.report_id",
            "type": "report_id",
        },
        "decision_reason": "sdk_marker_not_found",
    }


def _target_decision(
    client: Any, app_id: int, target: Mapping[str, Any]
) -> tuple[dict[str, Any], int]:
    if target["mode"] == "existing":
        detail = read_detail(
            client, app_id, target["space_id"], target["dashboard_id"]
        )
        _require_space(detail, target["space_id"])
        ownership = require_dashboard_authority(
            client, detail, target["dashboard_id"]
        )
        return dict(target) | {
            "decision": "reuse", "detail": detail,
            "ownership": ownership.public(), "dashboard_id_binding": None,
        }, 1
    return _new_target_decision(client, app_id, target)


def _new_target_decision(
    client: Any, app_id: int, target: Mapping[str, Any]
) -> tuple[dict[str, Any], int]:
    wire_name, selected_marker = marked_name(
        "kanban_dashboard", target["name"],
        {
            "app_id": app_id, "space_id": target["space_id"],
            "folder_id": target["folder_id"], "name": target["name"],
        },
        idempotency_key=target.get("idempotency_key"),
    )
    _tree, objects = read_tree(client, app_id)
    _validate_destination(objects, target)
    existing = create_preflight(objects, "dashboard", selected_marker, wire_name)
    base = dict(target) | {"wire_name": wire_name, "marker": selected_marker}
    if existing is None:
        return base | {
            "decision": "create", "detail": None, "ownership": None,
            "dashboard_id": None,
            "dashboard_id_binding": {
                "$ref": "target.dashboard_id", "type": "positive_integer"
            },
        }, 1
    _require_existing_parent(existing, target)
    detail = read_detail(client, app_id, existing.space_id, existing.object_id)
    ownership = require_dashboard_authority(client, detail, existing.object_id)
    return base | {
        "decision": "reuse", "detail": detail,
        "ownership": ownership.public(), "dashboard_id": existing.object_id,
        "dashboard_id_binding": None,
    }, 2


def _validate_destination(objects: Sequence[Any], target: Mapping[str, Any]) -> None:
    find_object(objects, "space", target["space_id"])
    if target["folder_id"]:
        folder = find_object(objects, "folder", target["folder_id"])
        if folder.space_id != target["space_id"]:
            raise InputValidationError(
                "target folder belongs to a different space",
                field="target.folder_id",
                next_action="Choose a folder from the selected target space.",
            )


def _require_existing_parent(existing: Any, target: Mapping[str, Any]) -> None:
    if (
        existing.space_id != target["space_id"]
        or not folder_ids_equal(existing.folder_id, target["folder_id"])
    ):
        raise ObjectAlreadyExistsError(
            "the planned dashboard marker already exists under another parent",
            field="target",
            next_action="Reuse its exact coordinates or choose another idempotency key.",
        )


def _existing_state(target: Mapping[str, Any]) -> dict[str, Any]:
    detail = target.get("detail")
    if detail is None:
        return {
            "report_ids": [], "notes": [],
            "counts": {"charts": 0, "notes": 0, "layout_items": 0},
        }
    reports, notes, layout = report_list(detail), detail_notes(detail), _layout(detail)
    if len(layout) != len(reports) + len(notes):
        raise InputValidationError(
            "existing dashboard contains layout items outside report and note contracts",
            field="target.dashboard_id",
            next_action="Choose an empty/report-and-note-only dashboard; unrecognized items stay untouched.",
        )
    report_ids = _report_ids(reports)
    return {
        "report_ids": report_ids, "notes": notes,
        "counts": {
            "charts": len(report_ids), "notes": len(notes),
            "layout_items": len(layout),
        },
    }


def _validate_existing_transition(
    decisions: Sequence[Mapping[str, Any]],
    notes: Sequence[Mapping[str, Any]],
    target: Mapping[str, Any],
    existing: Mapping[str, Any],
) -> None:
    if target.get("detail") is None:
        return
    desired_known = {
        item["report_id"] for item in decisions
        if isinstance(item.get("report_id"), str)
    }
    if any(item not in desired_known for item in existing["report_ids"]):
        raise InputValidationError(
            "existing dashboard contains reports outside the desired definitions",
            field="target.dashboard_id",
            next_action="Use a new/empty dashboard or include every attached report by report_id.",
        )
    expected_notes = compile_notes(notes, target["dashboard_id"])
    if existing["report_ids"] and list(existing["notes"]) != expected_notes:
        raise InputValidationError(
            "existing dashboard notes differ while reports are attached",
            field="notes",
            next_action="Use a new/empty target; note replacement will not overwrite report layout.",
        )


def _read_saved_detail(
    client: Any, app_id: str, analysis_id: str
) -> Mapping[str, Any]:
    value = client.read(GET_OPERATION_ID, {"app_id": app_id, "id": analysis_id})
    require_success(value, GET_OPERATION_ID, "saved Analysis board-plan detail")
    data = value.get("data") if isinstance(value, Mapping) else None
    if not isinstance(data, Mapping):
        raise ContractChangedError("saved Analysis board-plan detail changed shape")
    if str(data.get("id")) != analysis_id or str(data.get("app_id")) != app_id:
        raise ContractChangedError("saved Analysis board-plan detail changed identity")
    return data


def _saved_authority(
    client: Any, row: Mapping[str, Any], detail: Mapping[str, Any], analysis_id: str
) -> Any:
    selected_marker = marker(row, ("name", "remark")) or marker(
        detail, ("name", "remark")
    )
    owner = create_user_owner(detail)
    if owner.owner_id is None:
        owner = create_user_owner(row)
    if owner.owner_id is None:
        owner = single_creator_owner(detail.get("creator"))
    return require_mutation_authority(
        client, marker=selected_marker, owner=owner,
        object_kind="saved Analysis", object_id=analysis_id, field="analysis_id",
    )


def _same_saved_definition(
    current: Mapping[str, Any], desired: Mapping[str, Any], expected_remark: str
) -> bool:
    scalars = (
        ("name", desired["name"]), ("subject", desired["subject"]),
        ("remark", expected_remark),
    )
    if any(str(current.get(field)) != str(expected) for field, expected in scalars):
        return False
    try:
        return decoded_config(current.get("config")) == json.loads(desired["config_text"])
    except (GravityInsightError, ValueError, TypeError):
        return False


def _marked_remark(selected_marker: str | None, remark: str) -> str:
    return remark if selected_marker is None else (
        f"{selected_marker} | {remark}" if remark else selected_marker
    )


def _require_space(detail: Mapping[str, Any], expected: int) -> None:
    actual = detail.get("space_id")
    selected = int(actual) if isinstance(actual, str) and actual.isdecimal() else actual
    if selected != expected:
        raise InputValidationError(
            "dashboard detail belongs to a different space",
            field="target.space_id",
            next_action="Use the exact space_id returned with this dashboard.",
        )


def _layout(detail: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    raw = detail.get("ui_config")
    try:
        decoded = json.loads(raw) if isinstance(raw, str) else raw
    except json.JSONDecodeError as exc:
        raise ContractChangedError("dashboard ui_config is not valid JSON") from exc
    if decoded in (None, ""):
        return []
    if (
        not isinstance(decoded, list) or len(decoded) > DASHBOARD_LAYOUT_MAX_ITEMS
        or any(not isinstance(item, Mapping) for item in decoded)
    ):
        raise ContractChangedError(
            "dashboard ui_config no longer contains a bounded layout array"
        )
    return [dict(item) for item in decoded]


def _report_ids(reports: Sequence[Mapping[str, Any]]) -> list[str]:
    result: list[str] = []
    for item in reports:
        selected = normalize_report_id(item.get("report_id"))
        if selected is None or selected in result:
            raise ContractChangedError(
                "existing dashboard report identities changed shape or contain duplicates"
            )
        result.append(selected)
    return result


def public_target(value: Mapping[str, Any]) -> dict[str, Any]:
    fields = (
        "mode", "decision", "space_id", "folder_id", "dashboard_id",
        "dashboard_id_binding", "name", "marker", "ownership",
    )
    return {key: value.get(key) for key in fields if key in value}


__all__ = ["public_target", "resolve_board_state"]
