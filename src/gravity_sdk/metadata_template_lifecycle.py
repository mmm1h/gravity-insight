"""Small validation and envelope helpers for metadata-template mutations."""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from typing import Any

from .actionable_error_values import actual_value
from .errors import ContractChangedError, InputValidationError
from .metadata_template_wire import TEMPLATE_TYPES
from .result_source import GOVERNED_PRODUCT, result_source


SCHEMA_VERSION = "gravity-insight.metadata-template-mutation.v1"


def preview(
    raw: Mapping[str, Any], target: Mapping[str, Any], impact: str
) -> dict[str, Any]:
    return {
        **copy.deepcopy(dict(raw)), "schema_version": SCHEMA_VERSION,
        "result_source": result_source(GOVERNED_PRODUCT), "dry_run": True,
        "write_sent": False, "confirmation_required": True,
        "automatic_retry": False, "target": copy.deepcopy(dict(target)),
        "impact": impact,
        "preconditions": [
            "Read the complete current template or exact filtered membership.",
            "Require marker or proven owner before existing-template changes.",
            "Send one non-retried write and independently read back the result.",
        ],
        "next_action": "Review this zero-network preview, then repeat the same action and inputs with execute=true or --execute.",
    }


def dependent_preview(
    operation_id: str, target: Mapping[str, Any], impact: str
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "result_source": result_source(GOVERNED_PRODUCT), "ok": True,
        "status": "preview", "operation_id": operation_id,
        "effect": "mutation", "offline": True, "network_called": False,
        "write_sent": False, "dry_run": True, "confirmation_required": True,
        "automatic_retry": False, "attempts": 0,
        "target": copy.deepcopy(dict(target)), "impact": impact,
        "preconditions": [
            "Read the exact current preimage at execution time.",
            "Require marker or proven owner and independently read back the result.",
        ],
        "next_action": "Review the target, then repeat the same action and inputs with execute=true or --execute.",
    }


def completed(
    inspected: Mapping[str, Any], mutation: Mapping[str, Any],
    target: Mapping[str, Any], status: str,
    preimage: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "result_source": result_source(GOVERNED_PRODUCT), "ok": True,
        "status": status, "operation_id": mutation.get("operation_id"),
        "effect": "mutation", "offline": False, "network_called": True,
        "write_sent": True, "dry_run": False,
        "confirmation_required": False, "automatic_retry": False,
        "attempts": mutation.get("attempts", 1),
        "target": copy.deepcopy(dict(target)),
        "preimage": copy.deepcopy(dict(preimage)) if preimage is not None else None,
        "mutation": copy.deepcopy(dict(mutation)), "error": None,
        "impact": inspected.get("impact"),
    }


def idempotent(
    operation_id: str, template: Mapping[str, Any], selected_marker: str | None,
    members: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    ids = sorted(
        value for value in (row_id(row) for row in members) if value is not None
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "result_source": result_source(GOVERNED_PRODUCT), "ok": True,
        "status": "already_exists", "operation_id": operation_id,
        "effect": "mutation", "offline": False, "network_called": True,
        "write_sent": False, "attempts": 0, "idempotent_reuse": True,
        "target": {
            **copy.deepcopy(dict(template)), "marker": selected_marker,
            "member_ids": ids,
        },
        "error": None,
    }


def template_type(value: Any) -> str:
    if value not in TEMPLATE_TYPES:
        raise metadata_template_input_error(
            actual_value(value), actual_value(sorted(TEMPLATE_TYPES)),
            "template_type", "Choose a frontend-supported metadata template type.",
        )
    return str(value)


def identifier(value: Any, field: str) -> int:
    if type(value) is not int or value < 1:
        raise metadata_template_input_error(
            actual_value(value), "a positive integer catalog ID", field,
            f"Refresh the current catalog and choose one exact {field}.",
        )
    return value


def identifiers(value: Any, field: str) -> tuple[int, ...]:
    if (
        not isinstance(value, Sequence) or isinstance(value, (str, bytes))
        or not 1 <= len(value) <= 100
        or any(type(item) is not int or item < 1 for item in value)
        or len(set(value)) != len(value)
    ):
        raise metadata_template_input_error(
            actual_value(value), "1..100 unique positive integer catalog IDs", field,
            f"Refresh the catalog, deduplicate {field}, and rerun the dry-run.",
        )
    return tuple(value)


def text(value: Any, field: str, maximum: int, *, empty: bool = False) -> str:
    if (
        not isinstance(value, str) or len(value) > maximum
        or (not empty and not value.strip())
    ):
        raise metadata_template_input_error(
            actual_value(value), f"text of at most {maximum} characters" + ("" if empty else " and at least one non-space character"),
            field, f"Correct {field} within the documented bound and rerun the dry-run.",
        )
    return value.strip()


def boolean(value: Any, field: str) -> bool:
    if type(value) is not bool:
        raise metadata_template_input_error(
            actual_value(value), "true or false", field,
            f"Choose an explicit boolean {field} and rerun the dry-run.",
        )
    return value


def row_id(row: Mapping[str, Any]) -> int | None:
    value = row.get("id")
    return value if type(value) is int and value > 0 else None


def metadata_name(row: Mapping[str, Any], kind: str) -> str:
    value = row.get("name")
    if not isinstance(value, str) or not value:
        raise ContractChangedError(
            f"current {kind} no longer exposes a stable name",
            next_action=f"Stop writes until the {kind} identity contract is re-verified.",
        )
    return value


def member_names(rows: Sequence[Mapping[str, Any]]) -> set[str]:
    return {metadata_name(row, "template member") for row in rows}


def require_target_members(
    rows: Sequence[Mapping[str, Any]], targets: Sequence[Mapping[str, Any]],
    *, present: bool,
) -> None:
    observed = member_names(rows)
    expected = {metadata_name(row, "target metadata") for row in targets}
    failed = sorted(
        name for name in expected if (name in observed) is not present
    )
    if failed:
        state = "appear" if present else "disappear"
        raise ContractChangedError(
            f"metadata template member names did not {state} after acknowledgement",
            next_action="Stop writes and inspect the exact template membership before another action.",
        )


def metadata_template_input_error(
    actual: str, allowed: str, field: str, next_action: str
) -> InputValidationError:
    return InputValidationError(
        f"actual value: {actual}; allowed value: {allowed}",
        field=field, next_action=next_action,
    )


__all__ = [
    "SCHEMA_VERSION", "boolean", "completed", "dependent_preview",
    "idempotent", "identifier", "identifiers", "member_names",
    "metadata_name", "metadata_template_input_error", "preview",
    "require_target_members", "row_id", "template_type", "text",
]
