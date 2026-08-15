"""Versioned, layout-independent queries over private HTTP receipt storage."""

from __future__ import annotations

import base64
import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .errors import InputValidationError
from .receipt import HTTP_SCHEMA_VERSION
from .receipt_retention import _process_is_alive, _receipt_process_id
from .result_audit import STORED, WRITE_FAILED, receipt_reference
from .result_output import write_rendered_result
from .result_source import LOCAL_AUDIT, result_source
from .response_drift import normalize_response_drift


QUERY_SCHEMA_VERSION = "gravity.http-receipt-query.v1"
EXPORT_SCHEMA_VERSION = "gravity.http-receipt-export.v1"
DEFAULT_PAGE_SIZE = 100
MAX_PAGE_SIZE = 1_000
MAX_EXPORT_ITEMS = 10_000
_RECEIPT_FIELDS = frozenset(
    {
        "schema_version", "receipt_id", "completed_at", "operation_id", "method",
        "path", "http_status", "page_number", "attempt", "retry",
        "request_shape_fingerprint",
    }
)


@dataclass(frozen=True)
class _StoredReceipt:
    value: Mapping[str, Any]
    run_status: str

    @property
    def key(self) -> tuple[str, str]:
        return str(self.value["completed_at"]), str(self.value["receipt_id"])

    def public_value(self) -> dict[str, Any]:
        return {**dict(self.value), "run_status": self.run_status}


@dataclass(frozen=True)
class _Scan:
    receipts: tuple[_StoredReceipt, ...]
    corrupt_tokens: tuple[str, ...]
    corrupt_ids: frozenset[str]
    unreadable: bool = False


def list_http_receipts(
    state_root: str | Path,
    *,
    limit: int = DEFAULT_PAGE_SIZE,
    cursor: str | None = None,
    operation_id: str | None = None,
) -> dict[str, Any]:
    """Return one snapshot-bound keyset page in deterministic newest-first order."""

    return _list_http_receipts(
        state_root,
        limit=_bounded(limit, MAX_PAGE_SIZE, "limit"),
        cursor=cursor,
        operation_id=_operation_filter(operation_id),
    )


def get_http_receipt(
    state_root: str | Path,
    reference: str | Mapping[str, Any],
) -> dict[str, Any]:
    """Resolve one opaque reference with explicit absent-state semantics."""

    receipt_id, storage_status = _query_reference(reference)
    if storage_status == WRITE_FAILED:
        return _envelope(
            status="capability_gap",
            items=[],
            gaps=[_gap(WRITE_FAILED)],
            ok=False,
        )
    scan = _scan(Path(state_root))
    if scan.unreadable:
        return _envelope(
            status="capability_gap",
            items=[],
            gaps=[_gap("storage_unreadable")],
            ok=False,
        )
    selected = next(
        (item for item in scan.receipts if item.value["receipt_id"] == receipt_id),
        None,
    )
    if selected is not None:
        active = selected.run_status == "run_in_progress"
        return _envelope(
            status="partial" if active else "success",
            items=[selected.public_value()],
            gaps=[_gap("run_in_progress")] if active else [],
            ok=not active,
        )
    if receipt_id in scan.corrupt_ids:
        return _envelope(
            status="partial",
            items=[],
            gaps=[_gap("corrupt_receipt")],
            ok=False,
        )
    gap = "retention_pruned" if storage_status == STORED else "unknown_receipt"
    return _envelope(
        status="capability_gap",
        items=[],
        gaps=[_gap(gap)],
        ok=False,
    )


