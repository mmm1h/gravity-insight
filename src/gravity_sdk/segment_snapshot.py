"""Bounded aggregate inspection for one exact Analysis segment.

The product composes only existing stable read contracts.  It resolves one
segment from the complete bounded catalog and then reads its definition,
version history, and one explicitly selected natural-day result.  User-level
member rows and the omitted ``origin_query`` are deliberately outside v1.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from . import runtime
from .composite_batch import (
    annotate_result,
    composite_envelope,
    ordered_results,
)
from .composite_catalog import stable_operation
from .errors import (
    ContractChangedError,
    ErrorCode,
    ErrorDetail,
    GravityInsightError,
    InputValidationError,
    LocalIOError,
    PaginationError,
)
from .segment_snapshot_inputs import (
    DEFAULT_CONCURRENCY,
    MAX_CONCURRENCY,
    MIN_SNAPSHOT_ITEMS,
    bounded_text as _bounded_text,
    matches_app as _matches_app,
    positive_id as _positive_id,
    validate_segment_snapshot_request,
)
from .account_permission_profile import PERMISSION_EMPTY_NEXT_ACTION
from .actionable_error_values import actual_value


SCHEMA_VERSION = "gravity-insight.segment-snapshot.v1"
SOURCE_COUNT = 3
_SUCCESS = frozenset({"success", "empty", "contract_changed_additive"})
_ERROR_CODES = frozenset(item.value for item in ErrorCode)
_SAFE_EXTENSION_CODES = frozenset({"BATCH_RESULT_MISSING"})


@dataclass(frozen=True)
class SegmentIdentity:
    segment_id: str
    name: str

    def to_dict(self) -> dict[str, str]:
        return {"id": self.segment_id, "name": self.name}


@dataclass(frozen=True)
class SegmentSource:
    source: str
    operation_id: str
    paginated: bool


def _operation(resource: str, action: str) -> str:
    return stable_operation("analysis", resource, action=action).operation_id


LIST_OPERATION = _operation("segment", "list")
SEGMENT_SOURCES = (
    SegmentSource("detail", _operation("segment", "get"), False),
    SegmentSource("history", _operation("segment_history_version", "list"), True),
    SegmentSource("daily_result", _operation("segment_uid_result", "list"), True),
)


def segment_snapshot(
    client: Any,
    app_id: str | int,
    ref: str | int,
    *,
    date: str,
    max_workers: int = DEFAULT_CONCURRENCY,
    max_pages: int = 1_000,
    max_items: int = 100_000,
) -> dict[str, Any]:
    """Resolve one segment and return three ordered aggregate sources."""

    selected_app, selected_ref, selected_date, workers, pages, items = (
        validate_segment_snapshot_request(
            app_id,
            ref,
            date=date,
            max_workers=max_workers,
            max_pages=max_pages,
            max_items=max_items,
        )
    )
    catalog = _read_catalog(
        client,
        selected_app,
        pages=pages,
        items=items - SOURCE_COUNT,
    )
    identity = _resolve_identity(catalog, selected_ref, selected_app)
    if len(catalog) + SOURCE_COUNT > items:
        raise PaginationError(
            "segment catalog and fixed sources exceed the aggregate item safety bound"
        )
    remaining = items - len(catalog)
    if remaining < SOURCE_COUNT:
        raise PaginationError(
            "segment catalog left no capacity for the fixed snapshot sources"
        )
    requests = _requests(identity.segment_id, selected_date)
    ordered = _read_sources(
        client,
        requests,
        workers=workers,
        pages=pages,
        items=remaining,
    )
    results = [
        annotate_result(
            _safe_result(raw, source, identity, selected_app),
            source=source.source,
            scope="segment" if source.source == "detail" else "aggregate",
        )
        for source, raw in zip(SEGMENT_SOURCES, ordered, strict=True)
    ]
    if len(catalog) + SOURCE_COUNT + _row_count(results) > items:
        raise PaginationError(
            "segment snapshot exceeded the aggregate item safety bound"
        )
    envelope = composite_envelope(
        results,
        schema_version=SCHEMA_VERSION,
        extra={
            "app_id": selected_app,
            "segment": identity.to_dict(),
            "date": selected_date,
            "source_count": SOURCE_COUNT,
            "scopes": ["segment", "aggregate"],
        },
    )
    if envelope["total_count"] != SOURCE_COUNT:
        raise RuntimeError("segment snapshot result count invariant failed")
    return envelope


def _read_catalog(
    client: Any, app_id: str, *, pages: int, items: int
) -> list[Mapping[str, Any]]:
    try:
        envelope = runtime.call_read(
            client,
            LIST_OPERATION,
            {"app_id": app_id, "page": 1, "page_size": min(100, items)},
            max_pages=pages,
            max_items=items,
            max_workers=1,
        )
    except PaginationError:
        raise
    except GravityInsightError as exc:
        raise _safe_exception(exc.to_error_detail(), "catalog", LIST_OPERATION) from None
    except Exception:
        raise LocalIOError(
            "segment snapshot catalog client failed locally",
            next_action="Inspect the local Gravity client, then retry the snapshot.",
        ) from None
    if not isinstance(envelope, Mapping):
        raise ContractChangedError("segment catalog returned an invalid envelope")
    if envelope.get("ok") is not True or _status(envelope) not in _SUCCESS:
        raise _safe_exception(envelope.get("error"), "catalog", LIST_OPERATION)
    if envelope.get("truncated") is True or envelope.get("next_page_input") not in (
        None,
        {},
    ):
        raise PaginationError(
            "segment catalog exceeded the snapshot discovery safety bound",
            next_action=(
                "Increase max_pages/max_items within the documented limits and retry; "
                "do not treat a truncated catalog as not found."
            ),
        )
    data = envelope.get("data")
    rows = data.get("list") if isinstance(data, Mapping) else None
    if not isinstance(rows, list):
        raise ContractChangedError("segment catalog no longer returns data.list")
    if len(rows) > items or any(not isinstance(row, Mapping) for row in rows):
        raise ContractChangedError("segment catalog returned invalid bounded rows")
    return rows


def _resolve_identity(
    rows: Sequence[Mapping[str, Any]], ref: str, app_id: str
) -> SegmentIdentity:
    identities: list[SegmentIdentity] = []
    seen_ids: set[str] = set()
    for row in rows:
        segment_id = _row_identity(row)
        name = _bounded_text(row.get("segment_name"))
        if segment_id is None or name is None:
            raise ContractChangedError("segment catalog returned an incomplete identity")
        if segment_id in seen_ids:
            raise ContractChangedError("segment catalog returned a duplicate identity")
        seen_ids.add(segment_id)
        row_app = row.get("app_id")
        if row_app is not None and not _matches_app(row_app, app_id):
            raise ContractChangedError("segment catalog returned an App identity mismatch")
        identities.append(SegmentIdentity(segment_id, name))
    by_id = [item for item in identities if item.segment_id == ref]
    matches = by_id or [item for item in identities if item.name == ref]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise InputValidationError(
            f"actual value: {actual_value(len(matches))}; " + ("segment ref matches more than one exact name"),
            field="ref",
            next_action="Retry with the stable segment id from the segment catalog.",
        )
    raise InputValidationError(
        "segment ref does not match an exact segment id or name",
        field="ref",
        next_action=(
            PERMISSION_EMPTY_NEXT_ACTION
            if not identities
            else "Inspect the segment catalog and retry with an exact id or name."
        ),
    )


def _requests(segment_id: str, selected_date: str) -> list[dict[str, Any]]:
    return [
        {
            "operation_id": source.operation_id,
            "request_id": source.source,
            "inputs": _source_inputs(source.source, segment_id, selected_date),
            "read_all": source.paginated,
        }
        for source in SEGMENT_SOURCES
    ]


def _source_inputs(source: str, segment_id: str, selected_date: str) -> dict[str, Any]:
    if source == "detail":
        return {"segment_id": segment_id}
    inputs: dict[str, Any] = {"segment_id": segment_id, "page": 1, "page_size": 100}
    if source == "daily_result":
        inputs["date"] = selected_date
    return inputs


def _read_sources(
    client: Any,
    requests: Sequence[Mapping[str, Any]],
    *,
    workers: int,
    pages: int,
    items: int,
) -> list[dict[str, Any]]:
    try:
        raw = runtime.call_batch(
            client,
            requests,
            concurrency=workers,
            max_pages=pages,
            max_total_items=items,
        )
        return ordered_results(raw, requests, component="segment snapshot")
    except PaginationError:
        raise
    except GravityInsightError as exc:
        raise _safe_exception(exc.to_error_detail(), "batch", None) from None
    except Exception:
        raise LocalIOError(
            "segment snapshot batch client failed locally",
            next_action="Inspect the local Gravity client, then retry the snapshot.",
        ) from None


def _safe_result(
    raw: Mapping[str, Any],
    source: SegmentSource,
    identity: SegmentIdentity,
    app_id: str,
) -> dict[str, Any]:
    status = _status(raw)
    if raw.get("ok") is not True or status not in _SUCCESS:
        return _failed_result(source, raw.get("error"))
    native = raw.get("data")
    if not isinstance(native, Mapping) or _status(native) not in _SUCCESS:
        return _failed_result(source, ErrorCode.CONTRACT_CHANGED)
    try:
        data = _project_source(source.source, native.get("data"), identity, app_id)
    except ContractChangedError:
        return _failed_result(source, ErrorCode.CONTRACT_CHANGED)
    safe_status = (
        "contract_changed_additive"
        if "contract_changed_additive" in {status, _status(native)}
        else _status(native)
    )
    return {
        "operation_id": source.operation_id,
        "ok": True,
        "status": safe_status,
        "data": {
            "schema_version": "gravity-insight.read.v1",
            "operation_id": source.operation_id,
            "status": safe_status,
            "data": data,
        },
        "error": None,
    }


def _project_source(
    source: str,
    value: Any,
    identity: SegmentIdentity,
    app_id: str,
) -> dict[str, Any]:
    data = _mapping(value, f"{source}.data")
    if source == "detail":
        if _row_identity(data) != identity.segment_id:
            raise ContractChangedError("segment detail identity changed")
        detail_name = _bounded_text(data.get("segment_name"))
        if detail_name is not None and detail_name != identity.name:
            raise ContractChangedError("segment detail name changed")
        raw_app = data.get("app_id")
        if raw_app is not None and not _matches_app(raw_app, app_id):
            raise ContractChangedError("segment detail App identity changed")
        return _copy_fields(
            data,
            (
                "id", "segment_id", "app_id", "segment_name", "segment_remark",
                "user_cnt", "operation_status", "latest_version_calculation_status",
                "latest_result_finish_time", "analysis_scene", "update_type",
                "create_time", "modify_time",
            ),
            nested={"update_date_range": ("start_date", "end_date")},
        )
    rows = data.get("list")
    if not isinstance(rows, list) or any(not isinstance(row, Mapping) for row in rows):
        raise ContractChangedError(f"segment {source} no longer returns data.list")
    row_fields = (
        ("version_id", "uid_cnt", "execute_result", "calculation_status")
        if source == "history"
        else ("create_date", "user_cnt", "calculation_status")
    )
    projected = {"list": [_copy_fields(row, row_fields) for row in rows]}
    if source == "history":
        projected.update(_copy_fields(data, ("page", "page_size", "total")))
    else:
        projected.update(
            _copy_fields(
                data,
                (),
                nested={
                    "page_info": ("page", "page_size", "total_number", "total_page")
                },
            )
        )
    return projected


def _copy_fields(
    value: Mapping[str, Any],
    fields: Sequence[str],
    *,
    nested: Mapping[str, Sequence[str]] | None = None,
) -> dict[str, Any]:
    selected = {
        field: copy.deepcopy(value[field]) for field in fields if field in value
    }
    for field, children in (nested or {}).items():
        if field not in value or value[field] is None:
            continue
        child = _mapping(value[field], field)
        selected[field] = {
            key: copy.deepcopy(child[key]) for key in children if key in child
        }
    return selected


def _failed_result(
    source: SegmentSource, error: Any
) -> dict[str, Any]:
    detail = _safe_error(error, source)
    return {
        "operation_id": source.operation_id,
        "ok": False,
        "status": "contract_changed" if detail.code == "CONTRACT_CHANGED" else "error",
        "data": None,
        "error": detail.to_dict(),
    }


def _safe_error(value: Any, source: SegmentSource) -> ErrorDetail:
    if isinstance(value, ErrorCode):
        code = value.value
        raw: Mapping[str, Any] = {}
    else:
        raw = value if isinstance(value, Mapping) else {}
        candidate = str(raw.get("code", "")).strip().upper()
        code = (
            candidate
            if candidate in _ERROR_CODES | _SAFE_EXTENSION_CODES
            else ErrorCode.LOCAL_IO_ERROR.value
        )
    retry_after = raw.get("retry_after_ms")
    return ErrorDetail.create(
        code,
        f"Segment snapshot source `{source.source}` failed.",
        operation_id=source.operation_id,
        retry_after_ms=(
            retry_after
            if code == ErrorCode.RATE_LIMITED.value
            and type(retry_after) is int
            and retry_after >= 0
            else None
        ),
    )


def _safe_exception(
    value: Any, component: str, operation_id: str | None
) -> GravityInsightError:
    raw = value.to_dict() if isinstance(value, ErrorDetail) else value
    raw = raw if isinstance(raw, Mapping) else {}
    candidate = str(raw.get("code", "")).strip().upper()
    code = candidate if candidate in _ERROR_CODES else ErrorCode.UPSTREAM_UNAVAILABLE.value
    retry_after = raw.get("retry_after_ms")
    detail = ErrorDetail.create(
        code,
        f"Segment snapshot {component} read failed.",
        operation_id=operation_id,
        retry_after_ms=(
            retry_after
            if code == ErrorCode.RATE_LIMITED.value
            and type(retry_after) is int
            and retry_after >= 0
            else None
        ),
    )
    return GravityInsightError(
        detail.message,
        code=detail.code,
        retry_after_ms=detail.retry_after_ms,
        next_action=detail.next_action,
    )


def _row_count(results: Sequence[Mapping[str, Any]]) -> int:
    total = 0
    for result in results:
        native = result.get("data")
        data = native.get("data") if isinstance(native, Mapping) else None
        if isinstance(data, Mapping) and isinstance(data.get("list"), list):
            total += len(data["list"])
    return total


def _row_identity(value: Mapping[str, Any]) -> str | None:
    primary = _bounded_text(value.get("segment_id"))
    alternate = _bounded_text(value.get("id"))
    if primary is not None and alternate is not None and primary != alternate:
        raise ContractChangedError("segment identity fields disagree")
    return primary or alternate


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractChangedError(f"segment snapshot returned invalid {field}")
    return value


def _status(value: Mapping[str, Any]) -> str:
    status = value.get("status")
    return status.strip().casefold() if isinstance(status, str) else ""


__all__ = [
    "DEFAULT_CONCURRENCY",
    "LIST_OPERATION",
    "MAX_CONCURRENCY",
    "MIN_SNAPSHOT_ITEMS",
    "SCHEMA_VERSION",
    "SEGMENT_SOURCES",
    "SOURCE_COUNT",
    "segment_snapshot",
    "validate_segment_snapshot_request",
]
