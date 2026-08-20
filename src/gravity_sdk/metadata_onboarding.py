"""Bounded single-App metadata refresh and offline catalog status."""

from __future__ import annotations

import shutil
import sqlite3
from collections.abc import Mapping, Sequence
from contextlib import closing
from pathlib import Path
from typing import Any

from .actionable_error_values import actual_value
from .domains import ANALYSIS_METADATA_OPERATIONS, ANALYSIS_PAGINATED_OPERATIONS
from .errors import ErrorCategory, InputValidationError, exit_code_for_category
from .find_metadata import _validate_schema
from .metadata_sync import (
    DEFAULT_CONCURRENCY,
    MAX_CONCURRENCY,
    SCHEMA_VERSION as SYNC_SCHEMA_VERSION,
    _create_schema,
    _failure,
    _json,
    _metadata_inputs,
    _rows,
    _temporary_database,
    _utc_now,
    _write_failure,
    _write_rows,
    default_catalog_path,
)
from .result_audit import aggregate_result_audit, result_receipt_references
from .result_source import LOCAL_CATALOG, result_source
from .runtime import call_batch
from .runtime_scope import public_scoped_path


DEFAULT_MAX_PAGES = 2
MAX_APP_SYNC_PAGES = 8
PAGE_SIZE = 2_000
_PAGINATED = frozenset(ANALYSIS_PAGINATED_OPERATIONS) & frozenset(
    ANALYSIS_METADATA_OPERATIONS
)


def app_sync_request_budget(app_id: Any, *, max_pages: Any = DEFAULT_MAX_PAGES) -> dict[str, Any]:
    """Return the zero-network, machine-readable single-App request bound."""

    selected_app = _app_id(app_id)
    pages = _max_pages(max_pages)
    paginated_count = len(_PAGINATED)
    non_paginated_count = len(ANALYSIS_METADATA_OPERATIONS) - paginated_count
    return {
        "schema_version": "gravity.metadata-sync-bound.v1",
        "bound_kind": "single_app_fixed_analysis_objects_page_cap",
        "scope": "single_app",
        "app_id": selected_app,
        "app_count": 1,
        "operations": list(ANALYSIS_METADATA_OPERATIONS),
        "operation_count": len(ANALYSIS_METADATA_OPERATIONS),
        "paginated_operation_count": paginated_count,
        "non_paginated_operation_count": non_paginated_count,
        "max_pages_per_paginated_operation": pages,
        "logical_request_upper_bound": paginated_count * pages + non_paginated_count,
        "unit": "authorized_operation_page_request",
        "transport_retries_included": False,
        "transport_retry_note": (
            "HTTP retries and one authentication refresh follow the caller's client "
            "runtime policy and are reported from receipts after execution."
        ),
    }


def estimate_app_sync(
    app_id: Any,
    *,
    database: str | Path | None = None,
    max_pages: Any = DEFAULT_MAX_PAGES,
) -> dict[str, Any]:
    """Return the complete zero-network pre-execution sync estimate."""

    budget = app_sync_request_budget(app_id, max_pages=max_pages)
    return {
        "schema_version": SYNC_SCHEMA_VERSION,
        "result_source": result_source(LOCAL_CATALOG),
        "ok": True,
        "status": "estimate",
        "scope": "single_app",
        "database": public_scoped_path(
            _destination(database), explicit=database is not None
        ),
        "app_id": budget["app_id"],
        "dry_run": True,
        "network_called": False,
        "request_budget": budget,
        "next_action": (
            "Run the same bounded sync without --dry-run, then inspect "
            "operation_rows and operation_pages."
        ),
        "exit_code": 0,
    }