def export_http_receipts(
    state_root: str | Path,
    destination: str | Path,
    *,
    max_items: int = MAX_EXPORT_ITEMS,
    operation_id: str | None = None,
) -> dict[str, Any]:
    """Write one bounded snapshot query without exposing its private source files."""

    query = _list_http_receipts(
        state_root,
        limit=_bounded(max_items, MAX_EXPORT_ITEMS, "max_items"),
        cursor=None,
        operation_id=_operation_filter(operation_id),
    )
    rendered = json.dumps(query, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    output = write_rendered_result(str(destination), rendered)
    return {
        "schema_version": EXPORT_SCHEMA_VERSION,
        "result_source": result_source(LOCAL_AUDIT),
        "ok": query["ok"],
        "status": query["status"],
        "query": {
            "schema_version": query["schema_version"],
            "page": query["page"],
            "gaps": query["gaps"],
        },
        "output": output,
    }


def _list_http_receipts(
    state_root: str | Path,
    *,
    limit: int,
    cursor: str | None,
    operation_id: str | None,
) -> dict[str, Any]:
    cursor_value = _decode_cursor(cursor, operation_id) if cursor else None
    as_of = (
        str(cursor_value["as_of"])
        if cursor_value is not None
        else datetime.now(timezone.utc).isoformat(timespec="microseconds").replace(
            "+00:00", "Z"
        )
    )
    scan = _scan(Path(state_root))
    page = _page(limit=limit, as_of=as_of)
    if scan.unreadable:
        return _envelope(
            status="capability_gap", items=[], gaps=[_gap("storage_unreadable")],
            ok=False, page=page,
        )
    candidates = _snapshot_candidates(scan, as_of, operation_id)
    snapshot = _snapshot_fingerprint(candidates, scan.corrupt_tokens)
    if cursor_value is not None and cursor_value["snapshot"] != snapshot:
        return _envelope(
            status="partial", items=[], gaps=[_gap("snapshot_changed")],
            ok=False, page=page,
        )
    selected, has_more, next_cursor = _select_page(
        candidates, limit, cursor_value, as_of, snapshot, operation_id
    )
    active_count = sum(item.run_status == "run_in_progress" for item in candidates)
    gaps = _list_gaps(len(scan.corrupt_tokens), active_count)
    status = "partial" if gaps else "empty" if not selected else "success"
    return _envelope(
        status=status,
        items=[item.public_value() for item in selected],
        gaps=gaps,
        ok=not gaps,
        page={
            **page,
            "returned": len(selected),
            "has_more": has_more,
            "next_cursor": next_cursor,
            "snapshot_fingerprint": snapshot,
        },
    )


def _snapshot_candidates(
    scan: _Scan, as_of: str, operation_id: str | None
) -> list[_StoredReceipt]:
    selected = [
        item
        for item in scan.receipts
        if item.value["completed_at"] <= as_of
        and (operation_id is None or item.value["operation_id"] == operation_id)
    ]
    return sorted(selected, key=lambda item: item.key, reverse=True)


def _select_page(
    candidates: list[_StoredReceipt],
    limit: int,
    cursor: Mapping[str, Any] | None,
    as_of: str,
    snapshot: str,
    operation_id: str | None,
) -> tuple[list[_StoredReceipt], bool, str | None]:
    after = tuple(cursor["after"]) if cursor is not None else None
    remaining = (
        [item for item in candidates if item.key < after]
        if after is not None
        else candidates
    )
    selected = remaining[:limit]
    has_more = len(remaining) > limit
    next_cursor = (
        _encode_cursor(as_of, snapshot, selected[-1].key, operation_id)
        if has_more and selected
        else None
    )
    return selected, has_more, next_cursor


def _list_gaps(corrupt_count: int, active_count: int) -> list[dict[str, Any]]:
    gaps: list[dict[str, Any]] = []
    if corrupt_count:
        gaps.append(_gap("corrupt_receipt", corrupt_count))
    if active_count:
        gaps.append(_gap("run_in_progress", active_count))
    return gaps


def _scan(state_root: Path) -> _Scan:
    directory = state_root / "receipts" / "http"
    try:
        directory.stat()
    except FileNotFoundError:
        return _Scan((), (), frozenset())
    except OSError:
        return _Scan((), (), frozenset(), unreadable=True)
    try:
        with os.scandir(directory) as iterator:
            entries = sorted(
                (entry for entry in iterator if entry.name.endswith(".json")),
                key=lambda entry: entry.name,
            )
    except OSError:
        return _Scan((), (), frozenset(), unreadable=True)
    parsed: list[tuple[_StoredReceipt, str]] = []
    corrupt_tokens: list[str] = []
    corrupt_ids: set[str] = set()
    for entry in entries:
        item, token, candidate_id = _read_entry(entry)
        if item is None:
            corrupt_tokens.append(token)
            if candidate_id is not None:
                corrupt_ids.add(candidate_id)
        else:
            parsed.append((item, token))
    counts: dict[str, int] = {}
    for item, _ in parsed:
        identifier = str(item.value["receipt_id"])
        counts[identifier] = counts.get(identifier, 0) + 1
    receipts: list[_StoredReceipt] = []
    for item, token in parsed:
        identifier = str(item.value["receipt_id"])
        if counts[identifier] == 1:
            receipts.append(item)
        else:
            corrupt_tokens.append(token)
            corrupt_ids.add(identifier)
    return _Scan(
        tuple(receipts), tuple(sorted(corrupt_tokens)), frozenset(corrupt_ids)
    )


def _read_entry(entry: os.DirEntry[str]) -> tuple[_StoredReceipt | None, str, str | None]:
    material = entry.name.encode("utf-8", "surrogatepass")
    candidate_id: str | None = None
    try:
        if not entry.is_file(follow_symlinks=False):
            raise OSError("receipt entry is not a regular file")
        content = Path(entry.path).read_bytes()
        material += b"\0" + content
        value = json.loads(content.decode("utf-8"))
        if isinstance(value, Mapping) and _valid_receipt_id(value.get("receipt_id")):
            candidate_id = str(value["receipt_id"])
        normalized = _validated_receipt(value)
        pid = _receipt_process_id(entry.name)
        run_status = (
            "run_in_progress"
            if pid is not None and _process_is_alive(pid)
            else "completed"
        )
        return _StoredReceipt(normalized, run_status), _digest(material), candidate_id
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, TypeError):
        return None, _digest(material), candidate_id


