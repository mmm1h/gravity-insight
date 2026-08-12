"""Persist a governed, cross-application snapshot of Gravity metadata."""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

from .domains import (
    ANALYSIS_METADATA_OPERATIONS,
    ANALYSIS_PAGINATED_OPERATIONS,
    DOMAIN_OPERATIONS,
)
from .errors import ContractChangedError, InputValidationError, UpstreamError
from .find_metadata import search_metadata
from .cli_limits import metadata_limit, nonnegative_int
from .metadata_lineage import (
    TABLE_LINEAGE_OPERATIONS,
    add_table_lineage_commands,
    create_table_lineage_schema,
    lineage_catalog_values,
    search_table_lineage,
    sync_table_lineage,
)
from . import metadata_vocabulary as vocabulary
from .runtime import call_batch


SCHEMA_VERSION = "gravity-insight.metadata-sync.v1"
DATABASE_SCHEMA_VERSION = 1
APP_OPERATION_ID = DOMAIN_OPERATIONS["apps.list"][0]
DEFAULT_CONCURRENCY = 8
MAX_CONCURRENCY = 24
# batch() divides its 100,000-row aggregate allowance among requests. Keeping
# every mixed operation/app batch at eight requests leaves 12,500 rows for each
# catalog slice while allowing small workspaces to use more than one worker.
MAX_REQUESTS_PER_BATCH = 8


