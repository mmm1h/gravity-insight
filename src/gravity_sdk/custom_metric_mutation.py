"""Marker-governed custom-metric definitions over the current confmetric routes."""

from __future__ import annotations

import copy
import json
from collections.abc import Mapping, Sequence
from typing import Any

from .actionable_error_values import actual_value
from .custom_metric_contracts import (
    CUSTOM_METRIC_DELETE,
    CUSTOM_METRIC_LIST,
    CUSTOM_METRIC_UPSERT,
)
from .errors import ContractChangedError, InputValidationError
from .mutation_lifecycle import MARKER_PREFIX, WRITE_LOCK, mutation_marker
from .mutation_ownership import create_user_owner, require_mutation_authority
from .report_mutation_support import marker
from .result_source import GOVERNED_PRODUCT, result_source


SCHEMA_VERSION = "gravity-insight.custom-metric-mutation.v1"
_ACTIONS = frozenset({"create", "update", "delete"})
_ACTION_FIELDS = {
    "create": (frozenset({"name", "formula"}), frozenset({"description", "display_format", "idempotency_key"})),
    "update": (frozenset({"metric_id", "name", "formula"}), frozenset({"description", "display_format"})),
    "delete": (frozenset({"metric_id"}), frozenset()),
}


def custom_metric_mutation_schema() -> dict[str, Any]:
    return {
        "schema_version": "gravity-insight.custom-metric-mutation-schema.v1",
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


def list_custom_metrics(
    client: Any, *, max_pages: int = 1_000, max_items: int = 100_000
) -> dict[str, Any]:
    _bound(max_pages, "max_pages", 1_000)
    _bound(max_items, "max_items", 100_000)
    return client.read_all(
        CUSTOM_METRIC_LIST,
        {"filters": [], "page": 1, "page_size": 5_000},
        max_pages=max_pages,
        max_items=max_items,
        max_workers=1,
    )


def run_custom_metric_mutation(
    client: Any, action: str, inputs: Mapping[str, Any], *, execute: bool = False
) -> dict[str, Any]:
    if action not in _ACTIONS:
        raise custom_metric_input_error(
            actual_value(action), actual_value(sorted(_ACTIONS)), "action",
            "Choose an action from the offline custom-metric mutation schema and rerun the dry-run.",
        )
    if not isinstance(inputs, Mapping):
        raise custom_metric_input_error(
            actual_value(type(inputs).__name__), "an input object", "inputs",
            "Pass an object matching the selected action schema and rerun the dry-run.",
        )
    required, optional = _ACTION_FIELDS[action]
    missing, unknown = required - set(inputs), set(inputs) - required - optional
    if missing or unknown:
        raise custom_metric_input_error(
            actual_value({"missing": sorted(missing), "unknown": sorted(unknown)}),
            actual_value({"required": sorted(required), "optional": sorted(optional)}),
            "inputs", "Correct the selected action fields and rerun the dry-run.",
        )
    functions = {"create": create_custom_metric, "update": update_custom_metric, "delete": delete_custom_metric}
    return functions[action](client, execute=execute, **dict(inputs))


def create_custom_metric(
    client: Any, *, name: str, formula: str, description: str = "",
    display_format: int = 1, idempotency_key: str | None = None,
    execute: bool = False,
) -> dict[str, Any]:
    selected = _definition(name, formula, description, display_format)
    key = None if idempotency_key is None else _text(idempotency_key, "idempotency_key", 128)
    selected_marker = mutation_marker("custom_metric", selected, idempotency_key=key)
    wire = _wire(selected, selected_marker)
    raw_preview = client._preview_mutation(CUSTOM_METRIC_UPSERT, wire)
    preview = _preview(raw_preview, {**selected, "marker": selected_marker}, "Create one adreport custom-metric definition.")
    if not execute:
        return preview
    with WRITE_LOCK:
        rows = _catalog(client)
        existing = _unique_marker(rows, selected_marker)
        if existing is not None:
            return _idempotent(existing)
        _require_unique_name(rows, selected["name"])
        mutation = client._execute_mutation(CUSTOM_METRIC_UPSERT, wire)
        created = _unique_marker(_catalog(client), selected_marker)
        if created is None:
            raise ContractChangedError(
                "custom-metric create acknowledgement did not round-trip its marker",
                next_action="Read the current custom-metric list and clean up the exact GSDK marker before another create.",
            )
        _verify_definition(created, selected, selected_marker)
        return _completed(preview, mutation, created, "created")


def update_custom_metric(
    client: Any, *, metric_id: str, name: str, formula: str,
    description: str = "", display_format: int = 1, execute: bool = False,
) -> dict[str, Any]:
    selected_id = _metric_id(metric_id, "metric_id")
    selected = _definition(name, formula, description, display_format)
    preview = _dependent_preview(
        CUSTOM_METRIC_UPSERT, {"metric_id": selected_id, **selected},
        "Replace the selected custom-metric definition while preserving its verified SDK marker.",
    )
    if not execute:
        return preview
    with WRITE_LOCK:
        rows = _catalog(client)
        preimage = _exact_id(rows, selected_id)
        selected_marker, ownership = _authority(client, preimage, selected_id)
        _require_unique_name(rows, selected["name"], except_id=selected_id)
        wire = {**_wire(selected, selected_marker), "id": selected_id}
        raw_preview = client._preview_mutation(CUSTOM_METRIC_UPSERT, wire)
        mutation = client._execute_mutation(CUSTOM_METRIC_UPSERT, wire)
        updated = _exact_id(_catalog(client), selected_id)
        _verify_definition(updated, selected, selected_marker)
        target = {**dict(updated), "ownership": ownership}
        return _completed(_preview(raw_preview, preview["target"], preview["impact"]), mutation, target, "updated", preimage)


def delete_custom_metric(
    client: Any, *, metric_id: str, execute: bool = False
) -> dict[str, Any]:
    selected_id = _metric_id(metric_id, "metric_id")
    preview = _dependent_preview(
        CUSTOM_METRIC_DELETE, {"metric_id": selected_id},
        "Delete the exact custom metric only after marker-or-owner readback.",
    )
    if not execute:
        return preview
    with WRITE_LOCK:
        preimage = _exact_id(_catalog(client), selected_id)
        selected_marker, ownership = _authority(client, preimage, selected_id)
        raw_preview = client._preview_mutation(CUSTOM_METRIC_DELETE, {"id": selected_id})
        mutation = client._execute_mutation(CUSTOM_METRIC_DELETE, {"id": selected_id})
        remaining = [row for row in _catalog(client) if _row_id(row) == selected_id]
        if remaining:
            raise ContractChangedError(
                "custom metric still exists after delete acknowledgement",
                next_action="Stop writes and inspect this exact metric ID before another explicit delete.",
            )
        target = {"metric_id": selected_id, "marker": selected_marker, "deleted": True, "ownership": ownership}
        return _completed(_preview(raw_preview, target, preview["impact"]), mutation, target, "deleted", preimage)


def _definition(name: Any, formula: Any, description: Any, display_format: Any) -> dict[str, Any]:
    selected_name = _text(name, "name", 128)
    selected_formula = _text(formula, "formula", 4_096)
    if not isinstance(description, str) or len(description) > 1_980 or MARKER_PREFIX in description:
        raise custom_metric_input_error(
            actual_value({"type": type(description).__name__, "length": len(description) if isinstance(description, str) else None, "contains_marker": isinstance(description, str) and MARKER_PREFIX in description}),
            "caller text without an SDK marker, at most 1980 characters", "description",
            "Remove marker-like text or shorten the description, then rerun the dry-run.",
        )
    if type(display_format) is not int or display_format not in range(1, 7):
        raise custom_metric_input_error(
            actual_value(display_format), "an integer from 1 through 6", "display_format",
            "Choose a frontend-supported display format and rerun the dry-run.",
        )
    return {"name": selected_name, "formula": selected_formula, "description": description.strip(), "display_format": display_format}


def _wire(
    definition: Mapping[str, Any], selected_marker: str | None
) -> dict[str, Any]:
    formula, display_format = definition["formula"], definition["display_format"]
    description = str(definition["description"])
    tip = (
        f"{selected_marker} | {description}"
        if selected_marker and description
        else selected_marker or description
    )
    return {
        "cname": definition["name"],
        "tip": tip,
        "formula": formula,
        "display_format": display_format,
        "config": json.dumps({"formula": formula, "display_format": display_format}, ensure_ascii=False, separators=(",", ":")),
    }


def _catalog(client: Any) -> list[Mapping[str, Any]]:
    envelope = list_custom_metrics(client)
    if not isinstance(envelope, Mapping) or envelope.get("status") not in {"success", "empty"} or envelope.get("error") is not None:
        raise ContractChangedError(
            "current custom-metric list is unavailable for mutation preflight",
            next_action="Restore the turbo custom-metric list contract before another write.",
        )
    if envelope.get("truncated") is True or envelope.get("next_page_input") not in (None, {}):
        raise ContractChangedError(
            "custom-metric mutation preflight received an incomplete catalog",
            next_action="Raise the bounded list limit before retrying; do not bypass preflight.",
        )
    data = envelope.get("data")
    rows = data.get("list") if isinstance(data, Mapping) else None
    if not isinstance(rows, list) or any(not isinstance(row, Mapping) for row in rows):
        raise ContractChangedError(
            "current custom-metric list no longer returns data.list objects",
            next_action="Stop writes until the current list response contract is re-verified.",
        )
    return rows


def _authority(
    client: Any, row: Mapping[str, Any], metric_id: str
) -> tuple[str | None, dict[str, Any]]:
    selected_marker = marker(row, ("tip", "cname"))
    decision = require_mutation_authority(
        client, marker=selected_marker, owner=create_user_owner(row),
        object_kind="custom metric", object_id=metric_id, field="metric_id",
    )
    return selected_marker, decision.public()


def _row_id(row: Mapping[str, Any]) -> str | None:
    value = row.get("id")
    if isinstance(value, str) and value.strip() and len(value) <= 128:
        return value
    return None


def _exact_id(rows: Sequence[Mapping[str, Any]], metric_id: str) -> Mapping[str, Any]:
    matches = [row for row in rows if _row_id(row) == metric_id]
    if len(matches) != 1:
        raise custom_metric_input_error(
            actual_value({"metric_id": metric_id, "matches": len(matches)}),
            "exactly one current custom metric", "metric_id",
            "Refresh the complete custom-metric list and choose one exact current ID before another write.",
        )
    return matches[0]


def _unique_marker(rows: Sequence[Mapping[str, Any]], selected_marker: str) -> Mapping[str, Any] | None:
    matches = [row for row in rows if marker(row, ("tip", "cname")) == selected_marker]
    if len(matches) > 1:
        raise ContractChangedError(
            "more than one custom metric has the same SDK marker",
            next_action="Inspect all exact marker matches and remove only confirmed duplicates before retrying.",
        )
    return matches[0] if matches else None


def _require_unique_name(rows: Sequence[Mapping[str, Any]], name: str, *, except_id: str | None = None) -> None:
    matches = [row for row in rows if row.get("cname") == name and _row_id(row) != except_id]
    if matches:
        raise custom_metric_input_error(
            actual_value(name), "a unique custom-metric name", "name",
            "Choose a unique name or reuse the existing SDK marker returned by the list.",
        )


def _verify_definition(
    row: Mapping[str, Any], definition: Mapping[str, Any], selected_marker: str | None
) -> None:
    observed_marker = marker(row, ("tip", "cname"))
    observed_format = row.get("display_format", row.get("format", row.get("show_format")))
    if observed_format is None and isinstance(row.get("config"), str):
        try:
            config = json.loads(str(row["config"]))
            observed_format = config.get("display_format") if isinstance(config, Mapping) else None
        except json.JSONDecodeError:
            observed_format = None
    observed = {
        "name": row.get("cname"), "formula": row.get("formula"),
        "display_format": observed_format, "marker": observed_marker,
    }
    expected = {
        "name": definition["name"], "formula": definition["formula"],
        "display_format": definition["display_format"], "marker": selected_marker,
    }
    if observed != expected:
        raise ContractChangedError(
            "custom-metric definition did not round-trip the acknowledged write",
            next_action="Stop writes and inspect the exact marked metric before cleanup or another update.",
        )


def _preview(raw: Mapping[str, Any], target: Mapping[str, Any], impact: str) -> dict[str, Any]:
    return {
        **copy.deepcopy(dict(raw)), "schema_version": SCHEMA_VERSION,
        "result_source": result_source(GOVERNED_PRODUCT), "dry_run": True,
        "write_sent": False, "confirmation_required": True,
        "automatic_retry": False, "target": copy.deepcopy(dict(target)),
        "impact": impact,
        "preconditions": ["Read the complete current list before writing.", "Require marker or proven owner before update/delete.", "Send one non-retried write.", "Read back the exact marker and definition."],
        "next_action": "Review this zero-network preview, then repeat the same action with execute=true or --execute.",
    }


def _dependent_preview(operation_id: str, target: Mapping[str, Any], impact: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION, "result_source": result_source(GOVERNED_PRODUCT),
        "ok": True, "status": "preview", "operation_id": operation_id,
        "effect": "mutation", "offline": True, "network_called": False,
        "write_sent": False, "dry_run": True, "confirmation_required": True,
        "automatic_retry": False, "attempts": 0,
        "target": copy.deepcopy(dict(target)), "impact": impact,
        "preconditions": ["Read the exact current preimage at execution time.", "Require marker or proven owner.", "Send one non-retried write.", "Independently read back the result."],
        "next_action": "Review the target, then repeat the same action with execute=true or --execute.",
    }


def _completed(preview: Mapping[str, Any], mutation: Mapping[str, Any], target: Mapping[str, Any], status: str, preimage: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION, "result_source": result_source(GOVERNED_PRODUCT),
        "ok": True, "status": status, "operation_id": mutation.get("operation_id"),
        "effect": "mutation", "offline": False, "network_called": True,
        "write_sent": True, "dry_run": False, "confirmation_required": False,
        "automatic_retry": False, "attempts": mutation.get("attempts", 1),
        "target": copy.deepcopy(dict(target)),
        "preimage": copy.deepcopy(dict(preimage)) if preimage is not None else None,
        "mutation": copy.deepcopy(dict(mutation)), "error": None,
        "impact": preview.get("impact"),
    }


def _idempotent(existing: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION, "result_source": result_source(GOVERNED_PRODUCT),
        "ok": True, "status": "already_exists", "operation_id": CUSTOM_METRIC_UPSERT,
        "effect": "mutation", "offline": False, "network_called": True,
        "write_sent": False, "attempts": 0, "idempotent_reuse": True,
        "target": copy.deepcopy(dict(existing)), "error": None,
    }


def _bound(value: Any, field: str, maximum: int) -> int:
    if type(value) is not int or not 1 <= value <= maximum:
        raise custom_metric_input_error(
            actual_value(value), f"an integer from 1 through {maximum}", field,
            f"Choose a bounded {field} and retry the list.",
        )
    return value


def _metric_id(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 128:
        raise custom_metric_input_error(
            actual_value(value), "a non-empty string ID returned by custom_metric.list", field,
            "Use the exact current custom-metric ID and rerun the dry-run.",
        )
    return value


def _text(value: Any, field: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise custom_metric_input_error(
            actual_value(value), f"non-empty text of at most {maximum} characters", field,
            f"Correct {field} within the documented bound and rerun the dry-run.",
        )
    return value


def custom_metric_input_error(
    actual: str, allowed: str, field: str, next_action: str
) -> InputValidationError:
    return InputValidationError(
        f"actual value: {actual}; allowed value: {allowed}",
        field=field,
        next_action=next_action,
    )


__all__ = [
    "SCHEMA_VERSION", "create_custom_metric", "custom_metric_mutation_schema",
    "delete_custom_metric", "list_custom_metrics", "run_custom_metric_mutation",
    "update_custom_metric",
]
