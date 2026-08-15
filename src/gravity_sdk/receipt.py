"""Value-free execution receipts and scoped HTTP request accounting."""

from __future__ import annotations

import contextvars
import json
import logging
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping

from .fingerprints import shape_fingerprint
from .result_output import write_rendered_result


SCHEMA_VERSION = "gravity.receipt.v1"
HTTP_SCHEMA_VERSION = "gravity.http-receipt.v1"
_LOGGER = logging.getLogger("gravity_sdk")


@dataclass
class _ActiveHttpReceipt:
    context: Mapping[str, Any]
    state_root: Path
    recorded: bool = False


_ACTIVE_HTTP_RECEIPT: contextvars.ContextVar[_ActiveHttpReceipt | None] = (
    contextvars.ContextVar("gravity_active_http_receipt", default=None)
)


@dataclass
class RequestCounter:
    count: int = 0


_ACTIVE_REQUEST_COUNTER: contextvars.ContextVar[RequestCounter | None] = (
    contextvars.ContextVar("gravity_request_counter", default=None)
)


@contextmanager
def count_http_requests() -> Iterator[RequestCounter]:
    counter = RequestCounter()
    token = _ACTIVE_REQUEST_COUNTER.set(counter)
    try:
        yield counter
    finally:
        _ACTIVE_REQUEST_COUNTER.reset(token)


def record_http_request() -> None:
    counter = _ACTIVE_REQUEST_COUNTER.get()
    if counter is not None:
        counter.count += 1


def perform_http_request(
    request: Callable[..., Any],
    *args: Any,
    http_receipt: Mapping[str, Any] | None = None,
    receipt_root: Path | None = None,
    **kwargs: Any,
) -> Any:
    record_http_request()
    active = (
        _ActiveHttpReceipt(http_receipt, receipt_root)
        if http_receipt is not None and receipt_root is not None
        else None
    )
    token = _ACTIVE_HTTP_RECEIPT.set(active) if active is not None else None
    try:
        response = request(*args, **kwargs)
        record_active_http_response(response)
        return response
    finally:
        if token is not None:
            _ACTIVE_HTTP_RECEIPT.reset(token)


def record_active_http_response(response: Any) -> None:
    """Commit a surrounding request receipt at a raw transport boundary."""

    active = _ACTIVE_HTTP_RECEIPT.get()
    if active is None or active.recorded:
        return
    active.recorded = True
    record_completed_http_response(response, active.context, active.state_root)


def request_receipt_context(
    *,
    operation_id: str,
    method: str,
    path: str,
    query: Mapping[str, Any] | None = None,
    body: Mapping[str, Any] | None = None,
    page_number: int | None = None,
    retry: bool = False,
) -> dict[str, Any]:
    """Build value-free metadata before a controlled request is sent."""

    return {
        "operation_id": operation_id,
        "method": method.upper(),
        "path": path,
        "page_number": page_number,
        "retry": retry,
        "request_shape_fingerprint": shape_fingerprint(
            {"query": dict(query or {}), "body": dict(body or {})}
        ),
    }


def request_attempt_context(
    context: Mapping[str, Any] | None, attempt: int
) -> dict[str, Any]:
    selected = dict(context or {})
    selected["attempt"] = attempt + 1
    selected["retry"] = bool(selected.get("retry")) or attempt > 0
    return selected