def sync_app(
    client: Any,
    app_id: Any,
    *,
    database: str | Path | None = None,
    max_pages: Any = DEFAULT_MAX_PAGES,
    concurrency: Any = DEFAULT_CONCURRENCY,
) -> dict[str, Any]:
    """Refresh four Analysis metadata object kinds for exactly one App."""

    budget = app_sync_request_budget(app_id, max_pages=max_pages)
    selected_app = str(budget["app_id"])
    workers = _concurrency(concurrency)
    destination = _destination(database)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = _temporary_database(destination)
    synced_at = _utc_now()
    page_results: list[Mapping[str, Any]] = []
    try:
        states, failures, logical_requests, page_results = _replace_app_catalog(
            client,
            selected_app,
            destination=destination,
            temporary=temporary,
            synced_at=synced_at,
            max_pages=int(budget["max_pages_per_paginated_operation"]),
            concurrency=workers,
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary.replace(destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise

    result = _sync_result(
        destination=destination,
        app_id=selected_app,
        synced_at=synced_at,
        budget=budget,
        states=states,
        failures=failures,
        logical_requests=logical_requests,
        page_results=page_results,
    )
    if database is None:
        result["database"] = public_scoped_path(destination, explicit=False)
    return result


def _replace_app_catalog(
    client: Any, app_id: str, *, destination: Path, temporary: Path,
    synced_at: str, max_pages: int, concurrency: int,
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]], int, list[Mapping[str, Any]]]:
    catalog_exists = destination.exists()
    if catalog_exists:
        _require_compatible_catalog(destination)
        shutil.copy2(destination, temporary)
    with closing(sqlite3.connect(temporary)) as connection:
        if not catalog_exists:
            _create_schema(connection)
        connection.execute("PRAGMA foreign_keys = ON")
        payload = _preserved_app_payload(connection, app_id)
        _remove_app(connection, app_id)
        connection.execute(
            "INSERT INTO apps(app_id, payload_json, synced_at) VALUES (?, ?, ?)",
            (app_id, payload, synced_at),
        )
        states, failures, logical_requests, page_results = _read_bounded_pages(
            client, app_id, max_pages=max_pages, concurrency=concurrency,
        )
        for operation_id, state in states.items():
            _write_rows(connection, app_id, operation_id, state["rows"], synced_at)
        for failure in failures:
            _write_failure(connection, failure, synced_at)
        _refresh_catalog_summary(connection, synced_at)
        connection.commit()
    return states, failures, logical_requests, page_results


def _preserved_app_payload(connection: sqlite3.Connection, app_id: str) -> str:
    existing = connection.execute(
        "SELECT payload_json FROM apps WHERE app_id = ?", (app_id,)
    ).fetchone()
    return str(existing[0]) if existing is not None else _json({"id": app_id})


def _sync_result(
    *, destination: Path, app_id: str, synced_at: str,
    budget: Mapping[str, Any], states: Mapping[str, Mapping[str, Any]],
    failures: Sequence[Mapping[str, Any]], logical_requests: int,
    page_results: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    operation_rows = {operation_id: len(state["rows"]) for operation_id, state in states.items()}
    observed_receipts = _receipt_count(page_results)
    result: dict[str, Any] = {
        "schema_version": SYNC_SCHEMA_VERSION,
        "result_source": result_source(LOCAL_CATALOG),
        "ok": not failures,
        "status": "partial" if failures else "success",
        "scope": "single_app",
        "database": str(destination),
        "synced_at": synced_at,
        "app_id": app_id,
        "app_count": 1,
        "catalog_app_count": _catalog_app_count(destination),
        "operation_count": len(ANALYSIS_METADATA_OPERATIONS),
        "rows_written": sum(operation_rows.values()),
        "operation_rows": operation_rows,
        "operation_pages": {
            operation_id: {
                "pages_fetched": state["pages_fetched"],
                "complete": not state["truncated"] and state["failure"] is None,
                "truncated": state["truncated"],
                "next_page": state["next_page"] if state["truncated"] else None,
            }
            for operation_id, state in states.items()
        },
        "request_budget": budget,
        "logical_requests_made": logical_requests,
        "http_requests_observed": observed_receipts,
        "http_receipts_available": observed_receipts is not None,
        "retry_count_observed": (
            max(0, observed_receipts - logical_requests)
            if observed_receipts is not None
            else None
        ),
        "failure_count": len(failures),
        "failures": failures,
        "failures_truncated": False,
        "exit_code": _failure_exit_code(failures),
    }
    return aggregate_result_audit(result, page_results)


def app_sync_pages(value: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"max pages must be an integer between 1 and {MAX_APP_SYNC_PAGES}") from exc
    if not 1 <= parsed <= MAX_APP_SYNC_PAGES:
        raise ValueError(f"max pages must be an integer between 1 and {MAX_APP_SYNC_PAGES}")
    return parsed


def _read_bounded_pages(
    client: Any, app_id: str, *, max_pages: int, concurrency: int
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]], int, list[Mapping[str, Any]]]:
    states = {
        operation_id: {
            "rows": [], "pages_fetched": 0, "next_page": 1,
            "done": False, "truncated": False, "failure": None,
        }
        for operation_id in ANALYSIS_METADATA_OPERATIONS
    }
    failures: list[dict[str, Any]] = []
    logical_requests = 0
    page_results: list[Mapping[str, Any]] = []
    while pending := [item for item in states.items() if not item[1]["done"]]:
        requests = _page_requests(pending, app_id)
        results = call_batch(
            client,
            requests,
            concurrency=min(concurrency, len(requests)),
        )
        normalized = [item if isinstance(item, Mapping) else {} for item in results]
        logical_requests += len(requests)
        page_results.extend(normalized)
        for index, (operation_id, state) in enumerate(pending):
            result = normalized[index] if index < len(normalized) else None
            failure = _apply_page_result(
                state, result, app_id=app_id, operation_id=operation_id,
                max_pages=max_pages,
            )
            if failure:
                failures.append(failure)
    return states, failures, logical_requests, page_results


