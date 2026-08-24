"""Compatibility facade for Gravity's governed custom-SQL reader."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from collections.abc import Sequence as SequenceABC
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

try:
    from gravity_sdk.actionable_error_values import actual_value
    from gravity_sdk.errors import (
        CredentialError,
        GravityInsightError,
        SqlResponseError,
        SqlValidationError,
        TransportError,
    )
    from gravity_sdk.http_runtime import MAX_SQL_CONCURRENCY, SQL_PROFILE
    from gravity_sdk.shared_runtime import get_shared_runtime
    from gravity_sdk.sql.failures import (
        annotate_sql_failure,
        classify_sql_failure,
        sql_protocol_status,
    )
except ModuleNotFoundError:  # pragma: no cover - source-tree execution without installation.
    from gravity_sdk.actionable_error_values import actual_value
    from gravity_sdk.errors import (
        CredentialError,
        GravityInsightError,
        SqlResponseError,
        SqlValidationError,
        TransportError,
    )
    from gravity_sdk.http_runtime import MAX_SQL_CONCURRENCY, SQL_PROFILE
    from gravity_sdk.shared_runtime import get_shared_runtime
    from gravity_sdk.sql.failures import (
        annotate_sql_failure,
        classify_sql_failure,
        sql_protocol_status,
    )


DEFAULT_ENDPOINT = "https://api-insight.gravity-engine.com/custom_sql/api/sql/execute"
DEFAULT_ORIGIN = "https://bi.gravity-engine.com"
_SQL_PATH = "/custom_sql/api/sql/execute"
_SQL_TIMEOUT_SECONDS = 300.0
_AUTH_CODES = frozenset({2001, 10000, 10001})

# Compatibility name retained for callers that already classify authentication
# failures.  CredentialProvider now owns token loading and refresh.
GravityAuthError = CredentialError


@dataclass(frozen=True)
class SqlBatchRequest:
    """One SQL batch item; request_id is returned without interpreting it."""

    sql: str
    request_id: str | None = None


@dataclass(frozen=True)
class SqlBatchResult:
    """Isolated result for one SQL batch item."""

    ok: bool
    status: str
    rows: list[dict[str, Any]] | None
    error: str | None
    request_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "ok": self.ok,
            "status": self.status,
            "rows": self.rows,
            "error": self.error,
        }


class GravityClient:
    """SQL-compatible facade over the process-shared Gravity HTTP runtime.

    The constructor deliberately accepts no URL, method, headers, origin, or
    token.  Production requests can only reach the fixed custom-SQL route owned
    by ``SQL_PROFILE``.
    """

    def __init__(self, runtime: Any | None = None) -> None:
        self._runtime = runtime if runtime is not None else get_shared_runtime()

    @classmethod
    def from_env(cls, env_path: Any | None = None) -> "GravityClient":
        return cls(get_shared_runtime(env_path=env_path))

    def execute_sql(self, sql: str) -> list[dict[str, Any]]:
        normalized = _validate_sql(sql)
        try:
            response = self._runtime.request(
                SQL_PROFILE,
                "POST",
                _SQL_PATH,
                json_body={"sql": normalized, "tabId": "1"},
                semantic_auth_codes=_AUTH_CODES,
                timeout=_SQL_TIMEOUT_SECONDS,
            )
        except GravityInsightError:
            raise
        except Exception:  # Keep dependency/session details out of errors and tracebacks.
            raise annotate_sql_failure(
                TransportError("Gravity SQL request failed"), kind="transport"
            ) from None

        status_code = getattr(response, "status_code", 200)
        if isinstance(status_code, bool) or not isinstance(status_code, int):
            raise annotate_sql_failure(
                TransportError("Gravity SQL returned an invalid HTTP status"),
                kind="invalid_http_status",
            )
        if 300 <= status_code < 400:
            raise annotate_sql_failure(
                TransportError("Gravity SQL returned a blocked redirect"),
                kind="blocked_redirect",
            )
        payload = getattr(response, "payload", None)
        if status_code >= 400:
            raise annotate_sql_failure(
                TransportError(f"Gravity SQL request failed with HTTP {status_code}"),
                kind="http_status",
                http_status=status_code,
                protocol_status=sql_protocol_status(
                    payload,
                    http_status=status_code,
                    status=_find_status(payload),
                    classification="http_error",
                ),
            )

        status = _find_status(payload)
        if status and status.lower() != "success":
            raise annotate_sql_failure(
                SqlResponseError("Gravity SQL returned a non-success status"),
                kind="engine_rejected",
                protocol_status=sql_protocol_status(
                    payload,
                    http_status=status_code,
                    status=status,
                    classification="engine_rejected",
                ),
            )
        rows = _extract_rows(payload)
        if rows is None:
            raise annotate_sql_failure(
                SqlResponseError("Gravity SQL response did not contain tabular rows"),
                kind="non_tabular",
                protocol_status=sql_protocol_status(
                    payload,
                    http_status=status_code,
                    status=status,
                    classification="invalid_response_shape",
                ),
            )
        return rows

    def execute_batch(
        self,
        requests: Sequence[str | SqlBatchRequest | Mapping[str, Any]],
        *,
        max_workers: int = MAX_SQL_CONCURRENCY,
    ) -> list[dict[str, Any]]:
        """Execute independent SQL reads concurrently, preserving input order."""

        if isinstance(max_workers, bool) or not 1 <= max_workers <= MAX_SQL_CONCURRENCY:
            raise SqlValidationError(
                f"actual value: {actual_value(max_workers)}; SQL batch max_workers "
                f"must be between 1 and {MAX_SQL_CONCURRENCY}",
                field="max_workers",
            )
        if not isinstance(requests, SequenceABC) or isinstance(
            requests, (str, bytes, bytearray)
        ):
            raise SqlValidationError(
                f"actual value: {actual_value(type(requests).__name__)}; SQL batch "
                "requests must be a sequence",
                field="requests",
            )
        pending = list(requests)
        if not pending:
            return []

        def run(value: str | SqlBatchRequest | Mapping[str, Any]) -> SqlBatchResult:
            request_id: str | None = None
            try:
                request_id = _batch_request_id(value)
                item = _batch_request(value)
                return SqlBatchResult(
                    True,
                    "success",
                    self.execute_sql(item.sql),
                    None,
                    item.request_id,
                )
            except GravityInsightError as exc:
                return SqlBatchResult(
                    False,
                    "error",
                    None,
                    _safe_batch_error(exc),
                    request_id,
                )
            except Exception:
                return SqlBatchResult(
                    False,
                    "error",
                    None,
                    "Gravity SQL request failed",
                    request_id,
                )

        workers = min(max_workers, len(pending))
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="gravity-sql") as pool:
            return [result.to_dict() for result in pool.map(run, pending)]


_CLIENT: GravityClient | None = None
_CLIENT_LOCK = threading.Lock()


def build_sql_client() -> GravityClient:
    """Return one long-lived SQL facade per process."""

    global _CLIENT
    if _CLIENT is None:
        with _CLIENT_LOCK:
            if _CLIENT is None:
                _CLIENT = GravityClient.from_env()
    return _CLIENT


def _validate_sql(sql: Any) -> str:
    if not isinstance(sql, str) or not sql.strip():
        raise SqlValidationError(
            f"actual value: {actual_value(sql)}; Gravity SQL must be a non-empty string",
            field="sql",
        )
    return sql


def _batch_request(value: str | SqlBatchRequest | Mapping[str, Any]) -> SqlBatchRequest:
    if isinstance(value, SqlBatchRequest):
        _validate_sql(value.sql)
        if value.request_id is not None and not isinstance(value.request_id, str):
            raise SqlValidationError(
                f"actual value: {actual_value(value.request_id)}; SQL batch request_id "
                "must be a string",
                field="request_id",
            )
        return value
    if isinstance(value, str):
        return SqlBatchRequest(_validate_sql(value))
    if not isinstance(value, Mapping):
        raise SqlValidationError(
            f"actual value: {actual_value(type(value).__name__)}; SQL batch items must "
            "be strings or objects",
            field="requests",
        )
    unknown = set(value) - {"sql", "request_id"}
    if unknown:
        raise SqlValidationError(
            f"actual value: {actual_value(sorted(unknown))}; SQL batch item must use "
            "only sql and request_id; remove the extra fields",
            field="requests",
        )
    request_id = value.get("request_id")
    if request_id is not None and not isinstance(request_id, str):
        raise SqlValidationError(
            f"actual value: {actual_value(request_id)}; SQL batch request_id must be a "
            "string",
            field="request_id",
        )
    return SqlBatchRequest(_validate_sql(value.get("sql")), request_id)


def _batch_request_id(value: Any) -> str | None:
    if isinstance(value, SqlBatchRequest):
        return value.request_id if isinstance(value.request_id, str) else None
    if isinstance(value, Mapping):
        request_id = value.get("request_id")
        return request_id if isinstance(request_id, str) else None
    return None


def _safe_batch_error(error: GravityInsightError) -> str:
    return classify_sql_failure(error).message


def _find_status(payload: Any) -> str | None:
    if isinstance(payload, Mapping):
        if isinstance(payload.get("status"), str):
            return payload["status"]
        for key in ("data", "result"):
            nested = _find_status(payload.get(key))
            if nested:
                return nested
    return None


def _extract_rows(payload: Any) -> list[dict[str, Any]] | None:
    if isinstance(payload, list):
        return payload if all(isinstance(row, dict) for row in payload) else None
    if not isinstance(payload, Mapping):
        return None

    result = payload.get("result")
    if isinstance(result, Mapping):
        columns = result.get("columns")
        rows = result.get("rows")
        if isinstance(columns, list) and isinstance(rows, list):
            names = [
                column.get("name") if isinstance(column, Mapping) else str(column)
                for column in columns
            ]
            if not all(isinstance(name, str) and name for name in names):
                return None
            return [
                {names[index]: item for index, item in enumerate(row) if index < len(names)}
                for row in rows
                if isinstance(row, list)
            ]

    for key in ("data", "rows", "result"):
        value = payload.get(key)
        if isinstance(value, list) and all(isinstance(row, dict) for row in value):
            return value
        if isinstance(value, Mapping):
            nested = _extract_rows(value)
            if nested is not None:
                return nested
    return None
