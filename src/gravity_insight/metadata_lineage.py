"""Account-scoped, observed data-table lineage for the offline catalog.

The stable upstream sources expose identifiers and timestamps, but no verified
table name, App ownership, or current-version semantic.  This module therefore
stores and returns only observed facts from those projections.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

from .cli_limits import metadata_limit, nonnegative_int
from .composite_catalog import stable_operation
from .errors import ContractChangedError, InputValidationError, UpstreamError
from .find_metadata import (
    _catalog_values,
    _default_catalog_path,
    _validate_schema,
    search_limit,
    search_offset,
)
from .runtime import call_batch
from .result_source import LOCAL_CATALOG, result_source
from .actionable_error_values import actual_value
from .runtime_scope import public_scoped_path


SCHEMA_VERSION = "gravity.metadata-table-lineage.v1"
TABLE_VERSION_OPERATION_ID = stable_operation(
    "metadata", "version", action="list"
).operation_id
TABLE_OPERATION_LOG_OPERATION_ID = stable_operation(
    "metadata", "operation_log", action="list"
).operation_id
TABLE_LINEAGE_OPERATIONS = (
    TABLE_VERSION_OPERATION_ID,
    TABLE_OPERATION_LOG_OPERATION_ID,
)


class TableLineageClient(Protocol):
    def batch(
        self,
        requests: Sequence[Mapping[str, Any]],
        **kwargs: Any,
    ) -> Sequence[Mapping[str, Any]]: ...


def add_table_lineage_commands(metadata_commands: Any, sync: Any) -> None:
    sync.add_argument(
        "--include-table-lineage",
        action="store_true",
        help=(
            "Also synchronize the account-scoped observed data-table version and "
            "operation timeline."
        ),
    )
    tables = metadata_commands.add_parser(
        "tables",
        help="Search the observed account-scoped data-table lineage offline.",
    )
    tables.set_defaults(network_required=False)
    tables.add_argument("query", nargs="?", default="")
    tables.add_argument("--database", type=Path, default=None)
    tables.add_argument("--limit", type=metadata_limit, default=20)
    tables.add_argument("--offset", type=nonnegative_int, default=0)


def create_table_lineage_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE table_versions (
            row_index INTEGER PRIMARY KEY,
            source_id TEXT,
            table_id TEXT NOT NULL,
            version_id TEXT,
            create_time TEXT,
            observed_at TEXT NOT NULL
        );
        CREATE INDEX table_versions_table_idx
            ON table_versions(table_id, create_time);
        CREATE TABLE table_operation_logs (
            row_index INTEGER PRIMARY KEY,
            source_id TEXT,
            table_id TEXT NOT NULL,
            version_id TEXT,
            action_type TEXT,
            action_sub_type TEXT,
            create_time TEXT,
            observed_at TEXT NOT NULL
        );
        CREATE INDEX table_operation_logs_table_idx
            ON table_operation_logs(table_id, create_time);
        """
    )


def sync_table_lineage(
    connection: sqlite3.Connection,
    client: TableLineageClient,
    concurrency: int,
    observed_at: str,
) -> dict[str, int]:
    """Read each account-scoped lineage source exactly once."""

    requests = [
        {
            "operation_id": operation_id,
            "request_id": operation_id,
            "inputs": {"page": 1, "page_size": 100},
            "read_all": True,
        }
        for operation_id in TABLE_LINEAGE_OPERATIONS
    ]
    results = call_batch(client, requests, concurrency=min(concurrency, len(requests)))
    if not isinstance(results, Sequence) or len(results) != len(requests):
        raise UpstreamError(
            "Gravity data-table lineage returned an incomplete batch; "
            "the local catalog was not replaced"
        )

    rows_by_operation: dict[str, list[Mapping[str, Any]]] = {}
    for operation_id, result in zip(TABLE_LINEAGE_OPERATIONS, results):
        rows_by_operation[operation_id] = _result_rows(operation_id, result)

    versions = rows_by_operation[TABLE_VERSION_OPERATION_ID]
    logs = rows_by_operation[TABLE_OPERATION_LOG_OPERATION_ID]
    _write_table_versions(connection, versions, observed_at)
    _write_table_operation_logs(connection, logs, observed_at)
    return {
        TABLE_VERSION_OPERATION_ID: len(versions),
        TABLE_OPERATION_LOG_OPERATION_ID: len(logs),
    }