def _page_requests(
    pending: Sequence[tuple[str, dict[str, Any]]], app_id: str
) -> list[dict[str, Any]]:
    requests = []
    for operation_id, state in pending:
        inputs = _metadata_inputs(operation_id, app_id)
        if operation_id in _PAGINATED:
            inputs.update(page=state["next_page"], page_size=PAGE_SIZE)
        requests.append({
            "operation_id": operation_id, "request_id": operation_id,
            "inputs": inputs, "read_all": False,
        })
    return requests


def _apply_page_result(
    state: dict[str, Any], result: Mapping[str, Any] | None, *,
    app_id: str, operation_id: str, max_pages: int,
) -> dict[str, Any] | None:
    failure = _failure(app_id, operation_id, result)
    if failure is not None:
        failure = _actionable_failure(failure, app_id, max_pages)
        state.update(done=True, failure=failure)
        return failure
    assert result is not None
    envelope = result.get("data")
    page = envelope if isinstance(envelope, Mapping) else {}
    rows = _rows(page)
    state["rows"].extend(rows)
    state["pages_fetched"] += 1
    if operation_id not in _PAGINATED or not _has_more(page, len(rows), state["next_page"]):
        state["done"] = True
        return None
    state["next_page"] += 1
    if state["pages_fetched"] < max_pages:
        return None
    failure = _page_bound_failure(app_id, operation_id, max_pages)
    state.update(done=True, truncated=True, failure=failure)
    return failure


def _has_more(envelope: Mapping[str, Any], row_count: int, page_number: int) -> bool:
    page = envelope.get("page")
    if isinstance(page, Mapping):
        total_pages = _positive_integer(page.get("total_pages"))
        if total_pages is not None:
            return page_number < total_pages
        if isinstance(page.get("has_more"), bool):
            return bool(page["has_more"])
    return row_count >= PAGE_SIZE


def _remove_app(connection: sqlite3.Connection, app_id: str) -> None:
    connection.execute("DELETE FROM sync_failures WHERE app_id = ?", (app_id,))
    connection.execute("DELETE FROM metadata_rows WHERE app_id = ?", (app_id,))
    connection.execute("DELETE FROM apps WHERE app_id = ?", (app_id,))


def _refresh_catalog_summary(connection: sqlite3.Connection, synced_at: str) -> None:
    app_count = int(connection.execute("SELECT COUNT(*) FROM apps").fetchone()[0])
    rows_written = int(connection.execute("SELECT COUNT(*) FROM metadata_rows").fetchone()[0])
    failure_count = int(connection.execute("SELECT COUNT(*) FROM sync_failures").fetchone()[0])
    values = {
        "schema_version": "1",
        "synced_at": synced_at,
        "status": "partial" if failure_count else "success",
        "app_count": str(app_count),
        "rows_written": str(rows_written),
        "failure_count": str(failure_count),
    }
    connection.executemany(
        "INSERT OR REPLACE INTO catalog_metadata(key, value) VALUES (?, ?)",
        values.items(),
    )


