"""Governed whole-list attachment of saved analyses to a Kanban dashboard."""

from __future__ import annotations

import copy
import json
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .actionable_error_values import actual_value
from .errors import ContractChangedError, InputValidationError, MutationReadbackError
from .kanban_mutation_contracts import DASHBOARD_UPDATE, REPORT_LIST
from .kanban_mutation_support import (
    WRITE_LOCK,
    completed,
    marker_from_text,
    mutation_preview,
    normalize_report_id,
    positive_id,
    read_detail,
    report_list,
    require_dashboard_authority,
)


@dataclass(frozen=True)
class _LinkState:
    existing_ids: list[str]
    new_ids: list[str]
    already_attached: list[str]
    layout: list[Mapping[str, Any]]
    inputs: dict[str, Any]


def link_reports(
    client: Any,
    *,
    app_id: int,
    space_id: int,
    dashboard_id: int,
    report_ids: Sequence[str | int],
    execute: bool = False,
) -> dict[str, Any]:
    app = positive_id(app_id, "app_id")
    space = positive_id(space_id, "space_id")
    dashboard = positive_id(dashboard_id, "dashboard_id")
    selected = _report_ids(report_ids)
    if execute:
        with WRITE_LOCK:
            return _link_reports(client, app, space, dashboard, selected, send=True)
    return _link_reports(client, app, space, dashboard, selected, send=False)


def _link_reports(
    client: Any,
    app: int,
    space: int,
    dashboard: int,
    report_ids: list[str],
    *,
    send: bool,
) -> dict[str, Any]:
    detail = read_detail(client, app, space, dashboard)
    ownership = require_dashboard_authority(client, detail, dashboard)
    state = _prepare_link(client, app, space, detail, dashboard, report_ids)
    preview = _link_preview(client, dashboard, report_ids, ownership, state)
    if not send:
        return preview
    if not state.new_ids:
        return _already_attached(preview, dashboard, report_ids)
    mutation = client._execute_mutation(DASHBOARD_UPDATE, state.inputs)
    recovery_marker = marker_from_text(detail.get("name"))
    with MutationReadbackError.after_dispatch(mutation, recovery_marker):
        after = read_detail(client, app, space, dashboard)
        remaining_ids = _verify_link_readback(after, state)
    return completed(
        preview,
        mutation,
        {
            "kind": "dashboard_report_association",
            "dashboard_id": dashboard,
            "report_ids": remaining_ids,
            "linked_report_ids": state.new_ids,
            "already_attached_report_ids": state.already_attached,
            "ownership": ownership.public(),
        },
        status="updated",
    )


def _prepare_link(
    client: Any,
    app: int,
    space: int,
    detail: Mapping[str, Any],
    dashboard: int,
    report_ids: list[str],
) -> _LinkState:
    existing_reports = report_list(detail)
    existing_ids = _attached_report_ids(existing_reports)
    existing_set = set(existing_ids)
    new_ids = [item for item in report_ids if item not in existing_set]
    already_attached = [item for item in report_ids if item in existing_set]
    if len(existing_ids) + len(new_ids) > 20:
        raise InputValidationError(
            f"actual value: {len(existing_ids) + len(new_ids)} attached reports; allowed value: at most 20",
            field="report_ids",
            next_action="Unlink enough existing reports or select fewer new report IDs, then run dry-run again.",
        )
    available = _available_reports(client, app) if new_ids else {}
    unavailable = [item for item in new_ids if item not in available]
    if unavailable:
        raise InputValidationError(
            f"actual value: {actual_value(unavailable)}; allowed values: report IDs in the current principal's complete accessible saved-analysis catalog",
            field="report_ids",
            next_action="Read `analysis.report_config.list` for this App, choose only visible report IDs, and run dry-run again.",
        )
    layout_wire, layout = _dashboard_layout(detail)
    linked_layout = _linked_layout(layout, new_ids, available)
    merged = copy.deepcopy(existing_reports)
    merged.extend(
        {"report_id": item, "name": available[item]["name"]}
        for item in new_ids
    )
    inputs = {
        "app_id": app,
        "id": dashboard,
        "report_list": merged,
        "space_id": space,
        "ui_config": (
            layout_wire
            if not new_ids
            else json.dumps(linked_layout, ensure_ascii=False, separators=(",", ":"))
        ),
    }
    return _LinkState(
        existing_ids,
        new_ids,
        already_attached,
        layout,
        inputs,
    )