def lineage_catalog_values(counts: Mapping[str, int]) -> dict[str, str]:
    return {
        "table_lineage_observed": "true",
        "table_version_count": str(counts.get(TABLE_VERSION_OPERATION_ID, 0)),
        "table_operation_log_count": str(
            counts.get(TABLE_OPERATION_LOG_OPERATION_ID, 0)
        ),
    }


def search_table_lineage(
    query: str = "",
    *,
    database: str | Path | None = None,
    limit: int = 20,
    offset: int = 0,
) -> dict[str, Any]:
    """Search an opt-in lineage snapshot without constructing a client."""

    if not isinstance(query, str):
        raise InputValidationError(
            f"actual value: {actual_value(query)}; " + ("table lineage query must be a string"), field="query"
        )
    search_limit(limit)
    search_offset(offset)
    catalog = Path(database) if database is not None else _default_catalog_path()
    catalog = catalog.expanduser().resolve()
    public_catalog = public_scoped_path(catalog, explicit=database is not None)
    if not catalog.is_file():
        raise InputValidationError(
            f"actual value: {actual_value(public_catalog)}; " + ("metadata catalog does not exist; run `gravity metadata sync --all-apps "
            "--include-table-lineage`"),
            field="database",
            next_action=(
                "Run `gravity metadata sync --all-apps --include-table-lineage`, "
                "then retry."
            ),
        )
    connection = sqlite3.connect(f"{catalog.as_uri()}?mode=ro", uri=True)
    try:
        connection.row_factory = sqlite3.Row
        _validate_schema(connection)
        _require_lineage_snapshot(connection)
        catalog_status = _catalog_values(connection)
        results = _table_results(connection, query)
    finally:
        connection.close()
    page = results[offset : offset + limit]
    return {
        "schema_version": SCHEMA_VERSION,
        "result_source": result_source(LOCAL_CATALOG),
        "ok": True,
        "status": "success",
        "offline": True,
        "scope": "account",
        "observed": True,
        "query": query,
        "database": public_catalog,
        "catalog": catalog_status,
        "count": len(page),
        "total": len(results),
        "limit": limit,
        "offset": offset,
        "results": page,
    }


def _result_rows(operation_id: str, result: Any) -> list[Mapping[str, Any]]:
    if not isinstance(result, Mapping):
        raise UpstreamError(
            f"{operation_id} returned an invalid batch result; "
            "the local catalog was not replaced"
        )
    status = str(result.get("status", "error"))
    if not bool(result.get("ok")) or status not in {
        "success",
        "empty",
        "contract_changed_additive",
    }:
        if status in {"contract_changed", "upstream_changed"}:
            raise ContractChangedError(
                f"{operation_id} changed; the local catalog was not replaced"
            )
        raise UpstreamError(
            f"{operation_id} is unavailable; the local catalog was not replaced"
        )
    envelope = result.get("data")
    rows = _rows(envelope if isinstance(envelope, Mapping) else {})
    for row in rows:
        table_id = row.get("table_id")
        if (
            not isinstance(table_id, (str, int))
            or isinstance(table_id, bool)
            or not str(table_id)
        ):
            raise ContractChangedError(
                f"{operation_id} omitted table_id; the local catalog was not replaced"
            )
    return rows


