"""Workspace-scoped Analysis vocabulary persisted in the metadata catalog.

The online Analysis context already exposes these stable sources.  The local
catalog reads every source once per synchronization, stores only the governed
response projection, and lets callers discover metrics and templates without
repeating online context calls.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

from .analysis_context import ANALYSIS_CONTEXT_SOURCES, AnalysisContextSource
from .errors import InputValidationError
from .runtime import call_batch


VOCABULARY_SOURCES = tuple(ANALYSIS_CONTEXT_SOURCES[4:])
VOCABULARY_KINDS = (
    "metric",
    "custom_metric",
    "metric_tag",
    "metric_tag_category",
    "media_enum",
    "template",
)
VOCABULARY_SEARCH_KINDS = (*VOCABULARY_KINDS, "vocabulary")
VOCABULARY_SYNC_ACTION = (
    "Run `gravity metadata sync --all-apps`, then retry the same offline "
    "analysis vocabulary search."
)
MAX_VOCABULARY_BATCH_SIZE = 8
_SUCCESS_STATUSES = {"success", "empty", "contract_changed_additive"}
_SOURCE_KINDS = {
    "report_metrics": "metric",
    "custom_metrics": "custom_metric",
    "shared_custom_metrics": "custom_metric",
    "metric_tags": "metric_tag",
    "metric_tag_categories": "metric_tag_category",
    "media_enums": "media_enum",
    "mine_templates": "template",
    "shared_templates": "template",
    "preset_templates": "template",
}


class VocabularySyncClient(Protocol):
    def batch(
        self,
        requests: Sequence[Mapping[str, Any]],
        **kwargs: Any,
    ) -> Sequence[Mapping[str, Any]]: ...


@dataclass(frozen=True)
class VocabularySyncResult:
    counts: Mapping[str, int]
    failures: tuple[Mapping[str, Any], ...]

    @property
    def rows_written(self) -> int:
        return sum(self.counts.values())


def empty_vocabulary_result() -> VocabularySyncResult:
    return VocabularySyncResult({source.source: 0 for source in VOCABULARY_SOURCES}, ())


def vocabulary_summary(result: VocabularySyncResult) -> dict[str, Any]:
    return {
        "vocabulary_operation_count": len(VOCABULARY_SOURCES),
        "vocabulary_rows_written": result.rows_written,
        "vocabulary_rows": dict(result.counts),
        "vocabulary_failure_count": len(result.failures),
    }


def add_vocabulary_command(
    metadata_commands: Any,
    metadata_limit: Any,
    nonnegative_int: Any,
) -> None:
    vocabulary = metadata_commands.add_parser(
        "vocabulary",
        help="Search synchronized workspace Analysis metrics and templates offline.",
    )
    vocabulary.set_defaults(network_required=False)
    vocabulary.add_argument("query", nargs="?", default="")
    vocabulary.add_argument(
        "--kind", choices=VOCABULARY_SEARCH_KINDS, default="vocabulary"
    )
    vocabulary.add_argument("--database", type=Path, default=None)
    vocabulary.add_argument("--limit", type=metadata_limit, default=20)
    vocabulary.add_argument("--offset", type=nonnegative_int, default=0)


def run_vocabulary_search(args: Any) -> dict[str, Any]:
    from .find_metadata import search_metadata

    result = search_metadata(
        args.query,
        database=args.database,
        kind=args.kind,
        limit=args.limit,
        offset=args.offset,
    )
    result.pop("database", None)
    return result


def create_vocabulary_schema(connection: sqlite3.Connection) -> None:
    """Create tables kept independent from App-scoped metadata rows."""

    connection.executescript(
        """
        CREATE TABLE analysis_vocabulary_rows (
            source TEXT NOT NULL,
            operation_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            row_index INTEGER NOT NULL,
            name TEXT,
            cname TEXT,
            payload_json TEXT NOT NULL,
            synced_at TEXT NOT NULL,
            PRIMARY KEY (source, row_index)
        );
        CREATE INDEX analysis_vocabulary_kind_name_idx
            ON analysis_vocabulary_rows(kind, name, cname);
        CREATE TABLE analysis_vocabulary_failures (
            source TEXT PRIMARY KEY,
            operation_id TEXT NOT NULL,
            status TEXT NOT NULL,
            category TEXT NOT NULL,
            code TEXT NOT NULL,
            synced_at TEXT NOT NULL
        );
        """
    )


def sync_analysis_vocabulary(
    connection: sqlite3.Connection,
    client: VocabularySyncClient,
    concurrency: int,
    synced_at: str,
) -> VocabularySyncResult:
    """Read each stable workspace source once and retain successful siblings."""

    requests = [_request(source) for source in VOCABULARY_SOURCES]
    indexed: dict[str, Mapping[str, Any]] = {}
    for chunk in _chunks(requests, MAX_VOCABULARY_BATCH_SIZE):
        batch = call_batch(
            client,
            chunk,
            concurrency=min(concurrency, MAX_VOCABULARY_BATCH_SIZE, len(chunk)),
        )
        if not isinstance(batch, Sequence) or isinstance(batch, (str, bytes)):
            raise InputValidationError(
                "Analysis vocabulary batch returned an invalid result collection",
                field="result",
            )
        chunk_sources = {
            str(request["request_id"]): str(request["operation_id"])
            for request in chunk
        }
        indexed.update(_index_results(batch, chunk_sources))
    counts = {source.source: 0 for source in VOCABULARY_SOURCES}
    failures: list[Mapping[str, Any]] = []
    for source in VOCABULARY_SOURCES:
        result = indexed.get(source.source) or indexed.get(source.operation_id)
        failure = _failure(source, result)
        if failure is not None:
            failures.append(failure)
            _write_failure(connection, failure, synced_at)
            continue
        assert result is not None
        rows = _projected_rows(source, result)
        _write_rows(connection, source, rows, synced_at)
        counts[source.source] = len(rows)
    return VocabularySyncResult(counts, tuple(failures))


def sync_vocabulary_snapshot(
    connection: sqlite3.Connection,
    client: VocabularySyncClient,
    concurrency: int,
    synced_at: str,
    failures: list[Mapping[str, Any]],
) -> VocabularySyncResult:
    result = sync_analysis_vocabulary(connection, client, concurrency, synced_at)
    failures += list(result.failures)
    return result


def vocabulary_catalog_values(result: VocabularySyncResult) -> dict[str, str]:
    """Return compact markers used to distinguish new and legacy catalogs."""

    return {
        "analysis_vocabulary_observed": "true",
        "analysis_vocabulary_status": "partial" if result.failures else "success",
        "analysis_vocabulary_rows": str(result.rows_written),
        "analysis_vocabulary_failure_count": str(len(result.failures)),
    }


def require_vocabulary_snapshot(connection: sqlite3.Connection) -> None:
    """Fail with one precise recovery command for legacy catalogs."""

    tables = {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    marker = connection.execute(
        "SELECT value FROM catalog_metadata "
        "WHERE key = 'analysis_vocabulary_observed'"
    ).fetchone()
    if (
        not {"analysis_vocabulary_rows", "analysis_vocabulary_failures"} <= tables
        or marker is None
        or str(marker[0]).casefold() != "true"
    ):
        raise InputValidationError(
            "metadata catalog has no synchronized Analysis vocabulary; run "
            "`gravity metadata sync --all-apps`",
            field="database",
            next_action=VOCABULARY_SYNC_ACTION,
        )


def vocabulary_rows(
    connection: sqlite3.Connection,
    query: str,
    kind: str,
) -> list[sqlite3.Row]:
    """Select safe projected rows for formatting by the shared search surface."""

    require_vocabulary_snapshot(connection)
    normalized_kind = validate_vocabulary_kind(kind)
    clauses: list[str] = []
    parameters: list[Any] = []
    if normalized_kind != "vocabulary":
        clauses.append("kind = ?")
        parameters.append(normalized_kind)
    if query.strip():
        pattern = f"%{_escape_like(query.strip())}%"
        clauses.append(
            "(name LIKE ? ESCAPE '\\' OR cname LIKE ? ESCAPE '\\' "
            "OR source LIKE ? ESCAPE '\\' OR payload_json LIKE ? ESCAPE '\\')"
        )
        parameters.extend((pattern, pattern, pattern, pattern))
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    return connection.execute(
        "SELECT source, operation_id, kind, name, cname, payload_json "
        "FROM analysis_vocabulary_rows" + where,
        parameters,
    ).fetchall()


def vocabulary_failures(connection: sqlite3.Connection) -> list[dict[str, str]]:
    """Return bounded, credential-free failure facts for catalog diagnostics."""

    require_vocabulary_snapshot(connection)
    return [
        {
            "source": str(row[0]),
            "operation_id": str(row[1]),
            "status": str(row[2]),
            "category": str(row[3]),
            "code": str(row[4]),
        }
        for row in connection.execute(
            "SELECT source, operation_id, status, category, code "
            "FROM analysis_vocabulary_failures ORDER BY source"
        )
    ]


def validate_vocabulary_kind(kind: str) -> str:
    if kind not in VOCABULARY_SEARCH_KINDS:
        raise InputValidationError("unknown metadata search kind", field="kind")
    return kind


def vocabulary_kind(source: str) -> str:
    try:
        return _SOURCE_KINDS[source]
    except KeyError as error:
        raise InputValidationError(
            "unknown Analysis vocabulary source", field="source"
        ) from error


def _request(source: AnalysisContextSource) -> dict[str, Any]:
    return {
        "operation_id": source.operation_id,
        "request_id": source.source,
        "inputs": {},
        "read_all": source.paginated,
    }


def _index_results(
    results: Sequence[Any],
    expected: Mapping[str, str],
) -> dict[str, Mapping[str, Any]]:
    operation_sources = {operation_id: source for source, operation_id in expected.items()}
    indexed: dict[str, Mapping[str, Any]] = {}
    for result in results:
        if not isinstance(result, Mapping):
            raise InputValidationError(
                "Analysis vocabulary batch returned a non-object result",
                field="result",
            )
        request_id = result.get("request_id")
        operation_id = result.get("operation_id")
        if isinstance(request_id, str) and request_id:
            source = request_id
        elif isinstance(operation_id, str) and operation_id:
            source = operation_sources.get(operation_id, "")
        else:
            source = ""
        if source not in expected:
            raise InputValidationError(
                "Analysis vocabulary batch returned an unknown result identity",
                field="request_id",
            )
        if source in indexed:
            raise InputValidationError(
                "Analysis vocabulary batch returned a duplicate result identity",
                field="request_id",
            )
        if isinstance(operation_id, str) and operation_id:
            expected_operation = expected[source]
            if operation_id != expected_operation:
                raise InputValidationError(
                    "Analysis vocabulary batch result operation_id did not match its source",
                    field="operation_id",
                )
        indexed[source] = result
    return indexed


def _failure(
    source: AnalysisContextSource,
    result: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    if result is None:
        return {
            "source": source.source,
            "operation_id": source.operation_id,
            "status": "error",
            "category": "local",
            "code": "BATCH_RESULT_MISSING",
        }
    status = str(result.get("status", "error"))
    if bool(result.get("ok")) and status in _SUCCESS_STATUSES:
        if status == "empty" or _valid_projected_data(source, result):
            return None
        return {
            "source": source.source,
            "operation_id": source.operation_id,
            "status": "contract_changed",
            "category": "upstream",
            "code": "CONTRACT_CHANGED",
        }
    detail = result.get("error")
    error = detail if isinstance(detail, Mapping) else {}
    code = str(
        error.get(
            "code",
            "CONTRACT_CHANGED"
            if status in {"contract_changed", "upstream_changed"}
            else "UPSTREAM_UNAVAILABLE",
        )
    )
    return {
        "source": source.source,
        "operation_id": source.operation_id,
        "status": status,
        "category": str(error.get("category", "upstream")),
        "code": code,
    }


def _projected_rows(
    source: AnalysisContextSource,
    result: Mapping[str, Any],
) -> list[Mapping[str, Any]]:
    data = _projected_data(result)
    if source.source == "media_enums":
        return _flatten_media_enums(data)
    if not isinstance(data, Mapping):
        return []
    values = data.get("list", data.get("items", []))
    if not isinstance(values, list):
        return []
    return [dict(item) for item in values if isinstance(item, Mapping)]


def _valid_projected_data(
    source: AnalysisContextSource,
    result: Mapping[str, Any],
) -> bool:
    data = _projected_data(result)
    if not isinstance(data, Mapping):
        return False
    if source.source == "media_enums":
        return _valid_media_enums(data)
    values = data.get("list", data.get("items"))
    return isinstance(values, list)


def _projected_data(result: Mapping[str, Any]) -> Any:
    envelope = result.get("data")
    if not isinstance(envelope, Mapping):
        return None
    return envelope.get("data")


def _flatten_media_enums(data: Any) -> list[Mapping[str, Any]]:
    if not isinstance(data, Mapping):
        return []
    rows: list[Mapping[str, Any]] = []
    for platform in sorted(data):
        groups = data.get(platform)
        if not isinstance(groups, Mapping):
            continue
        for group in sorted(groups):
            items = groups.get(group)
            if not isinstance(items, list):
                continue
            for item in items:
                if isinstance(item, Mapping):
                    rows.append(
                        {**dict(item), "platform": str(platform), "group": str(group)}
                    )
    return rows


def _valid_media_enums(data: Mapping[Any, Any]) -> bool:
    return all(
        isinstance(platform, str)
        and isinstance(groups, Mapping)
        and all(
            isinstance(group, str)
            and isinstance(items, list)
            and all(isinstance(item, Mapping) for item in items)
            for group, items in groups.items()
        )
        for platform, groups in data.items()
    )


def _write_rows(
    connection: sqlite3.Connection,
    source: AnalysisContextSource,
    rows: Sequence[Mapping[str, Any]],
    synced_at: str,
) -> None:
    kind = vocabulary_kind(source.source)
    connection.executemany(
        """
        INSERT INTO analysis_vocabulary_rows(
            source, operation_id, kind, row_index, name, cname, payload_json, synced_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                source.source,
                source.operation_id,
                kind,
                index,
                _row_name(kind, row),
                _row_cname(kind, row),
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
        INSERT INTO analysis_vocabulary_failures(
            source, operation_id, status, category, code, synced_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            failure["source"],
            failure["operation_id"],
            failure["status"],
            failure["category"],
            failure["code"],
            synced_at,
        ),
    )


