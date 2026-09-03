"""Caller-owned input and offline artifact compilation for Kanban board plans."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from .domains import ANALYSIS_QUERY_OPERATIONS
from .errors import (
    ErrorCode,
    ErrorDetail,
    InputValidationError,
    UnsupportedOperationError,
)
from .kanban_limits import DASHBOARD_LAYOUT_MAX_ITEMS
from .kanban_mutation_support import normalize_report_id, positive_id
from .mutation_lifecycle import mutation_marker
from .report_mutation_support import caller_text, optional_caller_text
from .saved_analysis_artifact import preflight_saved_definition, saved_artifact_mode
from .saved_analysis_support import decoded_config, supported_subject


_INPUT_FIELDS = frozenset({"app_id", "target", "saved_definitions", "notes"})
_SAVED_FIELDS = frozenset(
    {
        "key", "name", "subject", "config", "remark", "idempotency_key",
        "report_id", "start", "end",
    }
)
_TARGET_FIELDS = {
    "existing": frozenset({"mode", "space_id", "dashboard_id"}),
    "new": frozenset(
        {"mode", "space_id", "folder_id", "name", "idempotency_key"}
    ),
}


def board_input(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise InputValidationError(
            "Kanban board prepare input must be an object", field="input"
        )
    missing = sorted(_INPUT_FIELDS - set(value))
    unknown = sorted(set(value) - _INPUT_FIELDS)
    if missing or unknown:
        raise InputValidationError(
            f"Kanban board prepare input fields are invalid; missing={missing}, unknown={unknown}",
            field="input",
            next_action="Match the whole_board_prepare.input_schema from `kanban schema`.",
        )
    return dict(value)


def target_input(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise InputValidationError("target must be an object", field="target")
    mode = value.get("mode")
    if mode not in _TARGET_FIELDS:
        raise InputValidationError(
            "target.mode must be existing or new", field="target.mode"
        )
    allowed = _TARGET_FIELDS[mode]
    required = allowed - ({"idempotency_key"} if mode == "new" else set())
    missing, unknown = sorted(required - set(value)), sorted(set(value) - allowed)
    if missing or unknown:
        raise InputValidationError(
            f"target fields are invalid; missing={missing}, unknown={unknown}",
            field="target",
            next_action="Match exactly one target variant from `kanban schema`.",
        )
    space_id = positive_id(value.get("space_id"), "target.space_id")
    if mode == "existing":
        return {
            "mode": mode,
            "space_id": space_id,
            "dashboard_id": positive_id(
                value.get("dashboard_id"), "target.dashboard_id"
            ),
        }
    return _new_target(value, space_id)


def _new_target(value: Mapping[str, Any], space_id: int) -> dict[str, Any]:
    folder = value.get("folder_id")
    if type(folder) is not int or folder < 0:
        raise InputValidationError(
            "target.folder_id must be a non-negative integer",
            field="target.folder_id",
        )
    key = value.get("idempotency_key")
    if key is not None:
        key = caller_text(key, "target.idempotency_key", 128)
    return {
        "mode": "new",
        "space_id": space_id,
        "folder_id": folder,
        "name": caller_text(value.get("name"), "target.name", 96).strip(),
        "idempotency_key": key,
    }


def saved_inputs(value: Any) -> list[Mapping[str, Any]]:
    return _object_array(value, "saved_definitions", DASHBOARD_LAYOUT_MAX_ITEMS)


def note_inputs(value: Any) -> list[dict[str, Any]]:
    rows = _object_array(value, "notes", DASHBOARD_LAYOUT_MAX_ITEMS)
    return [_note(row, index) for index, row in enumerate(rows)]


def _note(row: Mapping[str, Any], index: int) -> dict[str, Any]:
    unknown = sorted(set(row) - {"title", "content", "idempotency_key"})
    if unknown:
        raise InputValidationError(
            f"note contains unknown fields: {unknown}",
            field=f"notes[{index}]",
            next_action="Keep only title, content, and optional idempotency_key.",
        )
    selected = {
        "title": caller_text(
            row.get("title"), f"notes[{index}].title", 96
        ).strip(),
        "content": caller_text(
            row.get("content"), f"notes[{index}].content", 4_000
        ).strip(),
    }
    if row.get("idempotency_key") is not None:
        selected["idempotency_key"] = caller_text(
            row["idempotency_key"], f"notes[{index}].idempotency_key", 128
        )
    return selected


def prepare_charts(
    values: Sequence[Mapping[str, Any]], *, app_id: int, workspace: Any
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    charts, prepared, keys = [], [], set()
    for index, value in enumerate(values):
        try:
            internal = _prepare_chart(
                value, index=index, app_id=str(app_id), workspace=workspace
            )
            if internal["key"] in keys:
                raise InputValidationError(
                    "saved definition keys must be unique",
                    field=f"saved_definitions[{index}].key",
                )
            keys.add(internal["key"])
            prepared.append(internal)
            charts.append(public_chart(internal))
        except (InputValidationError, UnsupportedOperationError) as exc:
            charts.append(_unsupported_chart(index, _safe_key(value, index), exc))
    _unique_materializations(prepared)
    return charts, prepared


def _prepare_chart(
    value: Mapping[str, Any], *, index: int, app_id: str, workspace: Any
) -> dict[str, Any]:
    identity = _chart_identity(value, index=index, app_id=app_id)
    config = value.get("config")
    if not isinstance(config, Mapping):
        raise InputValidationError(
            "saved definition config must be an object",
            field=f"saved_definitions[{index}].config",
        )
    decoded = decoded_config(config)
    prepared = preflight_saved_definition(
        {"subject": identity["subject"], "config": decoded},
        app=app_id,
        workspace=workspace,
        start=value.get("start"),
        end=value.get("end"),
    )
    config_text = _config_text(prepared)
    selected_marker = mutation_marker(
        "saved_analysis",
        {
            "app_id": app_id,
            "name": identity["name"],
            "subject": identity["subject"],
            "config": config_text,
        },
        idempotency_key=identity["idempotency_key"],
    )
    return {
        **identity,
        "index": index,
        "operation_id": ANALYSIS_QUERY_OPERATIONS[identity["kind"]],
        "artifact_mode": saved_artifact_mode(
            {"subject": identity["subject"], "config": decoded}
        ),
        "config_text": config_text,
        "marker": selected_marker,
        "report_id": _optional_report_id(value, index),
        "start": value.get("start"),
        "end": value.get("end"),
    }


def _chart_identity(
    value: Mapping[str, Any], *, index: int, app_id: str
) -> dict[str, Any]:
    unknown = sorted(set(value) - _SAVED_FIELDS)
    missing = sorted({"key", "name", "subject", "config"} - set(value))
    if missing or unknown:
        raise InputValidationError(
            f"saved definition fields are invalid; missing={missing}, unknown={unknown}",
            field=f"saved_definitions[{index}]",
            next_action="Match the saved_definitions item schema and prepare again.",
        )
    subject = value.get("subject")
    key = value.get("idempotency_key")
    if key is not None:
        key = caller_text(key, f"saved_definitions[{index}].idempotency_key", 128)
    return {
        "key": caller_text(value.get("key"), f"saved_definitions[{index}].key", 128),
        "name": caller_text(value.get("name"), f"saved_definitions[{index}].name", 256).strip(),
        "subject": subject,
        "kind": supported_subject(subject),
        "remark": optional_caller_text(
            value.get("remark", ""), f"saved_definitions[{index}].remark", 1_980
        ),
        "idempotency_key": key,
        "app_id": app_id,
    }


def _optional_report_id(value: Mapping[str, Any], index: int) -> str | None:
    if "report_id" not in value:
        return None
    selected = normalize_report_id(value["report_id"])
    if selected is None:
        raise InputValidationError(
            "report_id must be a positive integer or bounded opaque string",
            field=f"saved_definitions[{index}].report_id",
        )
    return selected


def _config_text(value: Mapping[str, Any]) -> str:
    return json.dumps(
        value, ensure_ascii=False, allow_nan=False, sort_keys=True,
        separators=(",", ":"),
    )


def _unique_materializations(values: Sequence[Mapping[str, Any]]) -> None:
    for field in ("name", "marker"):
        seen: set[str] = set()
        for item in values:
            selected = str(item[field])
            if selected in seen:
                raise InputValidationError(
                    f"saved definition {field} values must be unique",
                    field=f"saved_definitions[{item['index']}].{field}",
                    next_action="Remove the duplicate desired definition before any write.",
                )
            seen.add(selected)


def public_chart(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value[key]
        for key in (
            "index", "key", "name", "subject", "kind", "operation_id",
            "artifact_mode", "marker",
        )
    } | {
        "supported": True,
        "validation_status": "valid_offline",
        "error": None,
    }


def _unsupported_chart(
    index: int, key: str, error: InputValidationError | UnsupportedOperationError
) -> dict[str, Any]:
    raw_code = getattr(error.code, "value", error.code)
    code = ErrorCode.INPUT_INVALID if raw_code == ErrorCode.INPUT_INVALID.value else ErrorCode.UNSUPPORTED
    field = error.field or "config"
    if not field.startswith("saved_definitions["):
        field = f"saved_definitions[{index}].{field}"
    detail = ErrorDetail.create(
        code,
        "Saved Analysis definition cannot be materialized through a proven artifact contract.",
        field=field,
        next_action=(
            "Correct this exact structural path or keep the complete chart out of "
            "the board plan; no grouping, predicate, metric, or note was removed."
        ),
        write_sent=False,
        automatic_retry=False,
    )
    return {
        "index": index, "key": key, "name": "unsupported",
        "subject": "unsupported", "kind": None, "operation_id": None,
        "artifact_mode": None, "supported": False,
        "validation_status": "unsupported", "error": detail.to_dict(),
    }


def _object_array(value: Any, field: str, maximum: int) -> list[Mapping[str, Any]]:
    if (
        not isinstance(value, Sequence) or isinstance(value, (str, bytes))
        or len(value) > maximum or any(not isinstance(item, Mapping) for item in value)
    ):
        raise InputValidationError(
            f"{field} must be an array of at most {maximum} objects", field=field
        )
    return [dict(item) for item in value]


def _safe_key(value: Mapping[str, Any], index: int) -> str:
    selected = value.get("key")
    if isinstance(selected, str) and 1 <= len(selected.strip()) <= 128:
        return selected.strip()
    return f"item-{index}"


__all__ = [
    "board_input", "note_inputs", "prepare_charts", "public_chart",
    "saved_inputs", "target_input",
]
