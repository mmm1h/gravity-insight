"""Concurrent machine-oriented execution for registered SQL products."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from gravity_sdk.errors import AuthenticationError, CredentialError
from gravity_sdk.http_runtime import MAX_SQL_CONCURRENCY
from gravity_sdk.sql.products import (
    EvidenceFormatError,
    normalize_app_ids,
    normalize_window,
    run_product,
)
from gravity_sdk.workspace import Workspace, load_workspace


QUERY_SCHEMA_VERSION = "gravity-sql.query.v1"
_QUERY_FIELDS = frozenset(
    {"product", "start", "end", "app_id", "app_ids", "request_id"}
)


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

    _validate_concurrency(max_workers)
    selected_workspace = load_workspace() if workspace is None else workspace
    pending = _request_sequence(requests)
    results = _execute(client, pending, max_workers, selected_workspace)
    return _envelope(results)


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


def _envelope(results: list[dict[str, Any]]) -> dict[str, Any]:
    succeeded = sum(item["ok"] is True for item in results)
    failed = len(results) - succeeded
    categories = {
        str(item["error"]["category"])
        for item in results
        if item["ok"] is False
    }
    return {
        "schema_version": QUERY_SCHEMA_VERSION,
        "ok": failed == 0,
        "status": "success" if failed == 0 else ("partial" if succeeded else "error"),
        "requested_count": len(results),
        "succeeded_count": succeeded,
        "failed_count": failed,
        "exit_code": _exit_code(categories),
        "results": results,
    }


def _exit_code(categories: set[str]) -> int:
    if "contract" in categories:
        return 4
    if "runtime" in categories:
        return 3
    return 2 if categories else 0


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
    product = normalized["product"]
    try:
        result = run_product(
            client,
            product,
            normalized["start_at"],
            normalized["end_at"],
            normalized["app_ids"],
            workspace=workspace,
        )
    except AuthenticationError:
        return _error(
            request_id,
            product,
            "authentication",
            "Gravity SQL authentication failed",
            code="SQL_PRODUCT_AUTH_FAILED",
        )
    except CredentialError:
        return _error(
            request_id,
            product,
            "authentication",
            "Gravity SQL credentials are unavailable",
            code="SQL_PRODUCT_CREDENTIALS_UNAVAILABLE",
        )
    except EvidenceFormatError:
        return _error(
            request_id,
            product,
            "contract",
            "SQL product result violated its aggregate contract",
            code="SQL_PRODUCT_CONTRACT_VIOLATION",
        )
    except Exception:
        return _error(
            request_id,
            product,
            "runtime",
            "Gravity SQL product query failed",
            code="SQL_PRODUCT_RUNTIME_FAILED",
        )
    return {"request_id": request_id, "ok": True, **result}


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
) -> dict[str, Any]:
    exit_code = 3 if category == "runtime" else 4 if category == "contract" else 2
    return {
        "request_id": request_id,
        "product": product,
        "ok": False,
        "status": "error",
        "exit_code": exit_code,
        "error": {
            "category": category,
            "code": code,
            "field": field,
            "message": message,
            "next_action": (
                "Run `gravity auth status`; refresh or configure credentials, then retry."
                if category == "authentication"
                else
                "Run `gravity sql products`, correct this request, and retry."
                if exit_code == 2
                else "Inspect the governed product contract and retry."
                if exit_code == 4
                else "Retry after checking Gravity authentication and availability."
            ),
        },
    }


def _validate_concurrency(value: int) -> None:
    if type(value) is not int or not 1 <= value <= MAX_SQL_CONCURRENCY:
        raise ValueError(
            f"SQL product concurrency must be between 1 and {MAX_SQL_CONCURRENCY}"
        )
