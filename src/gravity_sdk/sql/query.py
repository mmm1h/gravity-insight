"""Concurrent machine-oriented execution for registered SQL products."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
import time
from typing import Any

from gravity_sdk.errors import (
    ErrorCategory,
    exit_code_for_category,
)
from gravity_sdk.http_runtime import MAX_SQL_CONCURRENCY
from gravity_sdk.receipt import capture_http_receipt_references
from gravity_sdk.result_audit import add_result_audit
from gravity_sdk.result_source import CALLER_DEFINED, result_source
from gravity_sdk.sql.products import (
    EvidenceFormatError,
    normalize_app_ids,
    normalize_window,
    run_product,
)
from gravity_sdk.sql.failures import (
    SqlFailure,
    classify_sql_failure,
    diagnostic_fields,
    execution_evidence,
)
from gravity_sdk.workspace import Workspace, load_workspace


QUERY_SCHEMA_VERSION = "gravity-sql.query.v1"
_QUERY_FIELDS = frozenset(
    {"product", "start", "end", "app_id", "app_ids", "request_id"}
)
_SQL_ERROR_CATEGORIES = {
    "input": ErrorCategory.CALLER,
    "authentication": ErrorCategory.CALLER,
    "runtime": ErrorCategory.UPSTREAM,
    "contract": ErrorCategory.LOCAL,
    "local_io": ErrorCategory.LOCAL,
}


class _RequestError(ValueError):
    def __init__(self, code: str, field: str | None, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.field = field


def run_product_queries(
    client: Any,
    requests: Sequence[Mapping[str, Any]],
    *,
    max_workers: int = MAX_SQL_CONCURRENCY,
    workspace: Workspace | None = None,
) -> dict[str, Any]:
    """Execute registered products concurrently, preserving input order."""

    started = time.monotonic()
    _validate_concurrency(max_workers)
    selected_workspace = load_workspace() if workspace is None else workspace
    pending = _request_sequence(requests)
    results = _execute(client, pending, max_workers, selected_workspace)
    return _envelope(results, elapsed_seconds=time.monotonic() - started)


def _request_sequence(requests: object) -> list[object]:
    if not isinstance(requests, Sequence) or isinstance(
        requests, (str, bytes, bytearray)
    ):
        raise ValueError("SQL product requests must be a sequence")
    pending = list(requests)
    if not pending:
        raise ValueError("SQL product requests must not be empty")
    return pending


def _execute(
    client: Any,
    pending: list[object],
    max_workers: int,
    workspace: Workspace | None,
) -> list[dict[str, Any]]:
    workers = min(max_workers, len(pending))
    if workers == 1:
        return [_run_one(client, item, workspace) for item in pending]
    with ThreadPoolExecutor(
        max_workers=workers, thread_name_prefix="gravity-sql-product"
    ) as pool:
        return list(pool.map(lambda item: _run_one(client, item, workspace), pending))


def _envelope(
    results: list[dict[str, Any]], *, elapsed_seconds: float = 0
) -> dict[str, Any]:
    succeeded = sum(item["ok"] is True for item in results)
    failed = len(results) - succeeded
    categories = {
        str(item["error"]["category"])
        for item in results
        if item["ok"] is False
    }
    request_count = sum(_request_count(item) for item in results)
    return {
        "schema_version": QUERY_SCHEMA_VERSION,
        "result_source": result_source(CALLER_DEFINED),
        "ok": failed == 0,
        "status": "success" if failed == 0 else ("partial" if succeeded else "error"),
        "requested_count": len(results),
        "succeeded_count": succeeded,
        "failed_count": failed,
        "exit_code": _exit_code(categories),
        "execution_evidence": execution_evidence(
            elapsed_seconds=elapsed_seconds,
            request_count=request_count,
            request_count_bound=len(results),
        ),
        "results": results,
    }


def _request_count(result: Mapping[str, Any]) -> int:
    owner = result if result.get("ok") is True else result.get("error")
    evidence = owner.get("execution_evidence") if isinstance(owner, Mapping) else None
    count = evidence.get("request_count") if isinstance(evidence, Mapping) else 0
    return count if type(count) is int and count >= 0 else 0


def _exit_code(categories: set[str]) -> int:
    return max((sql_error_exit_code(category) for category in categories), default=0)


def sql_error_exit_code(category: str) -> int:
    """Map the legacy SQL error vocabulary through the shared exit policy."""

    return exit_code_for_category(
        _SQL_ERROR_CATEGORIES.get(category, ErrorCategory.CALLER)
    )


def _run_one(
    client: Any, value: object, workspace: Workspace | None
) -> dict[str, Any]:
    request_id = _request_id(value)
    try:
        normalized = _normalize(value, workspace)
    except _RequestError as exc:
        return _error(
            request_id,
            None,
            "input",
            str(exc),
            code=exc.code,
            field=exc.field,
        )
    except (EvidenceFormatError, TypeError, ValueError):
        return _error(
            request_id,
            None,
            "input",
            "SQL product request is invalid; use the products command for its input contract",
            code="SQL_PRODUCT_INPUT_INVALID",
        )
    return _execute_one(client, request_id, normalized, workspace)


def _execute_one(
    client: Any,
    request_id: str | None,
    normalized: dict[str, Any],
    workspace: Workspace | None,
) -> dict[str, Any]:
    with capture_http_receipt_references() as references:
        result = _execute_one_captured(client, request_id, normalized, workspace)
    return add_result_audit(result, references)


def _execute_one_captured(
    client: Any,
    request_id: str | None,
    normalized: dict[str, Any],
    workspace: Workspace | None,
) -> dict[str, Any]:
    product = normalized["product"]
    counted = _CountedSqlClient(client)
    started = time.monotonic()
    try:
        result = run_product(
            counted,
            product,
            normalized["start_at"],
            normalized["end_at"],
            normalized["app_ids"],
            workspace=workspace,
        )
    except EvidenceFormatError:
        failure = SqlFailure(
            "product_contract", "shape", "aggregate_shape_drift",
            "SQL_PRODUCT_CONTRACT_VIOLATION",
            "SQL product result violated its aggregate contract", False,
            "yes" if counted.request_count else "no",
            "Inspect the governed product output contract; do not retry unchanged.",
        )
        return _error(
            request_id,
            product,
            "contract",
            failure.message,
            code=failure.code,
            diagnostic=diagnostic_fields(
                failure,
                elapsed_seconds=time.monotonic() - started,
                request_count=counted.request_count,
                request_count_bound=1,
            ),
        )
    except Exception as exc:
        failure = classify_sql_failure(exc, request_count=counted.request_count)
        return _error(
            request_id,
            product,
            _failure_category(failure),
            failure.message,
            code=failure.code,
            diagnostic=diagnostic_fields(
                failure,
                elapsed_seconds=time.monotonic() - started,
                request_count=counted.request_count,
                request_count_bound=1,
            ),
            next_action=failure.next_action,
        )
    return {
        "request_id": request_id,
        "ok": True,
        **result,
        "result_source": result_source(CALLER_DEFINED),
        "execution_evidence": execution_evidence(
            elapsed_seconds=time.monotonic() - started,
            request_count=counted.request_count,
            request_count_bound=1,
        ),
    }


class _CountedSqlClient:
    def __init__(self, client: Any) -> None:
        self.client = client
        self.request_count = 0

    def execute_sql(self, sql: str) -> list[dict[str, Any]]:
        self.request_count += 1
        return self.client.execute_sql(sql)


def _failure_category(failure: SqlFailure) -> str:
    if failure.kind in {"authentication", "credentials"}:
        return "authentication"
    if failure.kind == "local_validation":
        return "input"
    if failure.stage == "compile":
        return "contract"
    return "runtime"


def _normalize(
    value: object, workspace: Workspace | None
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise _RequestError(
            "SQL_PRODUCT_REQUEST_NOT_OBJECT",
            None,
            "SQL product request must be an object",
        )
    _validate_fields(value)
    product = value.get("product")
    if not isinstance(product, str) or not product.strip():
        raise _RequestError(
            "SQL_PRODUCT_REQUIRED",
            "product",
            "SQL product request requires product",
        )
    request_id = value.get("request_id")
    if request_id is not None and not isinstance(request_id, str):
        raise _RequestError(
            "SQL_PRODUCT_REQUEST_ID_INVALID",
            "request_id",
            "SQL product request_id must be a string",
        )
    start = value.get("start")
    end = value.get("end")
    if not isinstance(start, str) or not isinstance(end, str):
        raise _RequestError(
            "SQL_PRODUCT_WINDOW_REQUIRED",
            "start/end",
            "SQL product request requires string start and end timestamps",
        )
    try:
        start_at, end_at = normalize_window(start, end)
    except ValueError as exc:
        raise _RequestError(
            "SQL_PRODUCT_WINDOW_INVALID",
            "start/end",
            "SQL product request has an invalid time window",
        ) from exc
    try:
        apps = normalize_app_ids(product, _app_ids(value), workspace)
    except EvidenceFormatError as exc:
        raise _RequestError(
            "SQL_PRODUCT_UNKNOWN",
            "product",
            "SQL product is not configured in the selected workspace",
        ) from exc
    except ValueError as exc:
        raise _RequestError(
            "SQL_PRODUCT_APP_INVALID",
            "app_ids",
            "SQL product app ids are invalid",
        ) from exc
    return {
        "product": product,
        "start_at": start_at,
        "end_at": end_at,
        "app_ids": apps,
    }


def _validate_fields(value: Mapping[str, Any]) -> None:
    unknown = sorted(set(value) - _QUERY_FIELDS)
    if unknown:
        raise _RequestError(
            "SQL_PRODUCT_FIELD_UNKNOWN",
            unknown[0],
            "SQL product request contains an unknown field",
        )
    if "app_id" in value and "app_ids" in value:
        raise _RequestError(
            "SQL_PRODUCT_APP_CONFLICT",
            "app_ids",
            "app_id and app_ids cannot be combined",
        )


def _app_ids(value: Mapping[str, Any]) -> list[Any] | None:
    raw_apps = value.get("app_ids", value.get("app_id"))
    if raw_apps is None:
        return None
    if type(raw_apps) is int:
        return [raw_apps]
    if isinstance(raw_apps, Sequence) and not isinstance(
        raw_apps, (str, bytes, bytearray)
    ):
        return list(raw_apps)
    raise _RequestError(
        "SQL_PRODUCT_APP_INVALID",
        "app_ids",
        "SQL product app_ids must be a positive integer or array",
    )


def _request_id(value: object) -> str | None:
    if not isinstance(value, Mapping):
        return None
    request_id = value.get("request_id")
    return request_id if isinstance(request_id, str) else None


def _error(
    request_id: str | None,
    product: str | None,
    category: str,
    message: str,
    *,
    code: str,
    field: str | None = None,
    diagnostic: Mapping[str, Any] | None = None,
    next_action: str | None = None,
) -> dict[str, Any]:
    exit_code = sql_error_exit_code(category)
    default_stage = "shape" if category == "contract" else "execute" if category == "runtime" else "bind"
    default_diagnostic = {
        "stage": default_stage,
        "retryable": False,
        "reached_sql_engine": "no",
        "upstream_error": {"category": "not_reached", "code": code},
        "execution_evidence": execution_evidence(
            elapsed_seconds=0, request_count=0, request_count_bound=1
        ),
    }
    return {
        "request_id": request_id,
        "product": product,
        "result_source": result_source(CALLER_DEFINED),
        "ok": False,
        "status": "error",
        "exit_code": exit_code,
        "error": {
            "category": category,
            "code": code,
            "field": field,
            "message": message,
            "next_action": next_action or (
                "Run `gravity auth status`; refresh or configure credentials, then retry."
                if category == "authentication"
                else
                "Run `gravity sql products`, correct this request, and retry."
                if category == "input"
                else "Inspect the governed product contract and retry."
                if category in {"contract", "local_io"}
                else "Retry the same query once; if it fails again, run `gravity doctor --live`."
            ),
            **(dict(diagnostic) if diagnostic is not None else default_diagnostic),
        },
    }


def _validate_concurrency(value: int) -> None:
    if type(value) is not int or not 1 <= value <= MAX_SQL_CONCURRENCY:
        raise ValueError(
            f"SQL product concurrency must be between 1 and {MAX_SQL_CONCURRENCY}"
        )
