"""Offline status contract for the synchronized metadata catalog."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .actionable_error_values import actual_value
from .errors import ErrorCategory, InputValidationError, exit_code_for_category
from .find_metadata import _catalog_values, _validate_schema
from .metadata_onboarding import _app_id, _destination
from .result_source import LOCAL_CATALOG, result_source
from .runtime_scope import public_scoped_path


SCHEMA_VERSION = "gravity.metadata-status.v1"
DEFAULT_MAX_AGE_HOURS = 24
MAX_AGE_HOURS = 8_760


def metadata_status(
    *,
    database: str | Path | None = None,
    app_id: Any | None = None,
    max_age_hours: Any = DEFAULT_MAX_AGE_HOURS,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Describe the local catalog without constructing a production client."""

    selected_app = _app_id(app_id) if app_id is not None else None
    hours = _max_age_hours(max_age_hours)
    destination = _destination(database, require_file=False)
    checked_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    base = {
        "schema_version": SCHEMA_VERSION,
        "result_source": result_source(LOCAL_CATALOG),
        "ok": True,
        "offline": True,
        "network_called": False,
        "database": public_scoped_path(destination, explicit=database is not None),
        "checked_at": _timestamp(checked_at),
        "max_age_hours": hours,
        "app_id": selected_app,
    }
    if not destination.exists():
        return {
            **base,
            "status": "missing",
            "catalog": {"exists": False, "compatible": None},
            "count": 0,
            "total": 0,
            "results": [],
            "next_action": _sync_action(selected_app),
            "exit_code": 0,
        }
    if not destination.is_file():
        return _incompatible(base)
    try:
        with closing(sqlite3.connect(f"{destination.as_uri()}?mode=ro", uri=True)) as connection:
            connection.row_factory = sqlite3.Row
            _validate_schema(connection)
            catalog = _catalog_values(connection)
            apps = _app_status_rows(
                connection,
                selected_app=selected_app,
                checked_at=checked_at,
                max_age=timedelta(hours=hours),
            )
    except (OSError, TypeError, ValueError, sqlite3.DatabaseError, InputValidationError):
        return _incompatible(base)
    if not apps:
        status = "not_synced"
        next_action = _sync_action(selected_app)
    elif any(row["sync_status"] == "partial" for row in apps):
        status = "partial"
        next_action = "Inspect each App failure and retry its bounded sync if needed."
    elif any(row["stale"] for row in apps):
        status = "stale"
        next_action = "Refresh only the stale App with `gravity metadata sync --app-id <app-id>`."
    else:
        status = "ready"
        next_action = "Use `gravity metadata events --app-id <app-id>` offline."
    return {
        **base,
        "status": status,
        "catalog": {"exists": True, "compatible": True, **catalog},
        "count": len(apps),
        "total": len(apps),
        "results": apps,
        "next_action": next_action,
        "exit_code": 0,
    }


def max_age_hours(value: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"max age hours must be an integer between 1 and {MAX_AGE_HOURS}"
        ) from exc
    if not 1 <= parsed <= MAX_AGE_HOURS:
        raise ValueError(f"max age hours must be an integer between 1 and {MAX_AGE_HOURS}")
    return parsed


def _app_status_rows(
    connection: sqlite3.Connection,
    *,
    selected_app: str | None,
    checked_at: datetime,
    max_age: timedelta,
) -> list[dict[str, Any]]:
    clauses, params = "", []
    if selected_app is not None:
        clauses, params = " WHERE app_id = ?", [selected_app]
    apps = connection.execute(
        "SELECT app_id, payload_json, synced_at FROM apps" + clauses + " ORDER BY app_id",
        params,
    ).fetchall()
    return [
        _one_app_status(
            connection, app, checked_at=checked_at, max_age=max_age
        )
        for app in apps
    ]


def _one_app_status(
    connection: sqlite3.Connection,
    app: sqlite3.Row,
    *,
    checked_at: datetime,
    max_age: timedelta,
) -> dict[str, Any]:
    app_id = str(app["app_id"])
    counts = {
        str(row[0]): int(row[1])
        for row in connection.execute(
            "SELECT operation_id, COUNT(*) FROM metadata_rows "
            "WHERE app_id = ? GROUP BY operation_id ORDER BY operation_id",
            (app_id,),
        )
    }
    failures = [
        {
            "operation_id": str(row[0]),
            "status": str(row[1]),
            "category": str(row[2]),
            "code": str(row[3]),
        }
        for row in connection.execute(
            "SELECT operation_id, status, category, code FROM sync_failures "
            "WHERE app_id = ? ORDER BY operation_id",
            (app_id,),
        )
    ]
    synced = _parse_timestamp(str(app["synced_at"]))
    age = max(timedelta(0), checked_at - synced)
    raw_payload = json.loads(str(app["payload_json"]))
    payload = raw_payload if isinstance(raw_payload, dict) else {}
    return {
        "app_id": app_id,
        "name": _optional_text(payload.get("name")),
        "synced_at": _timestamp(synced),
        "age_seconds": int(age.total_seconds()),
        "expires_at": _timestamp(synced + max_age),
        "stale": age > max_age,
        "fresh": age <= max_age,
        "sync_status": "partial" if failures else "success",
        "row_count": sum(counts.values()),
        "operation_rows": counts,
        "failure_count": len(failures),
        "failures": failures,
    }


def _incompatible(base: dict[str, Any]) -> dict[str, Any]:
    return {
        **base,
        "ok": False,
        "status": "incompatible",
        "catalog": {"exists": True, "compatible": False},
        "count": 0,
        "total": 0,
        "results": [],
        "error": {
            "code": "LOCAL_IO_ERROR",
            "category": "local",
            "message": "metadata catalog is unreadable or has an unsupported schema",
            "field": "database",
            "retryable": False,
            "retry_after_ms": None,
            "next_action": (
                "Back up the catalog, then run `gravity metadata sync --app-id "
                "<app-id>` with this database path."
            ),
        },
        "exit_code": exit_code_for_category(ErrorCategory.LOCAL),
    }


def _max_age_hours(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_AGE_HOURS:
        raise InputValidationError(
            f"metadata max_age_hours actual value is outside 1..{MAX_AGE_HOURS}: {actual_value(value)}",
            field="max_age_hours",
            next_action=(
                f"Replace max_age_hours with an integer from 1 through {MAX_AGE_HOURS}, "
                "then retry the offline status query."
            ),
        )
    return value


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return (
        parsed.replace(tzinfo=timezone.utc)
        if parsed.tzinfo is None
        else parsed.astimezone(timezone.utc)
    )


def _timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def _optional_text(value: Any) -> str | None:
    return (
        str(value)
        if isinstance(value, (str, int)) and not isinstance(value, bool)
        else None
    )


def _sync_action(app_id: str | None) -> str:
    return (
        f"Run `gravity metadata sync --app-id {app_id}`."
        if app_id is not None
        else "Run `gravity metadata sync --app-id <app-id>` for the App you need."
    )


__all__ = [
    "DEFAULT_MAX_AGE_HOURS",
    "SCHEMA_VERSION",
    "max_age_hours",
    "metadata_status",
]