def _rows(envelope: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    data: Any = envelope.get("data")
    if isinstance(data, list):
        values = data
    elif isinstance(data, Mapping):
        values = data.get("list", data.get("items", []))
    else:
        values = []
    if not isinstance(values, list):
        return []
    return [item for item in values if isinstance(item, Mapping)]


def _write_table_versions(
    connection: sqlite3.Connection,
    rows: Sequence[Mapping[str, Any]],
    observed_at: str,
) -> None:
    connection.executemany(
        "INSERT INTO table_versions(row_index, source_id, table_id, version_id, "
        "create_time, observed_at) VALUES (?, ?, ?, ?, ?, ?)",
        [
            (
                index,
                _optional_text(row.get("id")),
                str(row["table_id"]),
                _optional_text(row.get("version_id")),
                _optional_text(row.get("create_time")),
                observed_at,
            )
            for index, row in enumerate(rows)
        ],
    )


def _write_table_operation_logs(
    connection: sqlite3.Connection,
    rows: Sequence[Mapping[str, Any]],
    observed_at: str,
) -> None:
    connection.executemany(
        "INSERT INTO table_operation_logs(row_index, source_id, table_id, version_id, "
        "action_type, action_sub_type, create_time, observed_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                index,
                _optional_text(row.get("id")),
                str(row["table_id"]),
                _optional_text(row.get("version_id")),
                _optional_text(row.get("action_type")),
                _optional_text(row.get("action_sub_type")),
                _optional_text(row.get("create_time")),
                observed_at,
            )
            for index, row in enumerate(rows)
        ],
    )


def _require_lineage_snapshot(connection: sqlite3.Connection) -> None:
    tables = {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    observed = connection.execute(
        "SELECT value FROM catalog_metadata WHERE key = 'table_lineage_observed'"
    ).fetchone()
    if not {"table_versions", "table_operation_logs"} <= tables or observed is None:
        raise InputValidationError(
            f"actual value: {actual_value(sorted(tables))}; " + ("metadata catalog has no observed table lineage; run `gravity metadata "
            "sync --all-apps --include-table-lineage`"),
            field="database",
            next_action=(
                "Run `gravity metadata sync --all-apps --include-table-lineage`, "
                "then retry."
            ),
        )


def _table_results(connection: sqlite3.Connection, query: str) -> list[dict[str, Any]]:
    normalized = query.strip().casefold()
    versions: dict[str, list[dict[str, Any]]] = {}
    logs: dict[str, list[dict[str, Any]]] = {}
    for row in connection.execute(
        "SELECT table_id, version_id, create_time, observed_at FROM table_versions"
    ):
        item = _without_none(
            {
                "version_id": row["version_id"],
                "create_time": row["create_time"],
                "observed_at": row["observed_at"],
            }
        )
        versions.setdefault(str(row["table_id"]), []).append(item)
    for row in connection.execute(
        "SELECT table_id, version_id, action_type, action_sub_type, create_time, "
        "observed_at FROM table_operation_logs"
    ):
        item = _without_none(
            {
                "version_id": row["version_id"],
                "action_type": row["action_type"],
                "action_sub_type": row["action_sub_type"],
                "create_time": row["create_time"],
                "observed_at": row["observed_at"],
            }
        )
        logs.setdefault(str(row["table_id"]), []).append(item)
    results = []
    for table_id in sorted(set(versions) | set(logs)):
        item = {
            "table_id": table_id,
            "observed": True,
            "versions": sorted(versions.get(table_id, []), key=_timeline_key),
            "operations": sorted(logs.get(table_id, []), key=_timeline_key),
        }
        haystack = str(item).casefold()
        if not normalized or normalized in haystack:
            results.append(item)
    return results


def _timeline_key(item: Mapping[str, Any]) -> tuple[str, str]:
    return str(item.get("create_time", "")), str(item.get("version_id", ""))


def _without_none(item: Mapping[str, Any]) -> dict[str, Any]:
    return {str(key): value for key, value in item.items() if value is not None}


def _optional_text(value: Any) -> str | None:
    return str(value) if isinstance(value, (str, int)) and not isinstance(value, bool) else None


__all__ = [
    "TABLE_LINEAGE_OPERATIONS",
    "add_table_lineage_commands",
    "create_table_lineage_schema",
    "lineage_catalog_values",
    "search_table_lineage",
    "sync_table_lineage",
]
