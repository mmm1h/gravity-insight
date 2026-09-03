"""Machine-readable Kanban action and whole-board preparation schemas."""

from __future__ import annotations

import copy
from collections.abc import Iterable
from typing import Any

from .dashboard_artifact_contract import SUBJECT_KINDS
from .kanban_limits import (
    DASHBOARD_DELETE_BATCH_MAX_ITEMS,
    DASHBOARD_LAYOUT_MAX_ITEMS,
    NOTE_BATCH_MAX_ITEMS,
    ORDER_ROOT_BATCH_MAX_ITEMS,
    REPORT_LINK_BATCH_MAX_ITEMS,
    REPORT_LINK_BATCH_MIN_ITEMS,
    REPORT_UNLINK_BATCH_MAX_ITEMS,
    REPORT_UNLINK_BATCH_MIN_ITEMS,
)


_POSITIVE_ID = {"type": "integer", "minimum": 1}
_NONNEGATIVE_ID = {"type": "integer", "minimum": 0}
_REPORT_ID = {
    "oneOf": [
        {"type": "integer", "minimum": 1},
        {"type": "string", "minLength": 1, "maxLength": 128},
    ]
}
_NOTE = {
    "type": "object",
    "required": ["content", "title"],
    "additionalProperties": False,
    "properties": {
        "title": {"type": "string", "minLength": 1, "maxLength": 96},
        "content": {"type": "string", "minLength": 1, "maxLength": 4_000},
        "idempotency_key": {
            "type": "string",
            "minLength": 1,
            "maxLength": 128,
        },
    },
}


def kanban_action_input_schema(
    action: str, required: Iterable[str], optional: Iterable[str]
) -> dict[str, Any]:
    fields = sorted({*required, *optional})
    return {
        "type": "object",
        "required": sorted(required),
        "additionalProperties": False,
        "properties": {
            field: _action_field_schema(action, field) for field in fields
        },
    }


def kanban_prepare_input_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["app_id", "target", "saved_definitions", "notes"],
        "additionalProperties": False,
        "properties": {
            "app_id": copy.deepcopy(_POSITIVE_ID),
            "target": {
                "oneOf": [_existing_target_schema(), _new_target_schema()]
            },
            "saved_definitions": {
                "type": "array",
                "minItems": 0,
                "maxItems": DASHBOARD_LAYOUT_MAX_ITEMS,
                "items": _saved_definition_schema(),
            },
            "notes": {
                "type": "array",
                "minItems": 0,
                "maxItems": NOTE_BATCH_MAX_ITEMS,
                "items": copy.deepcopy(_NOTE),
            },
        },
        "allOf": [
            {
                "x-crossFieldCardinality": {
                    "expression": "len(saved_definitions) + len(notes)",
                    "maximum": DASHBOARD_LAYOUT_MAX_ITEMS,
                    "scope": "desired_dashboard_layout",
                }
            }
        ],
    }


def kanban_collection_constraints() -> dict[str, Any]:
    return {
        "action_batch_limits": {
            "dashboard.delete-many.dashboard_ids": _batch_limit(
                1, DASHBOARD_DELETE_BATCH_MAX_ITEMS, "single_action_request"
            ),
            "dashboard.notes.replace.notes": _batch_limit(
                0, NOTE_BATCH_MAX_ITEMS, "single_action_request"
            ),
            "dashboard.order.save.order_detail": _batch_limit(
                1, ORDER_ROOT_BATCH_MAX_ITEMS, "single_action_request"
            ),
            "dashboard.report.link.report_ids": _batch_limit(
                REPORT_LINK_BATCH_MIN_ITEMS,
                REPORT_LINK_BATCH_MAX_ITEMS,
                "single_action_request",
            ),
            "dashboard.report.unlink.report_ids": _batch_limit(
                REPORT_UNLINK_BATCH_MIN_ITEMS,
                REPORT_UNLINK_BATCH_MAX_ITEMS,
                "single_action_request",
            ),
        },
        "dashboard_layout_capacity": {
            "type": "array",
            "maxItems": DASHBOARD_LAYOUT_MAX_ITEMS,
            "scope": "dashboard_total_layout",
            "wire_field": "ui_config",
            "wire_type": "string",
            "decoded_type": "array",
            "counts": ["reports", "notes", "other_layout_items"],
            "enforced_across_link_requests": True,
            "request_splitting_increases_capacity": False,
        },
        "provenance": {
            "classification": "sdk_governed_wire_contract",
            "upstream_limit_verified": False,
            "note": (
                "The SDK enforces these bounds before writes. Preserved evidence "
                "does not establish whether Gravity independently enforces the "
                "same numeric layout limit."
            ),
        },
    }


