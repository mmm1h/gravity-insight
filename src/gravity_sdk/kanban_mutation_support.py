"""Hierarchy, marker, preview, and readback helpers for Kanban writes."""

from __future__ import annotations

import copy
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .actionable_error_values import actual_value
from .errors import (
    ContractChangedError,
    InputValidationError,
    MutationReadbackError,
    ObjectAlreadyExistsError,
)
from .kanban_mutation_contracts import DETAIL, SPACE_MEMBERS, TREE
from .mutation_lifecycle import (
    MARKER_PREFIX,
    WRITE_LOCK,
    mutation_digest as digest,
    mutation_marker as segment_marker,
)
from .mutation_ownership import (
    OwnerReference,
    create_user_owner,
    creator_owner,
    require_mutation_authority,
)
from .result_source import GOVERNED_PRODUCT, result_source


SCHEMA_VERSION = "gravity-insight.kanban-mutation.v1"
_MARKER = re.compile(r"GSDK-[0-9a-f]{12}")
_SUCCESS = frozenset({"success", "empty", "contract_changed_additive"})


@dataclass(frozen=True)
class KanbanObject:
    kind: str
    object_id: int
    name: str
    space_id: int
    folder_id: int | None = None
    owner_id: str | None = None
    owner_name: str | None = None

    def public(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "id": self.object_id,
            "name": self.name,
            "space_id": self.space_id,
            "folder_id": self.folder_id,
            "marker": marker_from_text(self.name),
            "create_user_id": self.owner_id,
            "create_user_name": self.owner_name,
        }


def positive_id(value: Any, field: str) -> int:
    if type(value) is not int or value < 1:
        raise InputValidationError(
            f"actual value: {actual_value(value)}; allowed value: a positive integer identifier",
            field=field,
            next_action=f"Use the exact positive {field} returned by the Kanban tree/detail read and run dry-run again.",
        )
    return value


def nonnegative_id(value: Any, field: str) -> int:
    if type(value) is not int or value < 0:
        raise InputValidationError(
            f"actual value: {actual_value(value)}; allowed value: a non-negative integer identifier",
            field=field,
            next_action=f"Use 0 for the ungrouped destination or an exact positive {field} from the Kanban tree, then run dry-run again.",
        )
    return value