def _link_preview(
    client: Any,
    dashboard: int,
    report_ids: list[str],
    ownership: Any,
    state: _LinkState,
) -> dict[str, Any]:
    impact = (
        "No report association will change because every requested report is already attached."
        if not state.new_ids
        else f"Attach {len(state.new_ids)} saved analyses while preserving all {len(state.existing_ids)} existing report associations and the current layout."
    )
    preview = mutation_preview(
        client._preview_mutation(DASHBOARD_UPDATE, state.inputs),
        target={
            "kind": "dashboard_report_association",
            "dashboard_id": dashboard,
            "report_ids": report_ids,
            "linked_report_ids": state.new_ids,
            "already_attached_report_ids": state.already_attached,
            "ownership": ownership.public(),
        },
        preimage={
            "dashboard_id": dashboard,
            "report_ids": state.existing_ids,
            "report_count": len(state.existing_ids),
            "layout_preserved": True,
        },
        impact=impact,
        reads_performed=1 + bool(state.new_ids),
    )
    if not state.new_ids:
        preview["idempotent_reuse"] = True
        preview["next_action"] = "No write is needed; every requested report is already attached."
    return preview


def _verify_link_readback(
    after: Mapping[str, Any], state: _LinkState
) -> list[str]:
    remaining_ids = _attached_report_ids(report_list(after))
    _after_wire, after_layout = _dashboard_layout(after)
    expected_ids = {*state.existing_ids, *state.new_ids}
    if set(remaining_ids) != expected_ids:
        raise MutationReadbackError(
            "dashboard report link did not round-trip the exact association set",
            next_action="Read the exact dashboard report list before another content write.",
        )
    if not _layout_preserved(state.layout, after_layout):
        raise MutationReadbackError(
            "dashboard report link did not preserve every existing layout item",
            next_action="Read the exact dashboard report list and layout before another content write.",
        )
    return remaining_ids


