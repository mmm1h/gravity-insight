"""Read-only search over synchronized Gravity metadata SQLite catalogs."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from .domains import ANALYSIS_METADATA_OPERATIONS
from .errors import InputValidationError
from .metadata_vocabulary import (
    VOCABULARY_SEARCH_KINDS,
    vocabulary_failures,
    vocabulary_rows,
)
from .result_source import LOCAL_CATALOG, result_source
from .actionable_error_values import actual_value
from .runtime_scope import metadata_catalog_path, public_scoped_path


SCHEMA_VERSION = "gravity.metadata-search.v1"
DATABASE_SCHEMA_VERSION = 1
_EVENT_OPERATIONS = tuple(
    value for value in ANALYSIS_METADATA_OPERATIONS if value.endswith(".event.list")
)
_PROPERTY_OPERATIONS = tuple(
    value
    for value in ANALYSIS_METADATA_OPERATIONS
    if value.endswith((".user_property.list", ".event_property.list"))
)
_APP_KINDS = {"all", "event", "property"}
_VOCABULARY_KINDS = set(VOCABULARY_SEARCH_KINDS)


def search_metadata(
    query: str = "",
    *,
    database: str | Path | None = None,
    app_id: str | None = None,
    kind: str = "all",
    limit: int | None = 20,
    offset: int = 0,
) -> dict[str, Any]:
    """Search the synchronized catalog without creating a network client."""

    if kind not in _APP_KINDS | _VOCABULARY_KINDS:
        raise InputValidationError("unknown metadata search kind", field="kind", next_action="Use a documented metadata search kind and retry.")
    if app_id is not None and kind in _VOCABULARY_KINDS:
        raise InputValidationError(
            "workspace Analysis vocabulary cannot be filtered by app_id",
            field="app_id", next_action="Omit app_id or switch to an App-scoped source.",
        )
    if limit is not None:
        search_limit(limit)
    search_offset(offset)
    catalog = Path(database) if database is not None else _default_catalog_path()
    catalog = catalog.expanduser().resolve()
    public_catalog = public_scoped_path(catalog, explicit=database is not None)
    if not catalog.is_file():
        raise InputValidationError(
            f"actual value: {actual_value(public_catalog)}; " + ("metadata catalog does not exist; run `gravity metadata sync --all-apps`"),
            field="database",
        )
    with closing(sqlite3.connect(f"{catalog.as_uri()}?mode=ro", uri=True)) as connection:
        connection.row_factory = sqlite3.Row
        _validate_schema(connection)
        catalog_status = _catalog_values(connection)
        candidates = (
            _candidates(connection, query, app_id, kind)
            if kind in _APP_KINDS
            else []
        )
        include_vocabulary = kind in _VOCABULARY_KINDS or (
            kind == "all"
            and app_id is None
            and catalog_status.get("analysis_vocabulary_observed", "").casefold()
            == "true"
        )
        vocabulary_kind = kind if kind in _VOCABULARY_KINDS else "vocabulary"
        catalog_failures: list[dict[str, str]] = []
        if include_vocabulary:
            candidates.extend(
                _vocabulary_candidates(connection, query, vocabulary_kind)
            )
            catalog_failures = vocabulary_failures(connection)
    ordered = sorted(candidates, key=_sort_key)
    page = ordered[offset:] if limit is None else ordered[offset : offset + limit]
    result = {
        "schema_version": SCHEMA_VERSION,
        "result_source": result_source(LOCAL_CATALOG),
        "ok": True,
        "status": "success",
        "offline": True,
        "query": query,
        "kind": kind,
        "database": public_catalog,
        "catalog": catalog_status,
        "count": len(page),
        "total": len(ordered),
        "limit": limit,
        "offset": offset,
        "results": page,
    }
    if kind in _VOCABULARY_KINDS:
        result.update(scope="workspace", failures=catalog_failures)
    return result


def _vocabulary_candidates(
    connection: sqlite3.Connection,
    query: str,
    kind: str,
) -> list[dict[str, Any]]:
    normalized = query.strip().casefold()
    results = []
    for row in vocabulary_rows(connection, query, kind):
        name = _optional_text(row["name"])
        cname = _optional_text(row["cname"])
        results.append(
            {
                "backend": "metadata",
                "kind": str(row["kind"]),
                "scope": "workspace",
                "source": str(row["source"]),
                "operation_id": str(row["operation_id"]),
                "name": name,
                "cname": cname,
                "score": _score(normalized, name, cname, str(row["payload_json"])),
                "payload": json.loads(row["payload_json"]),
            }
        )
    return results


def _candidates(
    connection: sqlite3.Connection,
    query: str,
    app_id: str | None,
    kind: str,
) -> list[dict[str, Any]]:
    normalized = query.strip().casefold()
    pattern = f"%{_escape_like(query.strip())}%"
    results = _app_candidates(connection, query, pattern, app_id) if kind == "all" else []
    operations = {
        "event": _EVENT_OPERATIONS,
        "property": _PROPERTY_OPERATIONS,
        "all": tuple(ANALYSIS_METADATA_OPERATIONS),
    }[kind]
    placeholders = ",".join("?" for _ in operations)
    clauses = [f"operation_id IN ({placeholders})"]
    params: list[Any] = list(operations)
    if app_id is not None:
        clauses.append("app_id = ?")
        params.append(str(app_id))
    if query.strip():
        clauses.append(
            "(name LIKE ? ESCAPE '\\' OR cname LIKE ? ESCAPE '\\' "
            "OR payload_json LIKE ? ESCAPE '\\')"
        )
        params.extend((pattern, pattern, pattern))
    rows = connection.execute(
        "SELECT app_id, operation_id, name, cname, payload_json "
        "FROM metadata_rows WHERE " + " AND ".join(clauses),
        params,
    ).fetchall()
    results.extend(_row_result(row, normalized) for row in rows)
    return results


def _app_candidates(
    connection: sqlite3.Connection,
    query: str,
    pattern: str,
    app_id: str | None,
) -> list[dict[str, Any]]:
    clauses = ["(? = '' OR payload_json LIKE ? ESCAPE '\\')"]
    params: list[Any] = [query.strip(), pattern]
    if app_id is not None:
        clauses.append("app_id = ?")
        params.append(str(app_id))
    rows = connection.execute(
        "SELECT app_id, payload_json FROM apps WHERE " + " AND ".join(clauses), params
    ).fetchall()
    results = []
    for row in rows:
        payload = json.loads(row["payload_json"])
        name = _optional_text(payload.get("name")) or str(row["app_id"])
        results.append(
            {
                "backend": "metadata",
                "kind": "app",
                "app_id": str(row["app_id"]),
                "name": name,
                "cname": _optional_text(payload.get("cname")),
                "operation_id": None,
                "score": _score(query.casefold(), name, None, row["payload_json"]),
                "payload": payload,
            }
        )
    return results


def _row_result(row: sqlite3.Row, query: str) -> dict[str, Any]:
    operation_id = str(row["operation_id"])
    name, cname = _optional_text(row["name"]), _optional_text(row["cname"])
    return {
        "backend": "metadata",
        "kind": _metadata_kind(operation_id),
        "app_id": str(row["app_id"]),
        "operation_id": operation_id,
        "name": name,
        "cname": cname,
        "score": _score(query, name, cname, row["payload_json"]),
        "payload": json.loads(row["payload_json"]),
    }


def _metadata_kind(operation_id: str) -> str:
    resource = operation_id.removeprefix("analysis.").removesuffix(".list")
    return resource if resource in {"event", "user_property", "event_property"} else "event_property_group"


def _score(query: str, name: str | None, cname: str | None, payload_json: str) -> int:
    if not query:
        return 0
    values = tuple(value.casefold() for value in (name, cname) if value)
    if query in values:
        return 100
    if any(value.startswith(query) for value in values):
        return 80
    if any(query in value for value in values):
        return 60
    return 20 if query in payload_json.casefold() else 0


def _sort_key(item: dict[str, Any]) -> tuple[Any, ...]:
    return (
        -int(item["score"]),
        str(item["kind"]),
        str(item.get("app_id", "")),
        str(item.get("name", "")).casefold(),
        str(item.get("operation_id", "")),
    )


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _validate_schema(connection: sqlite3.Connection) -> None:
    version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    tables = {
        str(row[0])
        for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    if version != DATABASE_SCHEMA_VERSION or not {
        "apps",
        "metadata_rows",
        "catalog_metadata",
    } <= tables:
        raise InputValidationError(
            f"actual value: {actual_value(version)}; " + ("metadata catalog schema is unsupported; run `gravity metadata sync --all-apps`"),
            field="database",
        )


def _catalog_values(connection: sqlite3.Connection) -> dict[str, str]:
    return {
        str(row[0]): str(row[1])
        for row in connection.execute("SELECT key, value FROM catalog_metadata")
    }


def search_limit(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 100:
        raise InputValidationError(
            f"actual value: {actual_value(value)}; " + ("metadata search limit must be between 1 and 100"), field="limit"
        )
    return value


def search_offset(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise InputValidationError(
            f"actual value: {actual_value(value)}; " + ("metadata search offset must be a non-negative integer"), field="offset"
        )
    return value


def _optional_text(value: Any) -> str | None:
    return str(value) if isinstance(value, (str, int)) and not isinstance(value, bool) else None


def _default_catalog_path(*, isolation_key: str = "") -> Path:
    return metadata_catalog_path(isolation_key)


__all__ = ["search_metadata"]