class MetadataSyncClient(Protocol):
    def read_all(
        self,
        operation_id: str,
        inputs: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> Mapping[str, Any]: ...

    def batch(
        self,
        requests: Sequence[Mapping[str, Any]],
        **kwargs: Any,
    ) -> Sequence[Mapping[str, Any]]: ...


def add_metadata_commands(
    commands: Any,
    concurrency_parser: Any,
    input_adder: Any,
    all_pages_adder: Any,
) -> tuple[Any, Any]:
    apps = commands.add_parser("apps")
    apps_commands = apps.add_subparsers(dest="apps_command", required=True)
    apps_list = apps_commands.add_parser("list")
    input_adder(apps_list)
    all_pages_adder(apps_list)
    metadata = commands.add_parser(
        "metadata", help="Synchronize and search governed local Gravity metadata."
    )
    metadata_commands = metadata.add_subparsers(
        dest="metadata_command", required=True
    )
    sync = metadata_commands.add_parser(
        "sync", help="Download application metadata into a local SQLite catalog."
    )
    sync.add_argument(
        "--all-apps", action="store_true", required=True,
        help="Synchronize every application visible to the current account.",
    )
    sync.add_argument(
        "--database", type=Path, default=None,
        help="Override the private per-user SQLite catalog path.",
    )
    sync.add_argument("--concurrency", type=concurrency_parser, default=8)
    for name, help_text in (
        ("search", "Search applications, events, and properties offline."),
        ("events", "List or search synchronized events offline."),
        ("properties", "List or search synchronized properties offline."),
    ):
        query = metadata_commands.add_parser(name, help=help_text)
        query.set_defaults(network_required=False)
        query.add_argument("query", nargs="?", default="")
        query.add_argument("--app-id")
        query.add_argument("--database", type=Path, default=None)
        query.add_argument("--limit", type=metadata_limit, default=20)
        query.add_argument("--offset", type=nonnegative_int, default=0)
    vocabulary.add_vocabulary_command(
        metadata_commands, metadata_limit, nonnegative_int
    )
    add_table_lineage_commands(metadata_commands, sync)
    return apps_commands, metadata_commands


def run_metadata_command(args: Any, client_builder: Any) -> dict[str, Any]:
    if args.metadata_command == "sync":
        if not args.all_apps:
            raise InputValidationError("metadata sync currently requires --all-apps")
        options = {"database": args.database, "concurrency": args.concurrency}
        if bool(args.include_table_lineage):
            options["include_table_lineage"] = True
        return sync_all_apps(client_builder(args), **options)
    if args.metadata_command == "tables":
        return search_table_lineage(
            args.query,
            database=args.database,
            limit=args.limit,
            offset=args.offset,
        )
    if args.metadata_command == "vocabulary":
        return vocabulary.run_vocabulary_search(args)
    kind = getattr(args, "kind", None) or {"search": "all", "events": "event", "properties": "property"}[args.metadata_command]
    return search_metadata(
        args.query,
        database=args.database,
        app_id=getattr(args, "app_id", None),
        kind=kind,
        limit=args.limit,
        offset=args.offset,
    )


def run_analysis_metadata(
    args: Any,
    client_builder: Any,
    object_input: Any,
) -> Any:
    client = client_builder(args)
    supplied = object_input(args.input)
    keyed_input = any(
        operation_id in supplied for operation_id in ANALYSIS_METADATA_OPERATIONS
    )
    requests: list[dict[str, Any]] = []
    for operation_id in ANALYSIS_METADATA_OPERATIONS:
        operation_input = supplied.get(operation_id, {}) if keyed_input else supplied
        if not isinstance(operation_input, Mapping):
            raise InputValidationError(
                f"analysis metadata input for {operation_id} must be an object"
            )
        inputs = {"app_id": str(args.app_id), **dict(operation_input)}
        if operation_id in ANALYSIS_PAGINATED_OPERATIONS:
            inputs.setdefault("page", 1)
            inputs.setdefault("page_size", 2_000)
        inputs["app_id"] = str(args.app_id)
        requests.append(
            {"operation_id": operation_id, "inputs": inputs, "read_all": True}
        )
    return call_batch(client, requests, concurrency=4)


def default_catalog_path() -> Path:
    """Return the private per-user catalog path without requiring an env var."""

    cache_root = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_CACHE_HOME")
    if cache_root:
        return Path(cache_root) / "GravityInsight" / "metadata" / "catalog.sqlite3"
    return Path.home() / ".cache" / "gravity-insight" / "metadata" / "catalog.sqlite3"


def sync_all_apps(
    client: MetadataSyncClient,
    *,
    database: str | Path | None = None,
    concurrency: int = DEFAULT_CONCURRENCY,
    include_table_lineage: bool = False,
) -> dict[str, Any]:
    """Download every readable app's stable Analysis metadata into SQLite."""

    if isinstance(concurrency, bool) or not 1 <= concurrency <= MAX_CONCURRENCY:
        raise InputValidationError(
            f"metadata sync concurrency must be between 1 and {MAX_CONCURRENCY}",
            field="concurrency",
        )
    destination = (Path(database) if database is not None else default_catalog_path()).expanduser().resolve()
    if destination.exists() and destination.is_dir():
        raise InputValidationError(
            "metadata sync database path points to a directory", field="database"
        )

    apps = _load_apps(client)
    synced_at = _utc_now()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = _temporary_database(destination)
    failures: list[dict[str, Any]] = []
    operation_counts = {operation_id: 0 for operation_id in ANALYSIS_METADATA_OPERATIONS}
    lineage_counts = {operation_id: 0 for operation_id in TABLE_LINEAGE_OPERATIONS}
    rows_written = 0
    vocabulary_result = vocabulary.empty_vocabulary_result()
    try:
        with closing(sqlite3.connect(temporary)) as connection:
            _create_schema(connection)
            _write_apps(connection, apps, synced_at)
            operation_counts, failures, rows_written = _sync_operations(
                connection, client, apps, concurrency, synced_at
            )
            vocabulary_result = vocabulary.sync_vocabulary_snapshot(
                connection, client, concurrency, synced_at, failures
            )
            if include_table_lineage:
                lineage_counts = sync_table_lineage(
                    connection, client, concurrency, synced_at
                )
            status = "partial" if failures else "success"
            _write_catalog_metadata(
                connection,
                synced_at=synced_at,
                status=status,
                app_count=len(apps),
                rows_written=rows_written,
                failure_count=len(failures),
                lineage_counts=lineage_counts if include_table_lineage else None,
                vocabulary_result=vocabulary_result,
            )
            connection.commit()
        os.replace(temporary, destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise

    result = {
        "schema_version": SCHEMA_VERSION,
        "ok": not failures,
        "status": "partial" if failures else "success",
        "scope": "all_apps",
        "database": str(destination),
        "synced_at": synced_at,
        "app_count": len(apps),
        "operation_count": len(apps) * len(ANALYSIS_METADATA_OPERATIONS),
        "rows_written": rows_written,
        "operation_rows": operation_counts,
        **vocabulary.vocabulary_summary(vocabulary_result),
        "failure_count": len(failures),
        "failures": failures[:20],
        "failures_truncated": len(failures) > 20,
        "exit_code": _failure_exit_code(failures),
    }
    if include_table_lineage:
        result.update(
            table_lineage_included=True,
            table_lineage_rows=lineage_counts,
        )
    return result


def _load_apps(client: MetadataSyncClient) -> list[tuple[str, Mapping[str, Any]]]:
    envelope = client.read_all(APP_OPERATION_ID, {})
    status = str(envelope.get("status", "error"))
    if status in {"contract_changed", "upstream_changed"}:
        raise ContractChangedError(
            "Gravity app metadata changed; the local catalog was not replaced"
        )
    if status not in {"success", "empty"}:
        raise UpstreamError(
            "Gravity app metadata is unavailable; the local catalog was not replaced"
        )
    return _validated_apps(_rows(envelope))


def _sync_operations(
    connection: sqlite3.Connection,
    client: MetadataSyncClient,
    apps: Sequence[tuple[str, Mapping[str, Any]]],
    concurrency: int,
    synced_at: str,
) -> tuple[dict[str, int], list[dict[str, Any]], int]:
    counts = {operation_id: 0 for operation_id in ANALYSIS_METADATA_OPERATIONS}
    failures: list[dict[str, Any]] = []
    tasks = [
        (operation_id, app_id)
        for operation_id in ANALYSIS_METADATA_OPERATIONS
        for app_id, _ in apps
    ]
    batch_size = min(concurrency, MAX_REQUESTS_PER_BATCH)
    for task_chunk in _chunks(tasks, batch_size):
        results = _sync_batch(client, task_chunk, concurrency)
        for index, (operation_id, app_id) in enumerate(task_chunk):
            result = results[index] if index < len(results) else None
            failure = _failure(app_id, operation_id, result)
            if failure is not None:
                failures.append(failure)
                _write_failure(connection, failure, synced_at)
                continue
            assert result is not None
            envelope = result.get("data")
            rows = _rows(envelope if isinstance(envelope, Mapping) else {})
            _write_rows(connection, app_id, operation_id, rows, synced_at)
            counts[operation_id] += len(rows)
    return counts, failures, sum(counts.values())


def _sync_batch(
    client: MetadataSyncClient,
    tasks: Sequence[tuple[str, str]],
    concurrency: int,
) -> list[Mapping[str, Any]]:
    requests = [
        {
            "operation_id": operation_id,
            "request_id": app_id,
            "inputs": _metadata_inputs(operation_id, app_id),
            "read_all": True,
        }
        for operation_id, app_id in tasks
    ]
    return [
        result if isinstance(result, Mapping) else {}
        for result in call_batch(client, requests, concurrency=concurrency)
    ]


def _validated_apps(rows: Sequence[Mapping[str, Any]]) -> list[tuple[str, Mapping[str, Any]]]:
    result: list[tuple[str, Mapping[str, Any]]] = []
    seen: set[str] = set()
    for row in rows:
        value = row.get("id", row.get("app_id"))
        if not isinstance(value, (str, int)) or isinstance(value, bool) or not str(value):
            raise ContractChangedError(
                "Gravity app metadata omitted an application id; the local catalog was not replaced"
            )
        app_id = str(value)
        if app_id not in seen:
            seen.add(app_id)
            result.append((app_id, row))
    return result


def _metadata_inputs(operation_id: str, app_id: str) -> dict[str, Any]:
    inputs: dict[str, Any] = {"app_id": app_id}
    if operation_id in ANALYSIS_PAGINATED_OPERATIONS:
        inputs.update(page=1, page_size=2_000)
    return inputs


def _failure(
    app_id: str,
    operation_id: str,
    result: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    if result is None:
        return {
            "app_id": app_id,
            "operation_id": operation_id,
            "status": "error",
            "category": "local",
            "code": "BATCH_RESULT_MISSING",
        }
    status = str(result.get("status", "error"))
    if bool(result.get("ok")) and status in {
        "success",
        "empty",
        "contract_changed_additive",
    }:
        return None
    error = result.get("error")
    detail = error if isinstance(error, Mapping) else {}
    return {
        "app_id": app_id,
        "operation_id": operation_id,
        "status": status,
        "category": str(detail.get("category", "upstream")),
        "code": str(detail.get("code", "UPSTREAM_UNAVAILABLE")),
    }


def _rows(envelope: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    data: Any = envelope.get("data")
    if isinstance(data, list):
        values = data
    elif isinstance(data, Mapping):
        values = data.get("list", data.get("items", []))
        if not isinstance(values, list):
            values = []
    else:
        values = []
    return [item for item in values if isinstance(item, Mapping)]


def _temporary_database(destination: Path) -> Path:
    handle = tempfile.NamedTemporaryFile(
        mode="wb",
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=destination.parent,
        delete=False,
    )
    handle.close()
    return Path(handle.name)


def _create_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        PRAGMA foreign_keys = ON;
        CREATE TABLE catalog_metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE apps (
            app_id TEXT PRIMARY KEY,
            payload_json TEXT NOT NULL,
            synced_at TEXT NOT NULL
        );
        CREATE TABLE metadata_rows (
            app_id TEXT NOT NULL,
            operation_id TEXT NOT NULL,
            row_index INTEGER NOT NULL,
            name TEXT,
            cname TEXT,
            payload_json TEXT NOT NULL,
            synced_at TEXT NOT NULL,
            PRIMARY KEY (app_id, operation_id, row_index),
            FOREIGN KEY (app_id) REFERENCES apps(app_id)
        );
        CREATE INDEX metadata_rows_name_idx
            ON metadata_rows(operation_id, name);
        CREATE TABLE sync_failures (
            app_id TEXT NOT NULL,
            operation_id TEXT NOT NULL,
            status TEXT NOT NULL,
            category TEXT NOT NULL,
            code TEXT NOT NULL,
            synced_at TEXT NOT NULL,
            PRIMARY KEY (app_id, operation_id),
            FOREIGN KEY (app_id) REFERENCES apps(app_id)
        );
        """
    )
    create_table_lineage_schema(connection)
    vocabulary.create_vocabulary_schema(connection)
    connection.execute(f"PRAGMA user_version = {DATABASE_SCHEMA_VERSION}")


def _write_apps(
    connection: sqlite3.Connection,
    apps: Sequence[tuple[str, Mapping[str, Any]]],
    synced_at: str,
) -> None:
    connection.executemany(
        "INSERT INTO apps(app_id, payload_json, synced_at) VALUES (?, ?, ?)",
        [
            (app_id, _json(row), synced_at)
            for app_id, row in apps
        ],
    )


def _write_rows(
    connection: sqlite3.Connection,
    app_id: str,
    operation_id: str,
    rows: Sequence[Mapping[str, Any]],
    synced_at: str,
) -> None:
    connection.executemany(
        """
        INSERT INTO metadata_rows(
            app_id, operation_id, row_index, name, cname, payload_json, synced_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                app_id,
                operation_id,
                index,
                _optional_text(row.get("name")),
                _optional_text(row.get("cname")),
                _json(row),
                synced_at,
            )
            for index, row in enumerate(rows)
        ],
    )


def _write_failure(
    connection: sqlite3.Connection,
    failure: Mapping[str, Any],
    synced_at: str,
) -> None:
    connection.execute(
        """
        INSERT INTO sync_failures(
            app_id, operation_id, status, category, code, synced_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            failure["app_id"],
            failure["operation_id"],
            failure["status"],
            failure["category"],
            failure["code"],
            synced_at,
        ),
    )


def _write_catalog_metadata(
    connection: sqlite3.Connection,
    *,
    synced_at: str,
    status: str,
    app_count: int,
    rows_written: int,
    failure_count: int,
    lineage_counts: Mapping[str, int] | None = None,
    vocabulary_result: vocabulary.VocabularySyncResult | None = None,
) -> None:
    values = {
        "schema_version": str(DATABASE_SCHEMA_VERSION),
        "synced_at": synced_at,
        "status": status,
        "app_count": str(app_count),
        "rows_written": str(rows_written),
        "failure_count": str(failure_count),
    }
    if lineage_counts is not None:
        values.update(lineage_catalog_values(lineage_counts))
    if vocabulary_result is not None:
        values.update(vocabulary.vocabulary_catalog_values(vocabulary_result))
    connection.executemany(
        "INSERT INTO catalog_metadata(key, value) VALUES (?, ?)", values.items()
    )


def _failure_exit_code(failures: Sequence[Mapping[str, Any]]) -> int:
    priorities = {"caller": 2, "upstream": 3, "local": 4}
    return max(
        (priorities.get(str(item.get("category")), 3) for item in failures),
        default=0,
    )


def _chunks(values: Sequence[Any], size: int) -> list[Sequence[Any]]:
    return [values[index : index + size] for index in range(0, len(values), size)]


def _optional_text(value: Any) -> str | None:
    return str(value) if isinstance(value, (str, int)) and not isinstance(value, bool) else None


def _json(value: Mapping[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