def caller_text(value: Any, field: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise InputValidationError(
            f"actual value: {actual_value({'type': type(value).__name__, 'length': len(value) if isinstance(value, str) else None})}; allowed range: 1 through {maximum} characters",
            field=field,
            next_action=f"Provide non-empty {field} text within the documented limit and run dry-run again.",
        )
    if MARKER_PREFIX in value:
        raise InputValidationError(
            f"actual value: {actual_value({'contains_sdk_marker': True})}; allowed value: caller text without an SDK marker",
            field=field,
            next_action="Remove marker-like text; the SDK owns marker generation and preservation, then run dry-run again.",
        )
    return value.strip()


def marked_name(
    kind: str,
    name: Any,
    semantic: Mapping[str, Any],
    *,
    idempotency_key: str | None,
) -> tuple[str, str]:
    selected = caller_text(name, "name", 96)
    marker = segment_marker(kind, semantic, idempotency_key=idempotency_key)
    return f"{selected} | {marker}", marker


def preserve_marker(name: Any, previous: str) -> str:
    selected = caller_text(name, "name", 96)
    marker = marker_from_text(previous)
    return selected if marker is None else f"{selected} | {marker}"


def marker_from_text(value: Any) -> str | None:
    match = _MARKER.search(value) if isinstance(value, str) else None
    return match.group(0) if match is not None else None


def read_tree(client: Any, app_id: int) -> tuple[list[Mapping[str, Any]], list[KanbanObject]]:
    value = client.read(TREE, {"app_id": str(app_id)})
    data = value.get("data") if isinstance(value, Mapping) else None
    if (
        not isinstance(value, Mapping)
        or value.get("error") is not None
        or value.get("status") not in _SUCCESS
        or not isinstance(data, list)
        or any(not isinstance(row, Mapping) for row in data)
    ):
        raise MutationReadbackError(
            "Kanban tree could not be read completely for mutation preflight/readback",
            next_action="Restore `analysis.dashboard.tree` for this exact App and inspect current state before another write.",
        )
    objects = _flatten_tree(data)
    identities = [
        (item.kind, item.space_id if item.kind == "folder" else None, item.object_id)
        for item in objects
    ]
    if len(identities) != len(set(identities)):
        raise ContractChangedError(
            "Kanban tree returned duplicate resource identities",
            next_action="Stop Kanban writes until the tree identity contract is re-verified.",
        )
    return data, objects


def _flatten_tree(rows: Sequence[Mapping[str, Any]]) -> list[KanbanObject]:
    result: list[KanbanObject] = []
    stack: list[tuple[Mapping[str, Any], int | None, int | None, bool, int]] = [
        (row, None, None, True, 0) for row in reversed(rows)
    ]
    while stack:
        node, inherited_space, inherited_folder, root, depth = stack.pop()
        if depth > 16:
            raise ContractChangedError(
                "Kanban tree exceeded the supported hierarchy depth",
                next_action="Stop Kanban writes until the upstream hierarchy is reviewed and the bounded walker is updated.",
            )
        object_id, name, space_id, folder, kind, owner_id, owner_name = _tree_node_identity(
            node, inherited_space, root
        )
        current_folder = object_id if folder else inherited_folder
        result.append(
            KanbanObject(
                kind,
                object_id,
                name,
                space_id,
                None if kind != "dashboard" else inherited_folder,
                owner_id,
                owner_name,
            )
        )
        children: list[tuple[Mapping[str, Any], int | None]] = []
        direct = node.get("folder_or_dashboard")
        if direct is not None:
            children.extend(
                (item, current_folder if folder else inherited_folder)
                for item in _child_rows(direct, "folder_or_dashboard")
            )
        dashboards = node.get("dashboards")
        if dashboards is not None:
            children.extend((item, current_folder) for item in _child_rows(dashboards, "dashboards"))
        stack.extend(
            (item, space_id, parent_folder, False, depth + 1)
            for item, parent_folder in reversed(children)
        )
    return result


def _tree_node_identity(
    node: Mapping[str, Any], inherited_space: int | None, root: bool
) -> tuple[int, str, int, bool, str, str | None, str | None]:
    folder = not root and (node.get("is_folder") is True or "dashboards" in node)
    object_id = (
        _response_nonzero_id(node.get("id"), "tree.folder.id")
        if folder
        else _response_id(node.get("id"), "tree.id")
    )
    name = _response_text(node.get("name"), "tree.name")
    space_id = object_id if root else _response_id(
        node.get("space_id", inherited_space), "tree.space_id"
    )
    kind = "space" if root else "folder" if folder else "dashboard"
    owner = create_user_owner(node)
    return object_id, name, space_id, folder, kind, owner.owner_id, owner.owner_name


def _child_rows(value: Any, field: str) -> list[Mapping[str, Any]]:
    rows = [value] if isinstance(value, Mapping) else value if isinstance(value, list) else None
    if rows is None or any(not isinstance(item, Mapping) for item in rows):
        raise ContractChangedError(
            f"Kanban tree {field} changed shape",
            next_action="Stop Kanban writes until the recursive tree contract is re-verified.",
        )
    return list(rows)


def find_object(objects: Sequence[KanbanObject], kind: str, object_id: int) -> KanbanObject:
    matches = [item for item in objects if item.kind == kind and item.object_id == object_id]
    if len(matches) != 1:
        raise MutationReadbackError(
            f"exact {kind} preimage is missing or ambiguous",
            next_action=f"Read the Kanban tree and choose one exact {kind} id before another write.",
        )
    return matches[0]


def require_owned(
    client: Any,
    app_id: int,
    target: KanbanObject,
    *,
    detail: Mapping[str, Any] | None = None,
) -> Any:
    marker = marker_from_text(target.name)
    owner = (
        OwnerReference(target.owner_id, target.owner_name, "create_user_id")
        if target.kind == "dashboard"
        else OwnerReference(None, None, "not_exposed")
    )
    if marker is None and target.kind == "space":
        owner = read_space_owner(client, app_id, target.object_id)
    elif marker is None and target.kind == "dashboard" and owner.owner_id is None:
        selected = detail or read_detail(
            client, app_id, target.space_id, target.object_id
        )
        owner = create_user_owner(selected)
    return require_mutation_authority(
        client,
        marker=marker,
        owner=owner,
        object_kind=f"Kanban {target.kind}",
        object_id=target.object_id,
        field=f"{target.kind}_id",
    )


def require_dashboard_authority(
    client: Any,
    detail: Mapping[str, Any],
    dashboard_id: int,
) -> Any:
    return require_mutation_authority(
        client,
        marker=marker_from_text(detail.get("name")),
        owner=create_user_owner(detail),
        object_kind="Kanban dashboard",
        object_id=dashboard_id,
        field="dashboard_id",
    )


def read_space_owner(client: Any, app_id: int, space_id: int) -> OwnerReference:
    value = client.read(
        SPACE_MEMBERS, {"app_id": str(app_id), "space_id": str(space_id)}
    )
    data = value.get("data") if isinstance(value, Mapping) else None
    if (
        not isinstance(value, Mapping)
        or value.get("error") is not None
        or value.get("status") not in _SUCCESS
        or not isinstance(data, Mapping)
    ):
        raise MutationReadbackError(
            "Kanban space creator could not be read for ownership preflight",
            next_action="Restore the exact space-members read before another space mutation.",
        )
    return creator_owner(data.get("creator"))


def descendants(objects: Sequence[KanbanObject], target: KanbanObject) -> list[KanbanObject]:
    if target.kind == "space":
        return [item for item in objects if item.kind != "space" and item.space_id == target.object_id]
    if target.kind == "folder":
        return [
            item
            for item in objects
            if item.kind == "dashboard"
            and item.space_id == target.space_id
            and item.folder_id == target.object_id
        ]
    return []


def read_detail(client: Any, app_id: int, space_id: int, dashboard_id: int) -> Mapping[str, Any]:
    value = client.read(
        DETAIL,
        {"app_id": str(app_id), "space_id": str(space_id), "id": str(dashboard_id)},
    )
    data = value.get("data") if isinstance(value, Mapping) else None
    if (
        not isinstance(value, Mapping)
        or value.get("error") is not None
        or value.get("status") not in _SUCCESS
        or not isinstance(data, Mapping)
    ):
        raise MutationReadbackError(
            "dashboard detail could not be read for mutation preflight/readback",
            next_action="Read the exact dashboard coordinates and resolve the upstream error before another write.",
        )
    if _response_id(data.get("id"), "dashboard.id") != dashboard_id:
        raise ContractChangedError(
            "dashboard detail identity changed",
            next_action="Stop Kanban writes until dashboard detail identity is re-verified.",
        )
    return data


def detail_notes(detail: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    config = detail.get("ui_config")
    try:
        decoded = json.loads(config) if isinstance(config, str) else config
    except json.JSONDecodeError as exc:
        raise ContractChangedError(
            "dashboard ui_config is no longer valid JSON",
            next_action="Stop note writes until the dashboard layout contract is repaired.",
        ) from exc
    if decoded in (None, ""):
        return []
    if not isinstance(decoded, list) or any(not isinstance(item, Mapping) for item in decoded):
        raise ContractChangedError(
            "dashboard ui_config no longer contains a layout array",
            next_action="Stop note writes until the dashboard layout contract is re-verified.",
        )
    return [item for item in decoded if item.get("subject") == "notes"]


def report_list(detail: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    reports = detail.get("even_report", [])
    if not isinstance(reports, list) or any(not isinstance(item, Mapping) for item in reports):
        raise ContractChangedError(
            "dashboard even_report changed shape",
            next_action="Stop dashboard content writes until the embedded report contract is re-verified.",
        )
    return [dict(item) for item in reports]


def mutation_preview(
    raw: Mapping[str, Any],
    *,
    target: Mapping[str, Any],
    impact: str,
    cascade: Mapping[str, Any] | None = None,
    preimage: Mapping[str, Any] | None = None,
    reads_performed: int = 0,
) -> dict[str, Any]:
    result = {
        **copy.deepcopy(dict(raw)),
        "schema_version": SCHEMA_VERSION,
        "status": "preview",
        "result_source": result_source(GOVERNED_PRODUCT),
        "offline": reads_performed == 0,
        "network_called": reads_performed > 0,
        "write_sent": False,
        "read_attempts": reads_performed,
        "dry_run": True,
        "confirmation_required": True,
        "target": copy.deepcopy(dict(target)),
        "impact": impact,
        "preimage": copy.deepcopy(dict(preimage)) if preimage is not None else None,
        "preconditions": [
            "Re-read the exact target and hierarchy before sending a write.",
            "Refuse unless the target carries GSDK-<12 hex> or its proven owner equals the authenticated gravity_id.",
            "Send at most one non-retried mutation through an exact one-shot authorization.",
            "Read the affected hierarchy/detail after acknowledgement and verify the promised effect.",
        ],
        "automatic_retry": False,
        "next_action": "Review the exact request and impact counts, then repeat the same action/inputs with execute=true or --execute.",
    }
    if cascade is not None:
        result["cascade"] = copy.deepcopy(dict(cascade))
    result["preview_fingerprint"] = digest(result)
    return result


def completed(
    preview: Mapping[str, Any],
    mutation: Mapping[str, Any],
    target: Mapping[str, Any],
    *,
    status: str,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "result_source": result_source(GOVERNED_PRODUCT),
        "ok": True,
        "status": status,
        "operation_id": mutation.get("operation_id"),
        "effect": "mutation",
        "offline": False,
        "network_called": True,
        "write_sent": True,
        "dry_run": False,
        "confirmation_required": False,
        "automatic_retry": False,
        "attempts": mutation.get("attempts", 1),
        "target": copy.deepcopy(dict(target)),
        "impact": copy.deepcopy(preview.get("impact")),
        "cascade": copy.deepcopy(preview.get("cascade")),
        "preview_fingerprint": preview.get("preview_fingerprint"),
        "mutation": copy.deepcopy(dict(mutation)),
        "error": None,
    }


def idempotent(operation_id: str, target: KanbanObject) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "result_source": result_source(GOVERNED_PRODUCT),
        "ok": True,
        "status": "already_exists",
        "operation_id": operation_id,
        "effect": "mutation",
        "offline": False,
        "network_called": True,
        "write_sent": False,
        "attempts": 0,
        "idempotent_reuse": True,
        "target": target.public(),
        "error": None,
    }


def create_preflight(
    objects: Sequence[KanbanObject], kind: str, marker: str, wire_name: str
) -> KanbanObject | None:
    owned = [item for item in objects if item.kind == kind and marker_from_text(item.name) == marker]
    if len(owned) > 1:
        raise MutationReadbackError(
            f"more than one {kind} has the same SDK marker",
            next_action="List the marker matches and remove only confirmed duplicates before retrying.",
        )
    if owned:
        if owned[0].name != wire_name:
            raise ObjectAlreadyExistsError(
                f"actual value: {actual_value(owned[0].name)}; allowed value: {actual_value(wire_name)}",
                field="name",
                next_action=f"Reuse the marked {kind} or choose a new idempotency key and name.",
            )
        return owned[0]
    if any(item.kind == kind and item.name == wire_name for item in objects):
        raise ObjectAlreadyExistsError(
            f"actual value: {actual_value(wire_name)}; allowed value: a unique {kind} name",
            field="name",
            next_action="Choose a unique visible name and run dry-run again.",
        )
    return None


def _response_id(value: Any, field: str) -> int:
    selected = int(value) if isinstance(value, str) and value.isdecimal() else value
    if type(selected) is not int or selected < 1:
        raise ContractChangedError(
            f"{field} changed type or range",
            next_action="Stop Kanban writes until the hierarchy identity contract is re-verified.",
        )
    return selected


def _response_nonzero_id(value: Any, field: str) -> int:
    signed_decimal = isinstance(value, str) and value.lstrip("-").isdecimal()
    selected = int(value) if signed_decimal else value
    if type(selected) is not int or selected == 0:
        raise ContractChangedError(
            f"{field} changed type or range",
            next_action="Stop Kanban writes until the system-folder identity contract is re-verified.",
        )
    return selected


def _response_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 256:
        raise ContractChangedError(
            f"{field} changed type or range",
            next_action="Stop Kanban writes until the hierarchy display contract is re-verified.",
        )
    return value


__all__ = [
    "KanbanObject",
    "SCHEMA_VERSION",
    "WRITE_LOCK",
    "caller_text",
    "completed",
    "create_preflight",
    "descendants",
    "detail_notes",
    "find_object",
    "idempotent",
    "marked_name",
    "marker_from_text",
    "mutation_preview",
    "nonnegative_id",
    "positive_id",
    "preserve_marker",
    "read_detail",
    "read_space_owner",
    "read_tree",
    "report_list",
    "require_dashboard_authority",
    "require_owned",
]