def authorized_request_receipt_context(
    authorization: object,
    *,
    method: str,
    path: str,
    query: Mapping[str, Any] | None,
    body: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Derive safe operation and pagination identity from a policy receipt."""

    target = getattr(authorization, "operation", None) or getattr(
        authorization, "route", None
    )
    operation_id = str(getattr(target, "operation_id", "unknown"))
    receipt_path = str(
        getattr(target, "path_template", None) or getattr(target, "path", None) or path
    )
    pagination = getattr(target, "pagination", None)
    page_field = str(getattr(pagination, "page_field", "") or "")
    wire = {**dict(query or {}), **dict(body or {})}
    page_number = _positive_integer(wire.get(page_field)) if page_field else None
    if page_number is None and page_field:
        defaults = getattr(getattr(target, "request", None), "defaults", {})
        if isinstance(defaults, Mapping):
            page_number = _positive_integer(defaults.get(page_field))
    return request_receipt_context(
        operation_id=operation_id,
        method=method,
        path=receipt_path,
        query=query,
        body=body,
        page_number=page_number,
    )


def record_completed_http_response(
    response: Any,
    context: Mapping[str, Any],
    state_root: Path,
) -> None:
    """Durably record a completed response without changing request outcomes."""

    completed_at = datetime.now(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )
    receipt = {
        "schema_version": HTTP_SCHEMA_VERSION,
        "receipt_id": uuid.uuid4().hex,
        "completed_at": completed_at,
        "operation_id": str(context.get("operation_id", "unknown")),
        "method": str(context.get("method", "unknown")).upper(),
        "path": str(context.get("path", "unknown")),
        "http_status": _http_status(response),
        "page_number": _positive_integer(context.get("page_number")),
        "attempt": _positive_integer(context.get("attempt")) or 1,
        "retry": bool(context.get("retry", False)),
        "request_shape_fingerprint": str(
            context.get("request_shape_fingerprint", "")
        ),
    }
    try:
        persist_http_receipt(receipt, state_root)
    except (OSError, UnicodeError):
        _report_http_receipt_failure(receipt)


def persist_http_receipt(receipt: Mapping[str, Any], state_root: Path) -> Path:
    """Publish one completed-request receipt with file and replace durability."""

    receipt_id = str(receipt.get("receipt_id", "unknown"))
    path = state_root / "receipts" / "http" / f"{receipt_id}.json"
    rendered = json.dumps(
        dict(receipt), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ) + "\n"
    write_rendered_result(str(path), rendered)
    return path


def _http_status(response: Any) -> int:
    value = getattr(response, "status_code", 0)
    try:
        return int(value) if not isinstance(value, bool) else 0
    except (TypeError, ValueError, OverflowError):
        return 0


def _positive_integer(value: Any) -> int | None:
    return value if type(value) is int and value > 0 else None


def _report_http_receipt_failure(receipt: Mapping[str, Any]) -> None:
    try:
        _LOGGER.warning(
            "gravity_http_receipt_write_failed",
            extra={
                "gravity_operation_id": receipt["operation_id"],
                "gravity_method": receipt["method"],
                "gravity_path": receipt["path"],
                "gravity_http_status": receipt["http_status"],
            },
        )
    except Exception:
        pass


def build_receipt(
    *,
    operation_id: str,
    inputs: Mapping[str, Any],
    contract_fingerprint: str | None,
    output: Any,
    status: str,
    duration_ms: float,
    request_count: int,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "receipt_id": uuid.uuid4().hex,
        "created_at": datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
        "operation_id": operation_id,
        "input_shape_fingerprint": shape_fingerprint(inputs),
        "contract_fingerprint": contract_fingerprint,
        "output_shape_fingerprint": shape_fingerprint(output),
        "status": status,
        "duration_ms": round(max(0.0, duration_ms), 3),
        "request_count": max(0, int(request_count)),
    }


def persist_receipt(
    receipt: Mapping[str, Any], state_root: Path
) -> tuple[bool, Path]:
    created_at = str(receipt.get("created_at", "unknown")).replace(":", "").replace(
        "-", ""
    )
    receipt_id = str(receipt.get("receipt_id", "unknown"))
    path = state_root / "receipts" / f"{created_at}-{receipt_id}.json"
    try:
        write_rendered_result(
            str(path),
            json.dumps(dict(receipt), ensure_ascii=False, sort_keys=True) + "\n",
        )
    except (OSError, UnicodeError):
        return False, path
    return path.is_file(), path


__all__ = [
    "build_receipt",
    "count_http_requests",
    "authorized_request_receipt_context",
    "perform_http_request",
    "persist_http_receipt",
    "persist_receipt",
    "record_active_http_response",
    "request_attempt_context",
    "request_receipt_context",
    "record_completed_http_response",
    "record_http_request",
]