def _action_field_schema(action: str, field: str) -> dict[str, Any]:
    if field == "report_ids":
        maximum = (
            REPORT_LINK_BATCH_MAX_ITEMS
            if action == "dashboard.report.link"
            else REPORT_UNLINK_BATCH_MAX_ITEMS
        )
        minimum = (
            REPORT_LINK_BATCH_MIN_ITEMS
            if action == "dashboard.report.link"
            else REPORT_UNLINK_BATCH_MIN_ITEMS
        )
        return {
            "type": "array",
            "minItems": minimum,
            "maxItems": maximum,
            "uniqueItems": True,
            "items": copy.deepcopy(_REPORT_ID),
        }
    if field == "dashboard_ids":
        return {
            "type": "array",
            "minItems": 1,
            "maxItems": DASHBOARD_DELETE_BATCH_MAX_ITEMS,
            "uniqueItems": True,
            "items": copy.deepcopy(_POSITIVE_ID),
        }
    if field == "notes":
        return {
            "type": "array",
            "minItems": 0,
            "maxItems": NOTE_BATCH_MAX_ITEMS,
            "items": copy.deepcopy(_NOTE),
        }
    if field == "order_detail":
        return {
            "type": "array",
            "minItems": 1,
            "maxItems": ORDER_ROOT_BATCH_MAX_ITEMS,
            "items": {"type": "object"},
        }
    if field == "note_id":
        return {
            "type": "string",
            "pattern": "^notes_",
            "minLength": 7,
            "maxLength": 64,
        }
    if field == "folder_id":
        return copy.deepcopy(
            _NONNEGATIVE_ID if action.startswith("dashboard.") else _POSITIVE_ID
        )
    if field == "to_folder_id":
        return copy.deepcopy(_NONNEGATIVE_ID)
    if field.endswith("_id") or field in {"app_id", "uid"}:
        return copy.deepcopy(_POSITIVE_ID)
    if field == "name":
        return {"type": "string", "minLength": 1, "maxLength": 96}
    if field == "idempotency_key":
        return {"type": "string", "minLength": 1, "maxLength": 128}
    return {}


def _existing_target_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["mode", "space_id", "dashboard_id"],
        "additionalProperties": False,
        "properties": {
            "mode": {"const": "existing"},
            "space_id": copy.deepcopy(_POSITIVE_ID),
            "dashboard_id": copy.deepcopy(_POSITIVE_ID),
        },
    }


def _new_target_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["mode", "space_id", "folder_id", "name"],
        "additionalProperties": False,
        "properties": {
            "mode": {"const": "new"},
            "space_id": copy.deepcopy(_POSITIVE_ID),
            "folder_id": copy.deepcopy(_NONNEGATIVE_ID),
            "name": {"type": "string", "minLength": 1, "maxLength": 96},
            "idempotency_key": {
                "type": "string",
                "minLength": 1,
                "maxLength": 128,
            },
        },
    }


def _saved_definition_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["key", "name", "subject", "config"],
        "additionalProperties": False,
        "properties": {
            "key": {"type": "string", "minLength": 1, "maxLength": 128},
            "name": {"type": "string", "minLength": 1, "maxLength": 256},
            "subject": {"type": "string", "enum": sorted(SUBJECT_KINDS)},
            "config": {"type": "object"},
            "remark": {"type": "string", "maxLength": 1_980},
            "idempotency_key": {
                "type": "string",
                "minLength": 1,
                "maxLength": 128,
            },
            "report_id": copy.deepcopy(_REPORT_ID),
            "start": {"type": "string", "minLength": 1, "maxLength": 64},
            "end": {"type": "string", "minLength": 1, "maxLength": 64},
        },
    }


def _batch_limit(minimum: int, maximum: int, scope: str) -> dict[str, Any]:
    return {
        "type": "array",
        "minItems": minimum,
        "maxItems": maximum,
        "scope": scope,
    }


__all__ = [
    "kanban_action_input_schema",
    "kanban_collection_constraints",
    "kanban_prepare_input_schema",
]
