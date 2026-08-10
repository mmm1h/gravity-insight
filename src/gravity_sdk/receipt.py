"""Value-free execution receipts and scoped HTTP request accounting."""

from __future__ import annotations

import contextvars
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping

from .fingerprints import shape_fingerprint, write_json_atomic


SCHEMA_VERSION = "gravity.receipt.v1"


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


def perform_http_request(request: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    record_http_request()
    return request(*args, **kwargs)


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
    write_json_atomic(path, receipt)
    return path.is_file(), path


__all__ = [
    "build_receipt",
    "count_http_requests",
    "perform_http_request",
    "persist_receipt",
    "record_http_request",
]
