"""Validation and safe projection helpers for saved Analysis replay."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from .dashboard_artifact_contract import SUBJECT_KINDS
from .errors import (
    ContractChangedError,
    ErrorCode,
    GravityInsightError,
    InputValidationError,
    UnsupportedOperationError,
)
from .workspace import Workspace, load_workspace
from .actionable_error_values import actual_value


DEFAULT_MAX_PAGES = 1_000
DEFAULT_MAX_ITEMS = 100_000
DEFAULT_MAX_WORKERS = 6
MAX_WORKERS = 24
MAX_CONFIG_BYTES = 1_000_000
DEFINITION_FIELDS = frozenset(
    {"id", "app_id", "name", "subject", "modify_time", "config"}
)
SUCCESS_STATUSES = frozenset({"success", "empty"})
RESULT_STATUSES = SUCCESS_STATUSES | frozenset(
    {
        "error",
        "partial",
        "contract_changed",
        "contract_changed_additive",
        "semantic_error",
        "unavailable",
        "parent_required",
        "permission_unavailable",
    }
)
KNOWN_ERROR_CODES = frozenset(item.value for item in ErrorCode)
REPLAY_STATUSES = frozenset(
    {"unchecked", "supported", "unsupported", "requires_window"}
)


def replay_capability(status: str) -> dict[str, Any]:
    """Keep the nullable capability flag consistent with its evidence status."""

    if status not in REPLAY_STATUSES:
        raise ContractChangedError("saved Analysis replay status is invalid")
    supported = None if status == "unchecked" else status == "supported"
    return {"replay_supported": supported, "replay_status": status}


def normalize_definition(
    value: Mapping[str, Any], *, expected_app_id: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    normalized = _definition_fields(value)
    supplied_app = value.get("app_id")
    if (
        supplied_app is not None
        and identifier(supplied_app, "definition.app_id") != expected_app_id
    ):
        raise InputValidationError(
            "saved Analysis definition app_id does not match the selected workspace App",
            field="definition.app_id", next_action="Set definition.app_id to the selected workspace App.",
        )
    normalized["app_id"] = expected_app_id
    return normalized, safe_metadata(normalized, app_id=expected_app_id)


def validate_definition_shape(value: Any) -> None:
    """Validate caller-owned definition structure without a client or workspace."""

    _definition_fields(value)


def _definition_fields(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise InputValidationError(
            f"actual value: {actual_value(value)}; " + ("saved Analysis definition must be an object"), field="definition"
        )
    unknown = sorted(set(value) - DEFINITION_FIELDS)
    if unknown:
        raise InputValidationError(
            "saved Analysis definition contains unsupported fields: "
            + ", ".join(unknown),
            field="definition", next_action="Remove unsupported definition fields and retry.",
        )
    if "subject" not in value or "config" not in value:
        raise InputValidationError(
            f"actual value: {actual_value(value)}; " + ("saved Analysis definition requires subject and config"),
            field="definition",
        )
    supported_subject(value.get("subject"))
    decoded_config(value.get("config"))
    normalized: dict[str, Any] = {
        "subject": value["subject"],
        "config": value["config"],
    }
    if "id" in value:
        normalized["id"] = identifier(value["id"], "definition.id")
    if "name" in value:
        normalized["name"] = text(value["name"], "definition.name")
    if "modify_time" in value:
        normalized["modify_time"] = text(
            value["modify_time"], "definition.modify_time"
        )
    if "app_id" in value:
        identifier(value["app_id"], "definition.app_id")
    return normalized


def catalog_rows(envelope: Mapping[str, Any], app_id: str) -> list[dict[str, Any]]:
    data = envelope.get("data")
    rows = data.get("list") if isinstance(data, Mapping) else None
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        raise ContractChangedError(
            "saved Analysis catalog did not match its projected contract",
            next_action=(
                "Stop catalog automation until the saved Analysis list operation "
                "is re-verified."
            ),
        )
    result: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for raw in rows:
        if not isinstance(raw, Mapping):
            raise ContractChangedError(
                "saved Analysis catalog contains a malformed item"
            )
        try:
            item_id = identifier(raw.get("id"), "catalog.id")
            name = text(raw.get("name"), "catalog.name")
            subject = text(raw.get("subject"), "catalog.subject")
            row_app = identifier(raw.get("app_id"), "catalog.app_id")
            modified = (
                text(raw["modify_time"], "catalog.modify_time")
                if "modify_time" in raw
                else None
            )
        except InputValidationError:
            raise ContractChangedError(
                "saved Analysis catalog contains an invalid projected item"
            ) from None
        if row_app != app_id:
            raise ContractChangedError(
                "saved Analysis catalog returned an item for a different App"
            )
        if item_id in seen_ids:
            raise ContractChangedError(
                "saved Analysis catalog contains a duplicate identity"
            )
        seen_ids.add(item_id)
        item = {
            key: raw[key]
            for key in (
                "id", "app_id", "name", "subject", "create_time", "modify_time",
                "create_user_id", "create_user_name", "update_user_id",
                "update_user_name", "is_deleted", "remark",
            )
            if key in raw
        }
        item.update(
            {
                "id": item_id,
                "app_id": row_app,
                "name": name,
                "subject": subject,
                "kind": SUBJECT_KINDS.get(subject),
                "subject_supported": subject in SUBJECT_KINDS,
                **replay_capability("unchecked"),
            }
        )
        if modified is not None:
            item["modify_time"] = modified
        result.append(item)
    return result


def select_reference(
    rows: Sequence[Mapping[str, Any]], reference: str | int | Mapping[str, Any]
) -> dict[str, Any]:
    mode, value = normalize_reference(reference)
    if mode == "id":
        matches = [row for row in rows if row.get("id") == value]
    elif mode == "name":
        matches = [row for row in rows if row.get("name") == value]
    else:
        matches = [
            row
            for row in rows
            if row.get("id") == value or row.get("name") == value
        ]
    unique = {str(row.get("id")): row for row in matches}
    if not unique:
        raise InputValidationError(
            f"actual value: {actual_value(value)}; " + ("saved Analysis reference was not found in the selected App"),
            field="reference",
            next_action=(
                "List saved analyses and retry with an explicit id or exact name."
            ),
        )
    if len(unique) != 1:
        raise InputValidationError(
            f"actual value: {actual_value(value)}; " + ("saved Analysis reference is ambiguous in the selected App"),
            field="reference",
            next_action="Retry with an explicit `{\"id\": \"...\"}` reference.",
        )
    return dict(next(iter(unique.values())))


def normalize_reference(value: Any) -> tuple[str, str]:
    if isinstance(value, Mapping):
        if set(value) not in ({"id"}, {"name"}):
            raise InputValidationError(
                f"actual value: {actual_value(value)}; " + ("saved Analysis reference must contain exactly id or name"),
                field="reference",
            )
        mode = next(iter(value))
        selected = (
            identifier(value[mode], f"reference.{mode}")
            if mode == "id"
            else text(value[mode], f"reference.{mode}")
        )
        return mode, selected
    if isinstance(value, int) and not isinstance(value, bool):
        return "id", identifier(value, "reference")
    return "auto", text(value, "reference")


def supported_subject(value: Any) -> str:
    if not isinstance(value, str) or value not in SUBJECT_KINDS:
        raise UnsupportedOperationError(
            "saved Analysis subject is not supported by deterministic replay",
            field="subject",
            next_action=(
                "Use analysis_event, analysis_funnel, analysis_retention, "
                "analysis_scatter, or analysis_user_property after its config "
                "passes Analysis Spec v1."
            ),
        )
    return SUBJECT_KINDS[value]


def decoded_config(value: Any) -> Mapping[str, Any]:
    try:
        if isinstance(value, str):
            if not value or len(value.encode("utf-8")) > MAX_CONFIG_BYTES:
                raise ValueError
            decoded = json.loads(value)
        elif isinstance(value, Mapping):
            encoded = json.dumps(value, ensure_ascii=False, allow_nan=False)
            if len(encoded.encode("utf-8")) > MAX_CONFIG_BYTES:
                raise ValueError
            decoded = json.loads(encoded)
        else:
            raise ValueError
    except (TypeError, ValueError, UnicodeError, json.JSONDecodeError):
        raise UnsupportedOperationError(
            "saved Analysis config is not a bounded JSON object supported by Analysis Spec v1",
            field="config",
            next_action=(
                "Export or provide the definition as a valid compact Analysis "
                "Spec v1 object."
            ),
        ) from None
    if not isinstance(decoded, Mapping):
        raise UnsupportedOperationError(
            "saved Analysis config is not an Analysis Spec v1 object", field="config"
        )
    return decoded


def safe_metadata(value: Mapping[str, Any], *, app_id: str) -> dict[str, Any]:
    subject = value.get("subject")
    result: dict[str, Any] = {}
    for key in ("id", "name", "subject", "modify_time"):
        item = value.get(key)
        if isinstance(item, (str, int)) and not isinstance(item, bool):
            rendered = str(item).strip()
            if rendered and len(rendered) <= 256:
                result[key] = item
    result.update(
        {
            "app_id": app_id,
            "kind": SUBJECT_KINDS.get(subject) if isinstance(subject, str) else None,
            "subject_supported": subject in SUBJECT_KINDS,
            **replay_capability("unchecked"),
        }
    )
    return result


def safe_query_envelope(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractChangedError(
            "saved Analysis query returned a malformed envelope"
        )
    # Data has already passed the operation projection.  Rebuild the envelope
    # instead of copying transport metadata, request echoes, page tokens, or
    # raw upstream exception text.
    status = value.get("status")
    if not isinstance(status, str) or status not in RESULT_STATUSES:
        raise ContractChangedError(
            "saved Analysis query returned an unknown result status"
        )
    error = value.get("error")
    if status in SUCCESS_STATUSES and error not in (None, {}):
        raise ContractChangedError(
            "saved Analysis query returned contradictory success and error fields"
        )
    ok = status in SUCCESS_STATUSES and error in (None, {})
    if "ok" in value and value.get("ok") is not ok:
        raise ContractChangedError(
            "saved Analysis query returned inconsistent success metadata"
        )
    result = {
        "schema_version": "gravity-insight.read.v1",
        "operation_id": (
            str(value["operation_id"])
            if isinstance(value.get("operation_id"), str)
            else None
        ),
        "ok": ok,
        "status": status,
        "data": value.get("data") if ok else None,
        "error": None,
    }
    if not ok:
        result["error"] = _safe_error(error if isinstance(error, Mapping) else {})
    return result


def _safe_error(value: Mapping[str, Any]) -> dict[str, Any]:
    category = str(value.get("category") or "upstream")
    if category not in {"caller", "upstream", "local"}:
        category = "upstream"
    code = str(value.get("code") or ErrorCode.UPSTREAM_UNAVAILABLE.value).upper()
    if code not in KNOWN_ERROR_CODES and code != "BATCH_RESULT_MISSING":
        code = ErrorCode.UPSTREAM_UNAVAILABLE.value
    return {
        "code": code,
        "category": category,
        "message": "Saved Analysis query failed.",
        "field": "result" if isinstance(value.get("field"), str) else None,
        "retryable": value.get("retryable") is True,
        "retry_after_ms": (
            value.get("retry_after_ms")
            if isinstance(value.get("retry_after_ms"), int)
            and not isinstance(value.get("retry_after_ms"), bool)
            and value["retry_after_ms"] >= 0
            else None
        ),
        "next_action": "Follow the governed error code and retry only after correcting its cause.",
    }


def safe_validation(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "status": value.get("status"),
        "live_metadata_dependencies": list(
            value.get("live_metadata_dependencies", [])
        ),
    }


def require_success(value: Any, operation_id: str, label: str) -> None:
    if not isinstance(value, Mapping):
        raise ContractChangedError(f"{label} returned a malformed envelope")
    status = str(value.get("status", "error"))
    success = status in SUCCESS_STATUSES and value.get("error") in (None, {})
    if "ok" in value and value.get("ok") is not success:
        raise ContractChangedError(f"{label} returned inconsistent success metadata")
    if success:
        return
    error = value.get("error")
    raw_code = error.get("code") if isinstance(error, Mapping) else None
    code = str(raw_code).upper() if raw_code is not None else ""
    if code not in KNOWN_ERROR_CODES:
        code = ErrorCode.UPSTREAM_UNAVAILABLE.value
    raise GravityInsightError(
        f"{label} could not be read safely",
        code=code,
        next_action=f"Follow the {operation_id} error guidance, then retry once.",
    )


def selected_workspace(value: Workspace | str | Any | None) -> Any:
    if isinstance(value, Workspace) or callable(getattr(value, "resolve_app", None)):
        return value
    return load_workspace(value)


def bounds(max_pages: Any, max_items: Any) -> tuple[int, int]:
    if (
        isinstance(max_pages, bool)
        or not isinstance(max_pages, int)
        or not 1 <= max_pages <= DEFAULT_MAX_PAGES
    ):
        raise InputValidationError(
            f"actual value: {actual_value(max_pages)}; " + (f"saved Analysis max_pages must be between 1 and {DEFAULT_MAX_PAGES}"),
            field="max_pages",
        )
    if (
        isinstance(max_items, bool)
        or not isinstance(max_items, int)
        or not 1 <= max_items <= DEFAULT_MAX_ITEMS
    ):
        raise InputValidationError(
            f"actual value: {actual_value(max_items)}; " + (f"saved Analysis max_items must be between 1 and {DEFAULT_MAX_ITEMS}"),
            field="max_items",
        )
    return max_pages, max_items


def workers(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_WORKERS:
        raise InputValidationError(
            f"actual value: {actual_value(value)}; " + (f"saved Analysis max_workers must be between 1 and {MAX_WORKERS}"),
            field="max_workers",
        )
    return value


def identifier(value: Any, field: str) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise InputValidationError(
            f"actual value: {actual_value(value)}; " + (f"{field} must be a string or integer"), field=field
        )
    selected = str(value).strip()
    if not selected or len(selected) > 256:
        raise InputValidationError(
            f"actual value: {actual_value(selected)}; " + (f"{field} must be a bounded identifier"), field=field
        )
    return selected


def text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise InputValidationError(f"actual value: {actual_value(value)}; " + (f"{field} must be a bounded string"), field=field)
    return value.strip()


def require_one_source(reference: Any, definition: Any) -> None:
    if (reference is None) == (definition is None):
        raise InputValidationError(
            "provide exactly one saved Analysis reference or definition",
            field="reference/definition", next_action="Supply exactly one of reference or definition.",
        )


__all__ = [
    "DEFAULT_MAX_ITEMS",
    "DEFAULT_MAX_PAGES",
    "DEFAULT_MAX_WORKERS",
    "SUBJECT_KINDS",
    "SUCCESS_STATUSES",
    "bounds",
    "catalog_rows",
    "decoded_config",
    "normalize_definition",
    "replay_capability",
    "require_one_source",
    "require_success",
    "safe_metadata",
    "safe_query_envelope",
    "safe_validation",
    "select_reference",
    "selected_workspace",
    "supported_subject",
    "validate_definition_shape",
    "workers",
]