def _layout_preserved(
    before: Sequence[Mapping[str, Any]], after: Sequence[Mapping[str, Any]]
) -> bool:
    def fingerprint(item: Mapping[str, Any]) -> str:
        return json.dumps(dict(item), ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    missing = Counter(map(fingerprint, before)) - Counter(map(fingerprint, after))
    return not missing


def _linked_layout(
    layout: Sequence[Mapping[str, Any]],
    new_ids: Sequence[str],
    available: Mapping[str, Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    if len(layout) + len(new_ids) > 20:
        raise InputValidationError(
            f"actual value: {len(layout) + len(new_ids)} layout items; allowed value: at most 20",
            field="report_ids",
            next_action="Remove enough dashboard layout items or select fewer reports, then run dry-run again.",
        )
    bottom = _layout_bottom(layout)
    result = copy.deepcopy(list(layout))
    result.extend(
        {
            "i": report_id,
            "x": 0,
            "y": bottom + index * 5,
            "w": 2,
            "h": 5,
            "name": available[report_id]["name"],
            "subject": available[report_id]["subject"],
            "isSmall": False,
        }
        for index, report_id in enumerate(new_ids)
    )
    return result


def _layout_bottom(layout: Sequence[Mapping[str, Any]]) -> float | int:
    bottoms = []
    for item in layout:
        y_value, height = item.get("y"), item.get("h")
        y = y_value if type(y_value) in {int, float} else 0
        h = height if type(height) in {int, float} else 0
        bottoms.append(y + h)
    return max(bottoms, default=0)


def _attached_report_ids(reports: Sequence[Mapping[str, Any]]) -> list[str]:
    result: list[str] = []
    for item in reports:
        selected = normalize_report_id(item.get("report_id"))
        if selected is None or selected in result:
            raise ContractChangedError(
                "dashboard report identities changed shape or contain duplicates",
                next_action="Stop dashboard report writes until the embedded report identity contract is re-verified.",
            )
        result.append(selected)
    return result


def _available_reports(client: Any, app_id: int) -> dict[str, Mapping[str, Any]]:
    value = client.read_all(
        REPORT_LIST,
        {"app_id": str(app_id), "page": 1, "page_size": 1_000},
        max_pages=1_000,
        max_items=100_000,
    )
    rows = _catalog_rows(value)
    result: dict[str, Mapping[str, Any]] = {}
    seen: set[str] = set()
    for row in rows:
        report_id, selected = _catalog_report(row, app_id)
        if report_id in seen:
            raise ContractChangedError(
                "saved-analysis catalog contains a duplicate projected identity",
                next_action="Stop dashboard report links until the saved-analysis list contract is re-verified.",
            )
        seen.add(report_id)
        if selected is not None:
            result[report_id] = selected
    return result


def _catalog_rows(value: Any) -> list[Any]:
    data = value.get("data") if isinstance(value, Mapping) else None
    rows = data.get("list") if isinstance(data, Mapping) else None
    invalid = not isinstance(value, Mapping) or not isinstance(rows, list)
    if isinstance(value, Mapping):
        invalid = invalid or value.get("error") is not None
        invalid = invalid or value.get("status") not in {
            "success", "empty", "contract_changed_additive",
        }
        invalid = invalid or value.get("truncated") is True
        invalid = invalid or value.get("next_page_input") not in (None, {})
    if invalid:
        raise MutationReadbackError(
            "saved-analysis catalog could not be read completely for dashboard link preflight",
            next_action="Restore `analysis.report_config.list` for this exact App before another report link.",
        )
    return rows


def _catalog_report(
    row: Any, app_id: int
) -> tuple[str, Mapping[str, Any] | None]:
    if not isinstance(row, Mapping):
        raise _catalog_contract_error()
    report_id = normalize_report_id(row.get("id"))
    row_app = _catalog_app_id(row.get("app_id"))
    name = row.get("name")
    subject = row.get("subject")
    if (
        report_id is None
        or row_app != app_id
        or not isinstance(name, str)
        or not name
        or not isinstance(subject, str)
        or not subject
    ):
        raise _catalog_contract_error()
    return report_id, None if row.get("is_deleted") is True else row


def _catalog_app_id(value: Any) -> int:
    selected = int(value) if isinstance(value, str) and value.isdecimal() else value
    if type(selected) is not int or selected < 1:
        raise _catalog_contract_error()
    return selected


def _catalog_contract_error() -> ContractChangedError:
    return ContractChangedError(
        "saved-analysis catalog contains an invalid projected identity",
        next_action="Stop dashboard report links until the saved-analysis list contract is re-verified.",
    )


def _dashboard_layout(detail: Mapping[str, Any]) -> tuple[str, list[Mapping[str, Any]]]:
    raw = detail.get("ui_config")
    try:
        decoded = json.loads(raw) if isinstance(raw, str) else raw
    except json.JSONDecodeError as exc:
        raise ContractChangedError(
            "dashboard ui_config is no longer valid JSON",
            next_action="Stop dashboard report writes until the layout contract is re-verified.",
        ) from exc
    if decoded in (None, ""):
        decoded = []
    if (
        not isinstance(decoded, list)
        or len(decoded) > 20
        or any(not isinstance(item, Mapping) for item in decoded)
    ):
        raise ContractChangedError(
            "dashboard ui_config no longer contains a bounded layout array",
            next_action="Stop dashboard report writes until the layout contract is re-verified.",
        )
    wire = raw if isinstance(raw, str) else json.dumps(decoded, ensure_ascii=False, separators=(",", ":"))
    return wire, [dict(item) for item in decoded]


def _report_ids(value: Any) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or not 1 <= len(value) <= 20:
        raise InputValidationError(
            f"actual value: {actual_value(value)}; allowed value: 1 through 20 positive integer or bounded opaque string report IDs",
            field="report_ids",
            next_action="Provide a non-empty bounded report_ids list from the saved-analysis catalog and run dry-run again.",
        )
    selected = [normalize_report_id(item) for item in value]
    if any(item is None for item in selected):
        raise InputValidationError(
            f"actual value: {actual_value(value)}; allowed value: positive integers or non-empty opaque strings of at most 128 characters",
            field="report_ids",
            next_action="Use exact report IDs from the saved-analysis catalog and run dry-run again.",
        )
    if len(selected) != len(set(selected)):
        raise InputValidationError(
            f"actual value: {actual_value(selected)}; allowed value: unique report IDs",
            field="report_ids",
            next_action="Remove duplicate report IDs and run dry-run again.",
        )
    return [item for item in selected if item is not None]


def _already_attached(
    preview: Mapping[str, Any], dashboard_id: int, report_ids: Sequence[str]
) -> dict[str, Any]:
    return {
        "schema_version": preview["schema_version"],
        "result_source": copy.deepcopy(preview["result_source"]),
        "ok": True,
        "status": "already_attached",
        "operation_id": DASHBOARD_UPDATE,
        "effect": "mutation",
        "offline": False,
        "network_called": True,
        "write_sent": False,
        "dry_run": False,
        "confirmation_required": False,
        "automatic_retry": False,
        "attempts": 0,
        "idempotent_reuse": True,
        "target": {
            "kind": "dashboard_report_association",
            "dashboard_id": dashboard_id,
            "report_ids": list(report_ids),
        },
        "impact": preview["impact"],
        "preview_fingerprint": preview["preview_fingerprint"],
        "mutation": None,
        "error": None,
    }


__all__ = ["link_reports"]