def _validated_receipt(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) not in {
        _RECEIPT_FIELDS,
        _RECEIPT_FIELDS | {"response_drift"},
    }:
        raise ValueError("HTTP receipt fields changed")
    _validate_receipt_identity(value)
    completed_at = value.get("completed_at")
    if not isinstance(completed_at, str) or not _canonical_timestamp(completed_at):
        raise ValueError("HTTP receipt timestamp is invalid")
    _validate_receipt_route(value)
    _validate_receipt_attempt(value)
    selected = dict(value)
    if value.get("response_drift") is not None:
        selected["response_drift"] = normalize_response_drift(value["response_drift"])
    return selected


def _validate_receipt_identity(value: Mapping[str, Any]) -> None:
    if value.get("schema_version") != HTTP_SCHEMA_VERSION:
        raise ValueError("HTTP receipt schema changed")
    if not _valid_receipt_id(value.get("receipt_id")):
        raise ValueError("HTTP receipt id is invalid")


def _validate_receipt_route(value: Mapping[str, Any]) -> None:
    operation_id, method, path = value.get("operation_id"), value.get("method"), value.get("path")
    if not isinstance(operation_id, str) or not operation_id:
        raise ValueError("HTTP receipt operation is invalid")
    if method not in {"GET", "POST"} or not isinstance(path, str) or not path.startswith("/"):
        raise ValueError("HTTP receipt route is invalid")


def _validate_receipt_attempt(value: Mapping[str, Any]) -> None:
    status, page, attempt = value.get("http_status"), value.get("page_number"), value.get("attempt")
    if type(status) is not int or not 0 <= status <= 999:
        raise ValueError("HTTP receipt status is invalid")
    if page is not None and (type(page) is not int or page <= 0):
        raise ValueError("HTTP receipt page is invalid")
    if type(attempt) is not int or attempt <= 0 or type(value.get("retry")) is not bool:
        raise ValueError("HTTP receipt attempt is invalid")
    fingerprint = value.get("request_shape_fingerprint")
    if not _valid_digest(fingerprint):
        raise ValueError("HTTP receipt fingerprint is invalid")


def _query_reference(value: str | Mapping[str, Any]) -> tuple[str, str | None]:
    if isinstance(value, str):
        if not _valid_receipt_id(value):
            raise InputValidationError("receipt_id is invalid", field="receipt_id")
        return value, None
    if not isinstance(value, Mapping) or set(value) != {"receipt_id", "storage_status"}:
        raise InputValidationError("receipt reference is invalid", field="reference")
    try:
        reference = receipt_reference(value["receipt_id"], str(value["storage_status"]))
    except ValueError as error:
        raise InputValidationError(str(error), field="reference") from None
    return reference["receipt_id"], reference["storage_status"]


