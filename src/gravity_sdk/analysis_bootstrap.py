"""Guided cold start from an explicit App and event to a reviewed Plan."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .actionable_error_values import actual_value
from .analysis_spec import compile_query_spec
from .domains import DOMAIN_OPERATIONS
from .errors import (
    AuthenticationError,
    CredentialError,
    GravityInsightError,
    InputValidationError,
    UpstreamError,
)
from .find_metadata import search_metadata
from .metadata_catalog_snapshot import create_metadata_snapshot
from .metadata_onboarding import sync_app
from .metadata_status import metadata_status
from .metadata_sync import default_catalog_path
from .result_audit import (
    bind_error_receipts,
    error_receipt_references,
    result_receipt_references,
)


SCHEMA_VERSION = "gravity.analysis-bootstrap.v1"
_APP_PAGE_SIZE = 6_000
_MAX_PAGES = 1
_METRIC = {"field": "PresetAllCount", "aggregation": "PresetAllCount"}


def bootstrap_event_analysis(
    sdk: Any,
    *,
    app: Any,
    start: Any,
    end: Any,
    target: Any,
    database: str | Path | None = None,
    max_pages: int = _MAX_PAGES,
    concurrency: int = 8,
) -> dict[str, Any]:
    """Verify one App, synchronize its catalog, and return a pinned Plan."""

    selected_app, selected_target, selected_database = _bootstrap_inputs(
        app, target, database
    )
    _require_bootstrap_page_cap(max_pages)
    _validate_window(sdk.workspace, selected_app, selected_target, start, end)
    app_result, before, sync_result, after = _prepare_catalog(
        sdk,
        selected_app,
        selected_database,
        max_pages=max_pages,
        concurrency=concurrency,
    )
    try:
        event, snapshot, plan, validation = _ready_plan(
            sdk,
            selected_app,
            selected_target,
            start,
            end,
            selected_database,
        )
    except GravityInsightError as exc:
        bind_error_receipts(exc, _bootstrap_receipts(app_result, sync_result))
        raise
    return _bootstrap_result(
        selected_app, event, start, end, before, after, sync_result,
        snapshot, plan, validation, app_result,
    )


def _bootstrap_inputs(
    app: Any, target: Any, database: str | Path | None
) -> tuple[str, str, Path]:
    app_action = (
        "Run `gravity run app.list --input "
        "'{\"page\":1,\"page_size\":6000}' --fields id,name`, choose one App, "
        "then retry bootstrap with --app <id>."
    )
    selected_app = _required_text(
        app,
        field="app",
        allowed="a positive App id selected by the caller",
        next_action=app_action,
    )
    if not selected_app.isdecimal() or int(selected_app) <= 0:
        raise _input_error(
            f"bootstrap App actual value: {actual_value(app)}; allowed value: a positive App id",
            "app",
            app_action,
        )
    selected_target = _required_text(
        target,
        field="target",
        allowed="one exact physical event name",
        next_action=(
            f"Run `gravity metadata events \"\" --app-id {selected_app}` and retry "
            "with one exact physical event name."
        ),
    )
    selected_database = (
        Path(database) if database is not None else default_catalog_path()
    ).expanduser().resolve()
    return selected_app, selected_target, selected_database


def _prepare_catalog(
    sdk: Any,
    app_id: str,
    database: Path,
    *,
    max_pages: int,
    concurrency: int,
) -> tuple[Mapping[str, Any], Mapping[str, Any], Mapping[str, Any] | None, Mapping[str, Any]]:
    app_result: Mapping[str, Any] = {}
    sync_result: Mapping[str, Any] | None = None
    try:
        app_result = sdk.insight.read(
            DOMAIN_OPERATIONS["apps.list"][0],
            {"page": 1, "page_size": _APP_PAGE_SIZE},
        )
        _require_readable_app(app_result, app_id)
        before = metadata_status(database=database, app_id=app_id)
        if before.get("status") != "ready":
            sync_result = sync_app(
                sdk.insight,
                app_id,
                database=database,
                max_pages=max_pages,
                concurrency=concurrency,
            )
            _require_complete_sync(sync_result, app_id, max_pages)
    except CredentialError as exc:
        rewritten = _credential_error(exc)
        bind_error_receipts(
            rewritten,
            [
                *error_receipt_references(exc),
                *_bootstrap_receipts(app_result, sync_result),
            ],
        )
        raise rewritten from exc
    except GravityInsightError as exc:
        bind_error_receipts(exc, _bootstrap_receipts(app_result, sync_result))
        raise
    after = metadata_status(database=database, app_id=app_id)
    if after.get("status") != "ready":
        raise _input_error(
            "bootstrap metadata status actual value: "
            f"{actual_value(after.get('status'))}; allowed value: \"ready\"",
            "metadata.status",
            _bootstrap_action(app_id),
        )
    return app_result, before, sync_result, after


def _require_bootstrap_page_cap(value: Any) -> None:
    if value != _MAX_PAGES or isinstance(value, bool):
        raise _input_error(
            f"bootstrap max_pages actual value: {actual_value(value)}; allowed value: 1",
            "max_pages",
            "Replace --max-pages with 1 so the complete journey remains within seven HTTP requests.",
        )


def _validate_window(
    workspace: Any, app_id: str, target: str, start: Any, end: Any
) -> None:
    spec = {
        "start": start,
        "end": end,
        "steps": [{"event": target, "metric": dict(_METRIC)}],
    }
    try:
        compile_query_spec("event", spec, workspace=workspace, app=app_id)
    except InputValidationError as exc:
        if exc.field != "start/end":
            raise
        raise _input_error(
            "bootstrap date range actual value: "
            f"{actual_value({'start': start, 'end': end})}; allowed value: two "
            "ordered ISO dates spanning no more than 90 days",
            "start/end",
            "Replace --start and --end with that date range, then retry bootstrap.",
        ) from exc


def _ready_plan(
    sdk: Any,
    app_id: str,
    target: str,
    start: Any,
    end: Any,
    database: Path,
) -> tuple[str, Mapping[str, str], Mapping[str, Any], Mapping[str, Any]]:
    event = _exact_event(database, app_id, target)
    spec = {
        "start": start,
        "end": end,
        "time_grain": "day",
        "steps": [{"event": event, "metric": dict(_METRIC)}],
    }
    snapshot = create_metadata_snapshot(app_id, database=database)
    plan = _plan(app_id, spec, snapshot)
    validation = sdk.execute_plan(
        plan, workspace=sdk.workspace, metadata_database=database, dry_run=True
    )
    return event, snapshot, plan, validation


def _bootstrap_result(
    app_id: str,
    event: str,
    start: Any,
    end: Any,
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    sync_result: Mapping[str, Any] | None,
    snapshot: Mapping[str, str],
    plan: Mapping[str, Any],
    validation: Mapping[str, Any],
    app_result: Mapping[str, Any],
) -> dict[str, Any]:
    references = [
        *result_receipt_references(app_result),
        *result_receipt_references(sync_result or {}),
    ]
    observed = len({item["receipt_id"] for item in references}) if references else 0
    return {
        "schema_version": SCHEMA_VERSION,
        "ok": True,
        "status": "plan_ready",
        "network_called": observed > 0,
        "app_id": app_id,
        "target": {"kind": "physical_event", "name": event},
        "date_range": {"start": start, "end": end, "inclusive": True},
        "metadata": {
            "status_before": before.get("status"),
            "status_after": after.get("status"),
            "sync_performed": sync_result is not None,
            "snapshot": snapshot,
        },
        "request_budget": {
            "top_level_calls_completed": 1,
            "top_level_calls_remaining": 1,
            "http_requests_observed": observed,
            "http_request_limit_for_complete_journey": 7,
            "analysis_requests_remaining": 1,
        },
        "plan_validation": {
            "schema_version": validation.get("schema_version"),
            "ok": validation.get("ok"),
            "status": validation.get("status"),
            "dry_run": validation.get("dry_run"),
        },
        "plan": plan,
        "next": {
            "argv": ["gravity", "plan", "run", "--input", "<plan.json>"],
            "action": "Review plan, persist exactly plan, then run it once.",
        },
    }


def _require_readable_app(result: Mapping[str, Any], app_id: str) -> None:
    status = result.get("status")
    if status not in {"success", "empty"} or result.get("ok") is False:
        raise UpstreamError(
            f"App discovery observed status {actual_value(status)} at app.list; allowed status: success or empty",
            field="app.list.status",
            next_action=(
                "Retry `gravity run app.list --input "
                "'{\"page\":1,\"page_size\":6000}' --fields id,name` once; "
                "stop if the same status repeats."
            ),
        )
    rows = _rows(result)
    if not rows:
        raise _input_error(
            f"readable App count actual value: {actual_value(0)}; allowed value: at least one App",
            "app.list.data.list",
            "Ask the Gravity workspace owner for App read access, then retry the same bootstrap command.",
        )
    ids = {
        str(item.get("id", item.get("app_id"))).strip()
        for item in rows
        if item.get("id", item.get("app_id")) is not None
    }
    if app_id not in ids:
        raise _input_error(
            f"bootstrap App actual value: {actual_value(app_id)}; allowed values from app.list: {actual_value(sorted(ids))}",
            "app",
            "Run `gravity run app.list --input '{\"page\":1,\"page_size\":6000}' --fields id,name`, choose one listed App, then retry bootstrap.",
        )


def _require_complete_sync(
    result: Mapping[str, Any], app_id: str, max_pages: int
) -> None:
    if result.get("ok") is True and result.get("status") == "success":
        return
    failures = result.get("failures")
    observed = [
        {
            "operation_id": item.get("operation_id"),
            "status": item.get("status"),
            "code": item.get("code"),
        }
        for item in failures
        if isinstance(item, Mapping)
    ] if isinstance(failures, Sequence) and not isinstance(failures, (str, bytes)) else []
    caller_failure = any(
        isinstance(item, Mapping) and item.get("category") == "caller"
        for item in (failures or ())
    )
    page_bound = any(item.get("code") == "PAGE_BOUND_REACHED" for item in observed)
    next_action = (
        "Run `gravity metadata sync --app-id "
        f"{app_id} --max-pages 2`, review its larger explicit budget, then retry "
        "bootstrap; bootstrap will not expand its own seven-request bound."
        if page_bound
        else (
            "Inspect failures and retry `gravity metadata sync --app-id "
            f"{app_id} --max-pages {max_pages}` only when retryable; do not expand "
            "the cold-start HTTP budget automatically."
        )
    )
    if caller_failure:
        raise _input_error(
            "metadata sync actual value: "
            f"{actual_value(observed or result.get('status'))}; allowed value: "
            "four complete metadata operation snapshots",
            "metadata.sync.failures",
            next_action,
        )
    raise UpstreamError(
        "metadata sync actual value: "
        f"{actual_value(observed or result.get('status'))}; allowed value: "
        "four complete metadata operation snapshots",
        field="metadata.sync.failures",
        next_action=next_action,
    )


def _exact_event(database: Path, app_id: str, target: str) -> str:
    result = search_metadata(
        target,
        database=database,
        app_id=app_id,
        kind="event",
        limit=None,
    )
    candidates = sorted(
        {
            str(item["name"])
            for item in result.get("results", ())
            if isinstance(item, Mapping) and item.get("name") == target
        }
    )
    if len(candidates) != 1:
        raise _input_error(
            f"bootstrap target actual value: {actual_value(target)}; allowed value: one exact physical event name; exact match count: {actual_value(len(candidates))}",
            "target",
            f"Run `gravity metadata events {actual_value(target)} --app-id {app_id}` and retry with one result's exact name.",
        )
    return candidates[0]


def _rows(result: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    data = result.get("data")
    values = data.get("list", ()) if isinstance(data, Mapping) else ()
    return [item for item in values if isinstance(item, Mapping)]


def _bootstrap_receipts(
    app_result: Mapping[str, Any], sync_result: Mapping[str, Any] | None
) -> list[dict[str, str]]:
    return [
        *result_receipt_references(app_result),
        *result_receipt_references(sync_result or {}),
    ]


def _plan(
    app_id: str, spec: Mapping[str, Any], snapshot: Mapping[str, str]
) -> dict[str, Any]:
    return {
        "schema_version": "gravity.plan.v1",
        "budget": {"max_workers": 1, "max_total_items": 200},
        "nodes": [
            {
                "id": "first_event_analysis",
                "kind": "composite",
                "request": {
                    "name": "analysis_query",
                    "kind": "event",
                    "app": app_id,
                    "spec": dict(spec),
                    "metadata_snapshot": dict(snapshot),
                },
                "limits": {"max_pages": 1, "max_items": 200},
            }
        ],
    }


def _required_text(
    value: Any, *, field: str, allowed: str, next_action: str
) -> str:
    if not isinstance(value, (str, int)) or isinstance(value, bool) or not str(value).strip():
        raise _input_error(
            f"bootstrap {field} actual value: {actual_value(value)}; allowed value: {allowed}",
            field,
            next_action,
        )
    return str(value).strip()


def _credential_error(error: CredentialError) -> CredentialError:
    selected = AuthenticationError if isinstance(error, AuthenticationError) else CredentialError
    return selected(
        f"bootstrap credentials observed value: {actual_value(error.code.value)}; allowed value: a valid username/password or unexpired session",
        field="credentials",
        next_action="Run `gravity insight auth refresh`, correct the configured credentials if rejected, then retry bootstrap once.",
    )


def _bootstrap_action(app_id: str) -> str:
    return (
        "Retry `gravity analysis bootstrap --app "
        f"{app_id} --start <date> --end <date> --target <physical-event>` "
        "after the reported metadata action succeeds."
    )


def _input_error(
    message: str, field: str, next_action: str
) -> InputValidationError:
    return InputValidationError(message, field=field, next_action=next_action)


__all__ = ["SCHEMA_VERSION", "bootstrap_event_analysis"]