def _row_name(kind: str, row: Mapping[str, Any]) -> str | None:
    field = "code" if kind == "media_enum" else "name"
    return _optional_text(row.get(field)) or _optional_text(row.get("id"))


def _row_cname(kind: str, row: Mapping[str, Any]) -> str | None:
    field = "name" if kind == "media_enum" else "cname"
    return _optional_text(row.get(field))


def _optional_text(value: Any) -> str | None:
    return (
        str(value)
        if isinstance(value, (str, int)) and not isinstance(value, bool)
        else None
    )


def _json(value: Mapping[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _chunks(values: Sequence[Any], size: int) -> list[Sequence[Any]]:
    return [values[index : index + size] for index in range(0, len(values), size)]


__all__ = [
    "VOCABULARY_KINDS",
    "VOCABULARY_SEARCH_KINDS",
    "VOCABULARY_SOURCES",
    "VOCABULARY_SYNC_ACTION",
    "VocabularySyncResult",
    "add_vocabulary_command",
    "create_vocabulary_schema",
    "empty_vocabulary_result",
    "require_vocabulary_snapshot",
    "sync_analysis_vocabulary",
    "sync_vocabulary_snapshot",
    "validate_vocabulary_kind",
    "vocabulary_catalog_values",
    "vocabulary_failures",
    "vocabulary_kind",
    "vocabulary_rows",
    "vocabulary_summary",
    "run_vocabulary_search",
]