def _encode_cursor(
    as_of: str, snapshot: str, after: tuple[str, str], operation_id: str | None
) -> str:
    raw = json.dumps(
        {"v": 1, "as_of": as_of, "snapshot": snapshot, "after": list(after),
         "operation_id": operation_id},
        sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(value: str, operation_id: str | None) -> Mapping[str, Any]:
    try:
        padding = "=" * (-len(value) % 4)
        decoded = json.loads(base64.urlsafe_b64decode(value + padding).decode("utf-8"))
        return _validated_cursor(decoded, operation_id)
    except (ValueError, TypeError, UnicodeError, json.JSONDecodeError):
        raise InputValidationError("cursor is invalid", field="cursor") from None


def _validated_cursor(value: object, operation_id: str | None) -> Mapping[str, Any]:
    fields = {"v", "as_of", "snapshot", "after", "operation_id"}
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ValueError
    after = value["after"]
    if value["v"] != 1 or value["operation_id"] != operation_id:
        raise ValueError
    if not isinstance(value["as_of"], str) or not _canonical_timestamp(value["as_of"]):
        raise ValueError
    if not _valid_digest(value["snapshot"]):
        raise ValueError
    if not isinstance(after, list) or len(after) != 2 or not all(isinstance(item, str) for item in after):
        raise ValueError
    if not _canonical_timestamp(after[0]) or not _valid_receipt_id(after[1]):
        raise ValueError
    return value


def _snapshot_fingerprint(
    receipts: list[_StoredReceipt], corrupt_tokens: tuple[str, ...]
) -> str:
    return _digest(
        json.dumps(
            {"keys": [list(item.key) for item in receipts], "corrupt": list(corrupt_tokens)},
            sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")
    )


def _envelope(
    *, status: str, items: list[dict[str, Any]], gaps: list[dict[str, Any]],
    ok: bool, page: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": QUERY_SCHEMA_VERSION,
        "result_source": result_source(LOCAL_AUDIT),
        "ok": ok,
        "status": status,
        "items": items,
        "page": dict(page or _page(limit=1, as_of=None)),
        "gaps": gaps,
    }


def _page(*, limit: int, as_of: str | None) -> dict[str, Any]:
    return {
        "limit": limit,
        "returned": 0,
        "has_more": False,
        "next_cursor": None,
        "sort": ["completed_at:desc", "receipt_id:desc"],
        "as_of": as_of,
        "snapshot_fingerprint": None,
    }


def _gap(kind: str, count: int = 1) -> dict[str, Any]:
    return {"kind": kind, "count": count}


def _bounded(value: object, maximum: int, field: str) -> int:
    if type(value) is not int or not 1 <= value <= maximum:
        raise InputValidationError(
            f"{field} must be between 1 and {maximum}", field=field
        )
    return value


def _operation_filter(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > 128:
        raise InputValidationError("operation_id filter is invalid", field="operation_id")
    return value.strip()


def _canonical_timestamp(value: str) -> bool:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return (
        parsed.tzinfo is not None
        and parsed.utcoffset() == timezone.utc.utcoffset(parsed)
        and parsed.astimezone(timezone.utc).isoformat(timespec="microseconds").replace(
            "+00:00", "Z"
        ) == value
    )


def _valid_receipt_id(value: object) -> bool:
    return isinstance(value, str) and len(value) == 32 and all(
        character in "0123456789abcdef" for character in value
    )


def _valid_digest(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(
        character in "0123456789abcdef" for character in value
    )


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


__all__ = [
    "DEFAULT_PAGE_SIZE",
    "EXPORT_SCHEMA_VERSION",
    "MAX_EXPORT_ITEMS",
    "MAX_PAGE_SIZE",
    "QUERY_SCHEMA_VERSION",
    "export_http_receipts",
    "get_http_receipt",
    "list_http_receipts",
]