def _require_compatible_catalog(path: Path) -> None:
    try:
        with closing(sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)) as connection:
            _validate_schema(connection)
    except (OSError, sqlite3.DatabaseError, InputValidationError) as exc:
        raise InputValidationError(
            "metadata database actual value is not a compatible catalog: "
            f"{actual_value(str(path))}",
            field="database",
            next_action=(
                "Back up or remove the incompatible file, then retry the same "
                "`gravity metadata sync --app-id <app-id>` command."
            ),
        ) from exc


def _app_id(value: Any) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int)) or not str(value).strip():
        raise InputValidationError(
            f"metadata App actual value must be a non-empty id: {actual_value(value)}",
            field="app_id",
            next_action="Run `gravity run app.list`, then retry with one returned App id.",
        )
    return str(value).strip()


def _max_pages(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_APP_SYNC_PAGES:
        raise InputValidationError(
            f"metadata max_pages actual value is outside 1..{MAX_APP_SYNC_PAGES}: {actual_value(value)}",
            field="max_pages",
            next_action=(
                f"Replace max_pages with an integer from 1 through {MAX_APP_SYNC_PAGES}, "
                "then retry the same App sync."
            ),
        )
    return value


def _concurrency(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_CONCURRENCY:
        raise InputValidationError(
            f"metadata concurrency actual value is outside 1..{MAX_CONCURRENCY}: {actual_value(value)}",
            field="concurrency",
            next_action=(
                f"Replace concurrency with an integer from 1 through {MAX_CONCURRENCY}, "
                "then retry the same App sync."
            ),
        )
    return value


def _destination(database: str | Path | None, *, require_file: bool = True) -> Path:
    destination = (
        Path(database) if database is not None else default_catalog_path()
    ).expanduser().resolve()
    if require_file and destination.exists() and destination.is_dir():
        raise InputValidationError(
            "metadata database actual value points to a directory: "
            f"{actual_value(str(destination))}",
            field="database",
            next_action="Replace --database with a SQLite file path, then retry the same App sync.",
        )
    return destination


def _actionable_failure(
    failure: Mapping[str, Any], app_id: str, max_pages: int
) -> dict[str, Any]:
    return {
        **dict(failure),
        "next_action": (
            "Inspect the safe code and retry `gravity metadata sync --app-id "
            f"{app_id} --max-pages {max_pages}` only when retryable."
        ),
    }


def _page_bound_failure(app_id: str, operation_id: str, max_pages: int) -> dict[str, Any]:
    next_pages = min(MAX_APP_SYNC_PAGES, max_pages + 1)
    return {
        "app_id": app_id,
        "operation_id": operation_id,
        "status": "partial",
        "category": "caller",
        "code": "PAGE_BOUND_REACHED",
        "next_action": (
            "Use the current prefix or retry the same App with "
            f"`--max-pages {next_pages}`; the hard maximum is {MAX_APP_SYNC_PAGES}."
        ),
    }


def _failure_exit_code(failures: Sequence[Mapping[str, Any]]) -> int:
    return max(
        (
            exit_code_for_category(
                str(item.get("category")), default=ErrorCategory.UPSTREAM
            )
            for item in failures
        ),
        default=0,
    )


def _receipt_count(results: Sequence[Mapping[str, Any]]) -> int | None:
    references = [
        reference
        for result in results
        for reference in result_receipt_references(result)
    ]
    return len({reference["receipt_id"] for reference in references}) if references else None


def _catalog_app_count(path: Path) -> int:
    with closing(sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)) as connection:
        return int(connection.execute("SELECT COUNT(*) FROM apps").fetchone()[0])


def _positive_integer(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


__all__ = [
    "DEFAULT_MAX_PAGES",
    "MAX_APP_SYNC_PAGES",
    "app_sync_request_budget",
    "app_sync_pages",
    "estimate_app_sync",
    "sync_app",
]
