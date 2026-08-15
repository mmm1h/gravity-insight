"""Governed catalog, inspection, and replay for Analysis templates.

Template ``config`` is an opaque operation field.  This module opens only two
already-proven shapes: compact Analysis Spec v1 and Dashboard ``calculateBody``
artifacts.  The observed ``originParams`` representation is described through
a value-free quarantine report and is never translated by similarity.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .dashboard_artifact import validate_dashboard_window
from .domains import ANALYSIS_TEMPLATE_OPERATIONS
from .errors import (
    ContractChangedError,
    ErrorCategory,
    ErrorCode,
    GravityInsightError,
    InputValidationError,
    PaginationError,
    exit_code_for_category,
    exit_code_for_error,
)
from .runtime import call_read
from .saved_analysis_result import execute_compiled, saved_result_item_count
from .saved_analysis_support import (
    DEFAULT_MAX_ITEMS,
    DEFAULT_MAX_PAGES,
    DEFAULT_MAX_WORKERS,
    bounds,
    require_success,
    safe_query_envelope,
    selected_workspace,
    workers,
)
from .workspace_app import resolve_workspace_app
from .template_artifact import CompiledTemplate, compile_template_artifact


CATALOG_SCHEMA_VERSION = "gravity-insight.analysis-template-catalog.v1"
PREVIEW_SCHEMA_VERSION = "gravity-insight.analysis-template-preview.v1"
REPLAY_SCHEMA_VERSION = "gravity-insight.analysis-template-replay.v1"

TEMPLATE_OPERATIONS = {
    scope: ANALYSIS_TEMPLATE_OPERATIONS[scope]
    for scope in ("own", "share", "internal")
}
_TEMPLATE_FIELDS = frozenset(
    {
        "cid", "config", "create_time", "id", "internal", "modify_time",
        "name", "review", "share_status", "source", "sub_type",
        "subject_ids", "subject_names", "template_type",
    }
)


def list_analysis_templates(
    client: Any,
    *,
    scope: str | None = None,
    max_pages: int = DEFAULT_MAX_PAGES,
    max_items: int = DEFAULT_MAX_ITEMS,
    max_workers: int = DEFAULT_MAX_WORKERS,
) -> dict[str, Any]:
    """List safe identities from one or all template catalogs."""

    pages, items = bounds(max_pages, max_items)
    page_workers = workers(max_workers)
    scopes = (_scope(scope),) if scope is not None else tuple(TEMPLATE_OPERATIONS)
    components: list[dict[str, Any]] = []
    failure_exit_codes: list[int] = []
    rows: list[dict[str, Any]] = []
    remaining = items
    for selected_scope in scopes:
        operation_id = TEMPLATE_OPERATIONS[selected_scope]
        try:
            envelope = _read_catalog(
                client, selected_scope, max_pages=pages,
                max_items=max(1, remaining), max_workers=page_workers,
            )
            component = _catalog_component(envelope, operation_id, selected_scope)
            if component["ok"]:
                selected_rows = _catalog_rows(envelope, selected_scope)
                if len(selected_rows) > remaining:
                    raise PaginationError("Analysis template catalog exceeded max_items")
                rows.extend(selected_rows)
                remaining -= len(selected_rows)
            components.append(component)
        except GravityInsightError as exc:
            components.append(_component_error(selected_scope, operation_id, exc))
            failure_exit_codes.append(exit_code_for_error(exc))
    successes = sum(item["ok"] is True for item in components)
    failures = len(components) - successes
    status = (
        "partial" if failures and successes else
        "error" if failures else
        "success" if rows else "empty"
    )
    return {
        "schema_version": CATALOG_SCHEMA_VERSION,
        "ok": failures == 0,
        "status": status,
        "exit_code": max(failure_exit_codes, default=0),
        "network_called": True,
        "query_executed": False,
        "count": len(rows),
        "items": rows,
        "components": components,
        "next_action": (
            "Select one template by scope and exact id or name, then prepare or run it."
            if rows else
            "No readable templates are available in the selected catalog scope."
        ),
    }


def prepare_analysis_template(
    client: Any,
    *,
    scope: str,
    reference: str | int | Mapping[str, Any],
    app: str | int | None,
    start: str,
    end: str,
    workspace: Any | None = None,
    max_pages: int = DEFAULT_MAX_PAGES,
    max_items: int = DEFAULT_MAX_ITEMS,
    max_workers: int = DEFAULT_MAX_WORKERS,
) -> dict[str, Any]:
    """Resolve and strictly inspect one template without running its query."""

    validate_dashboard_window(start, end)
    selected_workspace_value = selected_workspace(workspace)
    app_id = str(resolve_workspace_app(selected_workspace_value, app))
    item = _resolve_template(
        client, scope, reference,
        max_pages=max_pages, max_items=max_items, max_workers=max_workers,
    )
    report = compile_template_artifact(
        client, item, app_id=app_id, workspace=selected_workspace_value,
        start=start, end=end,
    )
    return _preview_envelope(item, scope, app_id, start, end, report)


def run_analysis_template(
    client: Any,
    *,
    scope: str,
    reference: str | int | Mapping[str, Any],
    app: str | int | None,
    start: str,
    end: str,
    workspace: Any | None = None,
    max_pages: int = DEFAULT_MAX_PAGES,
    max_items: int = DEFAULT_MAX_ITEMS,
    max_workers: int = DEFAULT_MAX_WORKERS,
) -> dict[str, Any]:
    """Resolve and execute one template only after complete strict compilation."""

    validate_dashboard_window(start, end)
    pages, items = bounds(max_pages, max_items)
    selected_workspace_value = selected_workspace(workspace)
    app_id = str(resolve_workspace_app(selected_workspace_value, app))
    item = _resolve_template(
        client, scope, reference,
        max_pages=pages, max_items=items, max_workers=max_workers,
    )
    report = compile_template_artifact(
        client, item, app_id=app_id, workspace=selected_workspace_value,
        start=start, end=end,
    )
    compiled = report.get("compiled")
    if not isinstance(compiled, CompiledTemplate):
        preview = _preview_envelope(item, scope, app_id, start, end, report)
        return {
            **preview,
            "schema_version": REPLAY_SCHEMA_VERSION,
            "ok": False,
            # exit-code-guard: allow - capability_gap is a caller selection result without ErrorDetail.
            "exit_code": 2,
            "next_action": (
                "Do not execute this template until every quarantine item has a "
                "proven Analysis contract mapping."
            ),
        }
    query = execute_compiled(client, compiled)
    if saved_result_item_count(compiled.operation_id, query) > items:
        raise PaginationError("Analysis template result exceeded max_items")
    status = str(query["status"])
    ok = query["ok"] is True
    return {
        "schema_version": REPLAY_SCHEMA_VERSION,
        "ok": ok,
        "status": status,
        "exit_code": 0 if ok else _result_exit_code(query),
        "network_called": True,
        "definition_network_called": True,
        "query_executed": True,
        "template": _safe_metadata(item, scope, app_id, replay_supported=True),
        "artifact_mode": compiled.mode,
        "kind": compiled.kind,
        "operation_id": compiled.operation_id,
        "date_range": _date_range(start, end),
        "date_override_applied": compiled.date_override_applied,
        "limitations": list(compiled.limitations),
        "quarantine": [],
        "result": safe_query_envelope(query),
        "next_action": (
            "Consume the governed Analysis result."
            if ok else "Follow result.error and do not consume a failed replay."
        ),
    }


def _resolve_template(
    client: Any,
    scope: str,
    reference: str | int | Mapping[str, Any],
    *,
    max_pages: int,
    max_items: int,
    max_workers: int,
) -> dict[str, Any]:
    selected_scope = _scope(scope)
    pages, items = bounds(max_pages, max_items)
    envelope = _read_catalog(
        client, selected_scope, max_pages=pages, max_items=items,
        max_workers=workers(max_workers),
    )
    catalog_rows = _catalog_rows(envelope, selected_scope)
    mode, selected = _reference(reference)
    matches = [
        row for row in catalog_rows
        if (mode == "id" and row["id"] == selected)
        or (mode == "name" and row["name"] == selected)
        or (mode == "auto" and selected in {row["id"], row["name"]})
    ]
    if not matches:
        raise InputValidationError(
            "Analysis template reference was not found in the selected scope",
            field="reference",
        )
    if len(matches) != 1:
        raise InputValidationError(
            "Analysis template reference is ambiguous; use an explicit id",
            field="reference",
        )
    raw_rows = _raw_rows(envelope)
    selected_id = matches[0]["id"]
    raw_matches = [row for row in raw_rows if _identifier(row.get("id"), "id") == selected_id]
    if len(raw_matches) != 1:
        raise ContractChangedError("Analysis template identity changed during resolution")
    return dict(raw_matches[0])


def _preview_envelope(
    item: Mapping[str, Any], scope: str, app_id: str, start: str, end: str,
    report: Mapping[str, Any],
) -> dict[str, Any]:
    supported = isinstance(report.get("compiled"), CompiledTemplate)
    return {
        "schema_version": PREVIEW_SCHEMA_VERSION,
        "ok": True,
        "status": "compiled" if supported else "capability_gap",
        "exit_code": 0,
        "network_called": True,
        "definition_network_called": True,
        "query_executed": False,
        "template": _safe_metadata(item, scope, app_id, replay_supported=supported),
        "artifact_mode": report.get("artifact_mode"),
        "kind": report.get("kind"),
        "operation_id": report.get("operation_id"),
        "date_range": _date_range(start, end),
        "date_override_applied": report.get("date_override_applied", False),
        "limitations": list(report.get("limitations", [])),
        "validation": (
            {"status": report.get("validation_status"), "live_metadata_dependencies": []}
            if supported else None
        ),
        "quarantine": list(report.get("quarantine", [])),
        "next_action": (
            "Run this template through the governed replay entrypoint."
            if supported else
            "Keep the template non-executable until every quarantine reason is proven."
        ),
    }


def _catalog_component(value: Any, operation_id: str, scope: str) -> dict[str, Any]:
    require_success(value, operation_id, "Analysis template catalog")
    count = len(_raw_rows(value))
    return {
        "scope": scope, "operation_id": operation_id, "ok": True,
        "status": "success" if count else "empty", "count": count, "error": None,
    }


def _read_catalog(
    client: Any, scope: str, *, max_pages: int, max_items: int, max_workers: int
) -> Mapping[str, Any]:
    operation_id = TEMPLATE_OPERATIONS[scope]
    envelope = call_read(
        client, operation_id, {"page": 1, "page_size": 1}, read_all=True,
        max_pages=max_pages, max_items=max_items, max_workers=max_workers,
    )
    require_success(envelope, operation_id, "Analysis template catalog")
    _raw_rows(envelope)
    return envelope


def _catalog_rows(value: Mapping[str, Any], scope: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in _raw_rows(value):
        unknown = set(raw) - _TEMPLATE_FIELDS
        if unknown:
            raise ContractChangedError("Analysis template catalog contains unregistered fields")
        item_id = _identifier(raw.get("id"), "id")
        if item_id in seen:
            raise ContractChangedError("Analysis template catalog contains duplicate ids")
        seen.add(item_id)
        result.append(_safe_metadata(raw, scope, None, replay_supported=None))
    return result


def _raw_rows(value: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    data = value.get("data")
    rows = data.get("list") if isinstance(data, Mapping) else None
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        raise ContractChangedError("Analysis template catalog changed shape")
    if any(not isinstance(item, Mapping) for item in rows):
        raise ContractChangedError("Analysis template catalog contains malformed items")
    if value.get("truncated") is True or value.get("next_page_input") not in (None, {}):
        raise PaginationError("Analysis template catalog exceeded its discovery bound")
    return list(rows)


def _safe_metadata(
    item: Mapping[str, Any], scope: str, app_id: str | None,
    *, replay_supported: bool | None,
) -> dict[str, Any]:
    result = {
        "scope": _scope(scope),
        "id": _identifier(item.get("id"), "id"),
        "name": _text(item.get("name"), "name"),
        "template_type": _optional_text(item.get("template_type")),
        "sub_type": _optional_text(item.get("sub_type")),
        "modify_time": _optional_text(item.get("modify_time")),
        "replay_supported": replay_supported,
    }
    if app_id is not None:
        result["app_id"] = app_id
    return result


def _component_error(scope: str, operation_id: str, exc: Exception) -> dict[str, Any]:
    code = getattr(exc, "code", ErrorCode.UPSTREAM_UNAVAILABLE)
    code_value = code.value if isinstance(code, ErrorCode) else str(code)
    rendered = {
        ErrorCode.PERMISSION_UNAVAILABLE.value: "permission_unavailable",
        ErrorCode.CONTRACT_CHANGED.value: "contract_changed",
    }.get(code_value, "error")
    return {
        "scope": scope, "operation_id": operation_id, "ok": False,
        "status": rendered, "count": 0,
        "error": {"code": code_value,
                  "message": "Analysis template catalog source was unavailable."},
    }


def _scope(value: Any) -> str:
    selected = str(value or "").strip().casefold()
    if selected not in TEMPLATE_OPERATIONS:
        raise InputValidationError("template scope must be own, share, or internal", field="scope")
    return selected


def _reference(value: Any) -> tuple[str, str]:
    if isinstance(value, Mapping):
        if set(value) not in ({"id"}, {"name"}):
            raise InputValidationError("template reference must contain exactly id or name", field="reference")
        mode = next(iter(value))
        selected = value[mode]
        if mode == "id":
            return mode, _reference_id(selected, f"reference.{mode}")
        return mode, _reference_text(selected, f"reference.{mode}")
    if isinstance(value, int) and not isinstance(value, bool):
        return "id", _reference_id(value, "reference")
    return "auto", _reference_text(value, "reference")


def _reference_id(value: Any, field: str) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise InputValidationError("template reference id is invalid", field=field)
    selected = str(value).strip()
    if not selected or len(selected) > 256:
        raise InputValidationError("template reference id is invalid", field=field)
    return selected


def _reference_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise InputValidationError("template reference name is invalid", field=field)
    return value.strip()


def _identifier(value: Any, field: str) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ContractChangedError(f"Analysis template {field} is invalid")
    selected = str(value).strip()
    if not selected or len(selected) > 256:
        raise ContractChangedError(f"Analysis template {field} is invalid")
    return selected


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise ContractChangedError(f"Analysis template {field} is invalid")
    return value.strip()


def _optional_text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() and len(value) <= 256 else None


def _date_range(start: str, end: str) -> dict[str, Any]:
    return {"start": start.strip(), "end": end.strip(), "inclusive": True}


def _result_exit_code(value: Mapping[str, Any]) -> int:
    error = value.get("error")
    category = error.get("category") if isinstance(error, Mapping) else None
    return exit_code_for_category(str(category), default=ErrorCategory.UPSTREAM)


__all__ = [
    "CATALOG_SCHEMA_VERSION", "PREVIEW_SCHEMA_VERSION", "REPLAY_SCHEMA_VERSION",
    "TEMPLATE_OPERATIONS", "list_analysis_templates",
    "prepare_analysis_template", "run_analysis_template",
]
