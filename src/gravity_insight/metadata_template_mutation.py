"""Governed lifecycle for reusable event/property metadata templates."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .actionable_error_values import actual_value
from .composite_catalog import stable_operation
from .errors import ContractChangedError
from .metadata_template_contracts import (
    TEMPLATE_APPEND,
    TEMPLATE_EVENT_MEMBERS,
    TEMPLATE_EVENT_REMOVE,
    TEMPLATE_LIST,
    TEMPLATE_MASTER,
    TEMPLATE_PROPERTY_MEMBERS,
    TEMPLATE_PROPERTY_REMOVE,
)
from .metadata_template_lifecycle import (
    SCHEMA_VERSION,
    boolean as _boolean,
    completed as _completed,
    dependent_preview as _dependent_preview,
    idempotent as _idempotent,
    identifier as _identifier,
    identifiers as _identifiers,
    member_names as _member_names,
    metadata_name as _metadata_name,
    metadata_template_input_error,
    preview as _preview,
    row_id as _row_id,
    require_target_members as _require_target_members,
    template_type as _template_type,
    text as _text,
)
from .mutation_lifecycle import MARKER_PREFIX, WRITE_LOCK, mutation_marker
from .mutation_ownership import create_user_owner, require_mutation_authority
from .report_mutation_support import marker
_ACTIONS = frozenset({"create", "append", "remove", "delete"})
_ACTION_FIELDS = {
    "create": (
        frozenset({"app_id", "name", "template_type", "target_ids"}),
        frozenset({"need_common", "remark", "idempotency_key"}),
    ),
    "append": (
        frozenset({"app_id", "template_id", "target_ids"}),
        frozenset({"need_common"}),
    ),
    "remove": (frozenset({"template_id", "member_ids"}), frozenset()),
    "delete": (frozenset({"template_id"}), frozenset()),
}


def metadata_template_mutation_schema() -> dict[str, Any]:
    return {
        "schema_version": "gravity-insight.metadata-template-mutation-schema.v1",
        "offline": True,
        "network_called": False,
        "actions": {
            action: {
                "required": sorted(required),
                "optional": sorted(optional),
                "confirmation_required": True,
            }
            for action, (required, optional) in _ACTION_FIELDS.items()
        },
    }


def run_metadata_template_mutation(
    client: Any, action: str, inputs: Mapping[str, Any], *, execute: bool = False
) -> dict[str, Any]:
    if action not in _ACTIONS:
        raise metadata_template_input_error(
            actual_value(action), actual_value(sorted(_ACTIONS)), "action",
            "Choose an action from the offline metadata-template schema.",
        )
    if not isinstance(inputs, Mapping):
        raise metadata_template_input_error(
            actual_value(type(inputs).__name__), "an input object", "inputs",
            "Pass the exact nested input object shown by the selected action card.",
        )
    required, optional = _ACTION_FIELDS[action]
    missing, unknown = required - set(inputs), set(inputs) - required - optional
    if missing or unknown:
        raise metadata_template_input_error(
            actual_value({"missing": sorted(missing), "unknown": sorted(unknown)}),
            actual_value({"required": sorted(required), "optional": sorted(optional)}),
            "inputs", "Correct the action fields and rerun the dry-run.",
        )
    functions = {
        "create": create_metadata_template,
        "append": append_metadata_template_members,
        "remove": remove_metadata_template_members,
        "delete": delete_metadata_template,
    }
    return functions[action](client, execute=execute, **dict(inputs))


def create_metadata_template(
    client: Any,
    *,
    app_id: int,
    name: str,
    template_type: str,
    target_ids: Sequence[int],
    need_common: bool = False,
    remark: str = "",
    idempotency_key: str | None = None,
    execute: bool = False,
) -> dict[str, Any]:
    selected = _create_definition(
        app_id, name, template_type, target_ids, need_common, remark
    )
    key = None if idempotency_key is None else _text(
        idempotency_key, "idempotency_key", 128
    )
    selected_marker = mutation_marker(
        "metadata_template", selected, idempotency_key=key
    )
    wire_name = f"{selected['name']} [{selected_marker}]"
    wire = _create_wire(selected, wire_name)
    raw = client._preview_mutation(TEMPLATE_MASTER, wire)
    preview = _preview(
        raw,
        {**selected, "name": wire_name, "marker": selected_marker},
        "Create one reusable template and attach the reviewed target IDs.",
    )
    if not execute:
        return preview
    with WRITE_LOCK:
        live_targets = _live_targets(client, selected)
        existing = _unique_marker(_template_catalog(client), selected_marker)
        if existing is not None:
            return _idempotent(TEMPLATE_MASTER, existing, selected_marker)
        mutation = client._execute_mutation(TEMPLATE_MASTER, wire)
        created = _unique_marker(_template_catalog(client), selected_marker)
        if created is None:
            raise ContractChangedError(
                "metadata-template create acknowledgement did not round-trip its marker",
                next_action="Read the exact GSDK template name and clean it up before another create.",
            )
        _verify_template(created, selected["template_type"], wire_name)
        members = _member_catalog(client, created)
        _require_target_members(members, live_targets.values(), present=True)
        target = {
            **dict(created), "marker": selected_marker,
            "source_target_ids": list(selected["target_ids"]),
            "member_ids": sorted(_member_ids(members)),
        }
        return _completed(preview, mutation, target, "created")


def append_metadata_template_members(
    client: Any,
    *,
    app_id: int,
    template_id: int,
    target_ids: Sequence[int],
    need_common: bool = False,
    execute: bool = False,
) -> dict[str, Any]:
    selected_id = _identifier(template_id, "template_id")
    selected_targets = _identifiers(target_ids, "target_ids")
    selected_app = _identifier(app_id, "app_id")
    _boolean(need_common, "need_common")
    preview = _dependent_preview(
        TEMPLATE_APPEND,
        {"app_id": selected_app, "template_id": selected_id,
         "target_ids": list(selected_targets), "need_common": need_common},
        "Append exact catalog members to one marker-or-owner template.",
    )
    if not execute:
        return preview
    with WRITE_LOCK:
        template = _exact_template(_template_catalog(client), selected_id)
        ownership = _authority(client, template, selected_id)
        live_targets = _live_targets(
            client,
            {"app_id": selected_app, "template_type": template["template_type"],
             "target_ids": selected_targets},
        )
        before = _member_catalog(client, template)
        existing_names = _member_names(before)
        missing = tuple(
            item for item in selected_targets
            if _metadata_name(live_targets[item], "target metadata") not in existing_names
        )
        if not missing:
            return _idempotent(
                TEMPLATE_APPEND, template, marker(template, ("name",)), before
            )
        wire = _append_wire(template, missing, selected_app, need_common)
        raw = client._preview_mutation(TEMPLATE_APPEND, wire)
        mutation = client._execute_mutation(TEMPLATE_APPEND, wire)
        after = _member_catalog(client, template)
        expected = tuple(live_targets[item] for item in missing)
        _require_target_members(after, expected, present=True)
        expected_names = {
            _metadata_name(row, "target metadata") for row in expected
        }
        added = sorted(
            item for item in (
                _row_id(row) for row in after
                if _metadata_name(row, "template member") in expected_names
            ) if item is not None
        )
        target = _target(template, ownership, after, added)
        target["source_target_ids"] = list(missing)
        return _completed(_preview(raw, preview["target"], preview["impact"]), mutation, target, "updated", template)


def remove_metadata_template_members(
    client: Any,
    *,
    template_id: int,
    member_ids: Sequence[int],
    execute: bool = False,
) -> dict[str, Any]:
    selected_id = _identifier(template_id, "template_id")
    selected_members = _identifiers(member_ids, "member_ids")
    preview = _dependent_preview(
        TEMPLATE_PROPERTY_REMOVE,
        {"template_id": selected_id, "member_ids": list(selected_members)},
        "Remove exact members only after template ownership and member preimage readback.",
    )
    if not execute:
        return preview
    with WRITE_LOCK:
        template = _exact_template(_template_catalog(client), selected_id)
        ownership = _authority(client, template, selected_id)
        before = _member_catalog(client, template)
        _require_members(before, selected_members, present=True)
        operation_id, wire = _remove_wire(template, selected_members)
        raw = client._preview_mutation(operation_id, wire)
        mutation = client._execute_mutation(operation_id, wire)
        after = _member_catalog(client, template)
        _require_members(after, selected_members, present=False)
        target = _target(template, ownership, after, selected_members)
        return _completed(_preview(raw, preview["target"], preview["impact"]), mutation, target, "updated", template)


def delete_metadata_template(
    client: Any, *, template_id: int, execute: bool = False
) -> dict[str, Any]:
    selected_id = _identifier(template_id, "template_id")
    preview = _dependent_preview(
        TEMPLATE_MASTER, {"template_id": selected_id},
        "Soft-delete the exact template only after marker-or-owner master readback.",
    )
    if not execute:
        return preview
    with WRITE_LOCK:
        template = _exact_template(_template_catalog(client), selected_id)
        ownership = _authority(client, template, selected_id)
        wire = {
            "id": selected_id, "name": template["name"],
            "template_type": template["template_type"], "is_deleted": 1,
        }
        raw = client._preview_mutation(TEMPLATE_MASTER, wire)
        mutation = client._execute_mutation(TEMPLATE_MASTER, wire)
        remaining = [row for row in _template_catalog(client) if _row_id(row) == selected_id]
        if remaining:
            raise ContractChangedError(
                "metadata template still exists after delete acknowledgement",
                next_action="Stop writes and inspect this exact template ID before another delete.",
            )
        target = {
            "template_id": selected_id, "name": template["name"],
            "deleted": True, "ownership": ownership,
        }
        return _completed(_preview(raw, preview["target"], preview["impact"]), mutation, target, "deleted", template)


def _create_definition(
    app_id: Any, name: Any, template_type: Any, target_ids: Any,
    need_common: Any, remark: Any,
) -> dict[str, Any]:
    selected_type = _template_type(template_type)
    selected_name = _text(name, "name", 106)
    if MARKER_PREFIX in selected_name:
        raise metadata_template_input_error(
            actual_value(selected_name), "caller text without an SDK marker", "name",
            "Remove marker-like text; the SDK adds its own deterministic marker.",
        )
    selected_remark = _text(remark, "remark", 2_000, empty=True)
    _boolean(need_common, "need_common")
    return {
        "app_id": _identifier(app_id, "app_id"), "name": selected_name,
        "template_type": selected_type,
        "target_ids": _identifiers(target_ids, "target_ids"),
        "need_common": need_common, "remark": selected_remark,
    }


def _create_wire(selected: Mapping[str, Any], name: str) -> dict[str, Any]:
    wire = {
        "name": name, "template_type": selected["template_type"],
        "target_id_list": list(selected["target_ids"]),
        "need_common": selected["need_common"], "remark": selected["remark"],
    }
    if selected["need_common"]:
        wire["app_id"] = selected["app_id"]
    return wire


def _append_wire(
    template: Mapping[str, Any], target_ids: Sequence[int], app_id: int,
    need_common: bool,
) -> dict[str, Any]:
    wire = {
        "id": _row_id(template), "name": "",
        "template_type": template["template_type"],
        "target_id_list": list(target_ids), "need_common": need_common,
        "remark": "",
    }
    if need_common:
        wire["app_id"] = app_id
    return wire


def _remove_wire(
    template: Mapping[str, Any], target_ids: Sequence[int]
) -> tuple[str, dict[str, Any]]:
    if template.get("template_type") == "meta_property":
        return TEMPLATE_EVENT_REMOVE, {
            "template_id": _row_id(template), "event_id_list": list(target_ids)
        }
    return TEMPLATE_PROPERTY_REMOVE, {
        "template_id": _row_id(template), "property_id_list": list(target_ids)
    }


def _template_catalog(client: Any) -> list[Mapping[str, Any]]:
    return _rows(client.read_all(
        TEMPLATE_LIST, {"page": 1, "page_size": 100},
        max_pages=100, max_items=10_000, max_workers=1,
    ), "template")


def _member_catalog(
    client: Any, template: Mapping[str, Any]
) -> list[Mapping[str, Any]]:
    operation_id = (
        TEMPLATE_EVENT_MEMBERS
        if template.get("template_type") == "meta_property"
        else TEMPLATE_PROPERTY_MEMBERS
    )
    template_id = _row_id(template)
    filters = [{"field": "template_id", "operator": 1, "values": [template_id]}]
    return _rows(client.read_all(
        operation_id, {"page": 1, "page_size": 100, "filters": filters},
        max_pages=100, max_items=10_000, max_workers=1,
    ), "template member")


def _live_targets(
    client: Any, selected: Mapping[str, Any]
) -> dict[int, Mapping[str, Any]]:
    resources = {
        "meta_property": "event",
        "event_property": "event_property",
        "user_property": "user_property",
    }
    resource = resources[str(selected["template_type"])]
    operation_id = stable_operation("analysis", resource, action="list").operation_id
    inputs = {"app_id": str(selected["app_id"]), "page": 1, "page_size": 2_000}
    if resource == "event":
        inputs["need_favourite"] = False
    rows = _rows(client.read_all(
        operation_id, inputs, max_pages=8, max_items=16_000, max_workers=1,
    ), "target metadata")
    current = {
        item: row for row in rows
        if (item := _row_id(row)) is not None
    }
    missing = sorted(set(selected["target_ids"]) - set(current))
    if missing:
        raise metadata_template_input_error(
            actual_value(missing), "IDs in the complete current App metadata catalog",
            "target_ids", "Refresh this App's metadata and choose exact current target IDs.",
        )
    return {item: current[item] for item in selected["target_ids"]}


def _rows(envelope: Any, kind: str) -> list[Mapping[str, Any]]:
    if not isinstance(envelope, Mapping) or envelope.get("status") not in {"success", "empty"} or envelope.get("error") is not None:
        raise ContractChangedError(
            f"current {kind} catalog is unavailable for mutation preflight",
            next_action=f"Restore the stable {kind} read contract before another write.",
        )
    if envelope.get("truncated") is True or envelope.get("next_page_input") not in (None, {}):
        raise ContractChangedError(
            f"current {kind} catalog is incomplete for mutation preflight",
            next_action=f"Raise the bounded {kind} list limit; do not bypass preflight.",
        )
    data = envelope.get("data")
    rows = data.get("list") if isinstance(data, Mapping) else None
    if not isinstance(rows, list) or any(not isinstance(row, Mapping) for row in rows):
        raise ContractChangedError(
            f"current {kind} catalog no longer returns data.list objects",
            next_action=f"Stop writes until the {kind} response contract is re-verified.",
        )
    return rows


def _exact_template(
    rows: Sequence[Mapping[str, Any]], template_id: int
) -> Mapping[str, Any]:
    matches = [row for row in rows if _row_id(row) == template_id]
    if len(matches) != 1:
        raise metadata_template_input_error(
            actual_value({"template_id": template_id, "matches": len(matches)}),
            "exactly one current template", "template_id",
            "Refresh the complete template catalog and choose one exact current ID.",
        )
    return matches[0]


def _unique_marker(
    rows: Sequence[Mapping[str, Any]], selected_marker: str
) -> Mapping[str, Any] | None:
    matches = [row for row in rows if marker(row, ("name",)) == selected_marker]
    if len(matches) > 1:
        raise ContractChangedError(
            "more than one metadata template has the same SDK marker",
            next_action="Inspect exact marker matches and clean up only confirmed duplicates.",
        )
    return matches[0] if matches else None


def _authority(
    client: Any, template: Mapping[str, Any], template_id: int
) -> dict[str, Any]:
    decision = require_mutation_authority(
        client, marker=marker(template, ("name",)),
        owner=create_user_owner(template), object_kind="metadata template",
        object_id=template_id, field="template_id",
    )
    return decision.public()


def _verify_template(
    row: Mapping[str, Any], template_type: str, expected_name: str
) -> None:
    if row.get("name") != expected_name or row.get("template_type") != template_type:
        raise ContractChangedError(
            "metadata template definition did not round-trip the acknowledged write",
            next_action="Stop writes and inspect the exact marked template before cleanup.",
        )


def _require_members(
    rows: Sequence[Mapping[str, Any]], target_ids: Sequence[int], *, present: bool
) -> None:
    observed = _member_ids(rows)
    failed = sorted(
        item for item in target_ids if (item in observed) is not present
    )
    if failed:
        state = "appear" if present else "disappear"
        raise ContractChangedError(
            f"metadata template member IDs did not {state} after acknowledgement",
            next_action="Stop writes and inspect the exact template membership before another action.",
        )


def _member_ids(rows: Sequence[Mapping[str, Any]]) -> set[int]:
    return {item for item in (_row_id(row) for row in rows) if item is not None}


def _target(
    template: Mapping[str, Any], ownership: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]], changed: Sequence[int],
) -> dict[str, Any]:
    return {
        "template_id": _row_id(template), "name": template.get("name"),
        "template_type": template.get("template_type"),
        "changed_member_ids": list(changed),
        "member_ids": sorted(_member_ids(rows)), "ownership": dict(ownership),
    }


__all__ = [
    "SCHEMA_VERSION", "append_metadata_template_members",
    "create_metadata_template", "delete_metadata_template",
    "metadata_template_input_error", "metadata_template_mutation_schema",
    "remove_metadata_template_members", "run_metadata_template_mutation",
]
