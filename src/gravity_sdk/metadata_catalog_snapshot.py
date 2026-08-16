"""Pinned, read-only metadata snapshots for reviewed Analysis Plans."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections.abc import Mapping
from contextlib import closing
from pathlib import Path
from typing import Any

from .actionable_error_values import actual_value
from .domains import ANALYSIS_METADATA_OPERATIONS
from .errors import InputValidationError
from .metadata_onboarding import _app_id
from .metadata_status import metadata_status
from .metadata_sync import default_catalog_path


SNAPSHOT_SCHEMA_VERSION = "gravity.metadata-snapshot.v1"
_SNAPSHOT_FIELDS = frozenset(
    {"schema_version", "app_id", "synced_at", "fingerprint", "database"}
)
_FINGERPRINT = re.compile(r"^[0-9a-f]{64}$")
_SUPPORTED_OPERATIONS = frozenset(ANALYSIS_METADATA_OPERATIONS)


def create_metadata_snapshot(
    app_id: Any, *, database: str | Path | None = None
) -> dict[str, str]:
    """Pin one fresh, complete App catalog without reading production."""

    selected_app = _app_id(app_id)
    selected_database = _database(database)
    status = metadata_status(database=selected_database, app_id=selected_app)
    if status.get("status") != "ready" or status.get("count") != 1:
        raise _input_error(
            "metadata catalog actual value: "
            f"{actual_value({'app_id': selected_app, 'status': status.get('status')})}; "
            "allowed value: one fresh, complete App snapshot",
            "metadata_catalog.status",
            _bootstrap_action(selected_app),
        )
    result = status.get("results")
    app_status = result[0] if isinstance(result, list) and result else {}
    synced_at = app_status.get("synced_at") if isinstance(app_status, Mapping) else None
    if not isinstance(synced_at, str) or not synced_at:
        raise _input_error(
            f"metadata catalog synced_at actual value: {actual_value(synced_at)}; "
            "allowed value: a timestamp from the completed App sync",
            "metadata_catalog.synced_at",
            _bootstrap_action(selected_app),
        )
    fingerprint = _catalog_fingerprint(selected_database, selected_app, synced_at)
    return {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "app_id": selected_app,
        "synced_at": synced_at,
        "fingerprint": fingerprint,
        "database": str(selected_database),
    }


def validate_metadata_snapshot(
    value: Any, *, expected_app: Any | None = None
) -> dict[str, str]:
    """Validate only the Plan-carried snapshot shape; perform no file I/O."""

    if not isinstance(value, Mapping) or set(value) != _SNAPSHOT_FIELDS:
        observed = sorted(value) if isinstance(value, Mapping) else type(value).__name__
        raise _input_error(
            f"metadata snapshot actual value: {actual_value(observed)}; allowed fields: "
            f"{actual_value(sorted(_SNAPSHOT_FIELDS))}",
            "metadata_snapshot",
            "Run `gravity analysis bootstrap --help`, then regenerate the Plan.",
        )
    schema = value.get("schema_version")
    if schema != SNAPSHOT_SCHEMA_VERSION:
        raise _input_error(
            f"metadata snapshot schema actual value: {actual_value(schema)}; allowed "
            f"value: {actual_value(SNAPSHOT_SCHEMA_VERSION)}",
            "metadata_snapshot.schema_version",
            "Run `gravity analysis bootstrap --help`, then regenerate the Plan.",
        )
    selected_app = _app_id(value.get("app_id"))
    if expected_app is not None and selected_app != str(expected_app).strip():
        raise _input_error(
            "metadata snapshot App actual value: "
            f"{actual_value(selected_app)}; allowed value: {actual_value(str(expected_app).strip())}",
            "metadata_snapshot.app_id",
            "Run `gravity analysis bootstrap --help`, then regenerate the Plan for the selected App.",
        )
    synced_at = value.get("synced_at")
    if not isinstance(synced_at, str) or not synced_at.strip():
        raise _input_error(
            f"metadata snapshot synced_at actual value: {actual_value(synced_at)}; "
            "allowed value: a non-empty sync timestamp",
            "metadata_snapshot.synced_at",
            "Run `gravity analysis bootstrap --help`, then regenerate the Plan.",
        )
    fingerprint = value.get("fingerprint")
    if not isinstance(fingerprint, str) or not _FINGERPRINT.fullmatch(fingerprint):
        raise _input_error(
            f"metadata snapshot fingerprint actual value: {actual_value(fingerprint)}; "
            "allowed value: a 64-character lowercase SHA-256 digest",
            "metadata_snapshot.fingerprint",
            "Run `gravity analysis bootstrap --help`, then regenerate the Plan.",
        )
    database = value.get("database")
    if not isinstance(database, str) or not database.strip():
        raise _input_error(
            f"metadata snapshot database actual value: {actual_value(database)}; "
            "allowed value: the SQLite path emitted by bootstrap",
            "metadata_snapshot.database",
            "Run `gravity analysis bootstrap --help`, then regenerate the Plan.",
        )
    return {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "app_id": selected_app,
        "synced_at": synced_at.strip(),
        "fingerprint": fingerprint,
        "database": str(Path(database).expanduser().resolve()),
    }


def metadata_snapshot_loader(value: Any):
    """Return a FieldPolicy loader after verifying the pinned catalog bytes."""

    snapshot = validate_metadata_snapshot(value)
    current = create_metadata_snapshot(
        snapshot["app_id"], database=snapshot["database"]
    )
    for field in ("synced_at", "fingerprint"):
        if current[field] != snapshot[field]:
            raise _input_error(
                f"metadata snapshot {field} actual value: {actual_value(current[field])}; "
                f"allowed pinned value: {actual_value(snapshot[field])}",
                f"metadata_snapshot.{field}",
                _bootstrap_action(snapshot["app_id"]),
            )
    rows = _catalog_rows(Path(snapshot["database"]), snapshot["app_id"])

    def load(operation_id: str, inputs: Mapping[str, Any]) -> Mapping[str, Any]:
        if operation_id not in _SUPPORTED_OPERATIONS:
            raise _input_error(
                f"metadata snapshot operation actual value: {actual_value(operation_id)}; "
                f"allowed values: {actual_value(sorted(_SUPPORTED_OPERATIONS))}",
                "metadata_snapshot.operation_id",
                "Run `gravity analysis bootstrap --help` and regenerate the simple event-count Plan, or remove the snapshot to use normal live metadata validation.",
            )
        observed_app = inputs.get("app_id")
        if str(observed_app).strip() != snapshot["app_id"]:
            raise _input_error(
                f"metadata loader App actual value: {actual_value(observed_app)}; "
                f"allowed pinned value: {actual_value(snapshot['app_id'])}",
                "metadata_snapshot.app_id",
                _bootstrap_action(snapshot["app_id"]),
            )
        selected = rows.get(operation_id, ())
        return {
            "schema_version": "gravity-insight.read.v1",
            "ok": True,
            "status": "success" if selected else "empty",
            "operation_id": operation_id,
            "data": {"list": list(selected)},
        }

    return load


def _catalog_rows(database: Path, app_id: str) -> dict[str, tuple[dict[str, Any], ...]]:
    grouped: dict[str, list[dict[str, Any]]] = {
        operation_id: [] for operation_id in _SUPPORTED_OPERATIONS
    }
    try:
        with closing(sqlite3.connect(f"{database.as_uri()}?mode=ro", uri=True)) as connection:
            rows = connection.execute(
                "SELECT operation_id, payload_json FROM metadata_rows "
                "WHERE app_id = ? ORDER BY operation_id, row_index",
                (app_id,),
            ).fetchall()
    except (OSError, sqlite3.DatabaseError) as exc:
        raise _input_error(
            f"metadata snapshot database actual value: {actual_value(str(database))}; "
            "allowed value: a readable compatible SQLite catalog",
            "metadata_snapshot.database",
            _bootstrap_action(app_id),
        ) from exc
    for operation_id, payload_json in rows:
        try:
            payload = json.loads(str(payload_json))
        except (TypeError, ValueError) as exc:
            raise _input_error(
                f"metadata snapshot row actual value: {actual_value('invalid_json')}; "
                "allowed value: a projected metadata object",
                "metadata_snapshot.rows[]",
                _bootstrap_action(app_id),
            ) from exc
        if not isinstance(payload, Mapping):
            raise _input_error(
                f"metadata snapshot row actual value: {actual_value(type(payload).__name__)}; "
                "allowed value: a projected metadata object",
                "metadata_snapshot.rows[]",
                _bootstrap_action(app_id),
            )
        if str(operation_id) in grouped:
            grouped[str(operation_id)].append(dict(payload))
    return {key: tuple(value) for key, value in grouped.items()}


def _catalog_fingerprint(database: Path, app_id: str, synced_at: str) -> str:
    try:
        with closing(sqlite3.connect(f"{database.as_uri()}?mode=ro", uri=True)) as connection:
            app = connection.execute(
                "SELECT payload_json FROM apps WHERE app_id = ? AND synced_at = ?",
                (app_id, synced_at),
            ).fetchone()
            rows = connection.execute(
                "SELECT operation_id, row_index, payload_json FROM metadata_rows "
                "WHERE app_id = ? ORDER BY operation_id, row_index",
                (app_id,),
            ).fetchall()
            failures = connection.execute(
                "SELECT operation_id, status, category, code FROM sync_failures "
                "WHERE app_id = ? ORDER BY operation_id",
                (app_id,),
            ).fetchall()
    except (OSError, sqlite3.DatabaseError) as exc:
        raise _input_error(
            f"metadata catalog database actual value: {actual_value(str(database))}; "
            "allowed value: a readable compatible SQLite catalog",
            "metadata_catalog.database",
            _bootstrap_action(app_id),
        ) from exc
    if app is None:
        raise _input_error(
            f"metadata catalog App actual value: {actual_value(app_id)}; allowed value: "
            "one App present at the reported sync timestamp",
            "metadata_catalog.app_id",
            _bootstrap_action(app_id),
        )
    material = {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "app_id": app_id,
        "synced_at": synced_at,
        "operations": sorted(_SUPPORTED_OPERATIONS),
        "app": str(app[0]),
        "rows": [list(item) for item in rows],
        "failures": [list(item) for item in failures],
    }
    encoded = json.dumps(
        material, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _database(value: str | Path | None) -> Path:
    return (
        Path(value) if value is not None else default_catalog_path()
    ).expanduser().resolve()


def _bootstrap_action(app_id: str) -> str:
    return (
        "Run `gravity analysis bootstrap --app "
        f"{app_id} --start <date> --end <date> --target <physical-event>` "
        "again to refresh and regenerate the Plan."
    )


def _input_error(
    message: str, field: str, next_action: str
) -> InputValidationError:
    return InputValidationError(message, field=field, next_action=next_action)


__all__ = [
    "SNAPSHOT_SCHEMA_VERSION",
    "create_metadata_snapshot",
    "metadata_snapshot_loader",
    "validate_metadata_snapshot",
]
