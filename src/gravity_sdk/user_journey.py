"""One bounded, concurrent view of a single user's governed Analysis journey."""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from . import runtime
from .composite_batch import (
    composite_envelope,
    ordered_results,
    validate_composite_bounds,
)
from .composite_catalog import stable_operation
from .errors import InputValidationError, PaginationError


SCHEMA_VERSION = "gravity-insight.user-journey.v1"


def _stable_read(resource: str) -> str:
    return stable_operation("analysis", resource, action="list").operation_id


USER_PROFILE_OPERATION = _stable_read("user_detail")
USER_EVENTS_OPERATION = _stable_read("user_event")
USER_POSTBACKS_OPERATION = _stable_read("user_postback_log")
USER_JOURNEY_OPERATIONS = (
    ("profile", USER_PROFILE_OPERATION),
    ("events", USER_EVENTS_OPERATION),
    ("postbacks", USER_POSTBACKS_OPERATION),
)
MAX_CONCURRENCY = 24
_SENSITIVE_KEYS = frozenset(
    {
        "request",
        "requests",
        "request_id",
        "input",
        "inputs",
        "client_id",
        "clientid",
        "authorization",
        "access_token",
        "token",
        "cookie",
        "password",
        "secret",
        "refresh_token",
        "session_token",
    }
)
_SAFE_ERROR_FIELDS = frozenset(
    {"category", "code", "field", "operation_id", "retryable", "retry_after_ms"}
)


@dataclass(frozen=True)
class _JourneyInput:
    app_id: str
    client_id: str
    event_window: Mapping[str, Any]
    page: int
    page_size: int
    fields: tuple[str, ...]
    events: tuple[str, ...]
    workers: int
    max_items: int


def user_journey(
    client: Any,
    app_id: str | int,
    client_id: str,
    *,
    date_value: str | None = None,
    start: str | None = None,
    end: str | None = None,
    page: int = 1,
    page_size: int = 20,
    fields: Sequence[str] = (),
    events: Sequence[str] = (),
    max_workers: int = 3,
    max_items: int = 100_000,
) -> dict[str, Any]:
    """Read profile, event timeline and postbacks in one isolated batch.

    The event operation has no proven page-info contract. ``page`` and
    ``page_size`` are therefore sent exactly once and never auto-incremented.
    """

    selected = _normalize_input(
        app_id,
        client_id,
        date_value=date_value,
        start=start,
        end=end,
        page=page,
        page_size=page_size,
        fields=fields,
        events=events,
        max_workers=max_workers,
        max_items=max_items,
    )
    requests = _requests(selected)
    raw = runtime.call_batch(
        client,
        requests,
        concurrency=min(selected.workers, len(requests)),
        max_pages=1,
        max_total_items=selected.max_items,
    )
    ordered = ordered_results(raw, requests, component="user journey")
    safe = _safe_results(ordered, secret=selected.client_id)
    _enforce_item_budget(safe, selected.max_items)
    return composite_envelope(
        safe,
        schema_version=SCHEMA_VERSION,
        extra=_envelope_metadata(selected),
    )


def validate_user_journey_input(
    app_id: str | int,
    client_id: str,
    *,
    date_value: str | None = None,
    start: str | None = None,
    end: str | None = None,
    page: int = 1,
    page_size: int = 20,
    fields: Sequence[str] = (),
    events: Sequence[str] = (),
    max_workers: int = 3,
    max_items: int = 100_000,
) -> None:
    """Run the value-free structural validation used by CLI, SDK and Plan."""

    _normalize_input(
        app_id,
        client_id,
        date_value=date_value,
        start=start,
        end=end,
        page=page,
        page_size=page_size,
        fields=fields,
        events=events,
        max_workers=max_workers,
        max_items=max_items,
    )


def _normalize_input(
    app_id: Any,
    client_id: Any,
    *,
    date_value: Any,
    start: Any,
    end: Any,
    page: Any,
    page_size: Any,
    fields: Any,
    events: Any,
    max_workers: Any,
    max_items: Any,
) -> _JourneyInput:
    _, items = validate_composite_bounds(
        1, max_items, minimum_items=len(USER_JOURNEY_OPERATIONS)
    )
    return _JourneyInput(
        app_id=_identifier(app_id, "app_id"),
        client_id=_client_identifier(client_id),
        event_window=_event_window(date_value=date_value, start=start, end=end),
        page=_bounded_integer(page, "page", minimum=1),
        page_size=_bounded_integer(page_size, "page_size", minimum=1, maximum=100),
        fields=_strings(fields, "fields", maximum=100),
        events=_strings(events, "events", maximum=2_000),
        workers=_bounded_integer(
            max_workers, "max_workers", minimum=1, maximum=MAX_CONCURRENCY
        ),
        max_items=items,
    )


def _requests(selected: _JourneyInput) -> list[dict[str, Any]]:
    profile_inputs: dict[str, Any] = {
        "app_id": selected.app_id,
        "client_id": selected.client_id,
        "page": selected.page,
        "page_size": selected.page_size,
    }
    event_inputs: dict[str, Any] = {
        "app_id": selected.app_id,
        "client_id": selected.client_id,
        "page": selected.page,
        "page_size": selected.page_size,
        **selected.event_window,
    }
    if "date" in selected.event_window:
        profile_inputs["date"] = selected.event_window["date"]
    if selected.fields:
        profile_inputs["fields"] = list(selected.fields)
        event_inputs["fields"] = list(selected.fields)
    if selected.events:
        event_inputs["event_list"] = list(selected.events)
    return [
        _request("profile", USER_PROFILE_OPERATION, profile_inputs),
        _request("events", USER_EVENTS_OPERATION, event_inputs),
        _request(
            "postbacks",
            USER_POSTBACKS_OPERATION,
            {"app_id": selected.app_id, "client_id": selected.client_id},
        ),
    ]


def _safe_results(
    ordered: Sequence[Mapping[str, Any]], *, secret: str
) -> list[dict[str, Any]]:
    return [
        _safe_result(result, source=source, secret=secret)
        for (source, _operation_id), result in zip(
            USER_JOURNEY_OPERATIONS, ordered, strict=True
        )
    ]


def _enforce_item_budget(
    results: Sequence[Mapping[str, Any]], max_items: int
) -> None:
    used = sum(_journey_item_count(result) for result in results)
    if used > max_items:
        raise PaginationError("user journey exceeded its aggregate item safety bound")


def _journey_item_count(result: Mapping[str, Any]) -> int:
    envelope = result.get("data")
    if not isinstance(envelope, Mapping):
        return 0
    data = envelope.get("data")
    if isinstance(data, list):
        return len(data)
    if not isinstance(data, Mapping):
        return 0
    count = sum(
        len(rows)
        for key in ("list", "items")
        if isinstance((rows := data.get(key)), list)
    )
    timeline = data.get("event_timeline")
    if isinstance(timeline, list):
        count += sum(
            len(rows)
            for bucket in timeline
            if isinstance(bucket, Mapping)
            and isinstance((rows := bucket.get("list")), list)
        )
    return count


def _envelope_metadata(selected: _JourneyInput) -> dict[str, Any]:
    return {
        "app_id": selected.app_id,
        "source_count": len(USER_JOURNEY_OPERATIONS),
        "scope": "user",
        "continuation": {
            "kind": "explicit_page",
            "next_page": selected.page + 1,
            "page_size": selected.page_size,
            "automatic": False,
            "reason": "user-event has no page_info contract",
        },
    }


def _request(source: str, operation_id: str, inputs: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "request_id": source,
        "operation_id": operation_id,
        "inputs": dict(inputs),
        "read_all": False,
    }


def _safe_result(
    result: Mapping[str, Any], *, source: str, secret: str
) -> dict[str, Any]:
    selected: dict[str, Any] = {}
    for key, value in result.items():
        normalized = str(key).casefold()
        if normalized in _SENSITIVE_KEYS:
            continue
        selected[key] = (
            _safe_error(value)
            if normalized == "error"
            else _scrub(copy.deepcopy(value), secret=secret)
        )
    selected["source"] = source
    selected["scope"] = "user"
    return selected


def _safe_error(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    selected = {
        key: copy.deepcopy(item)
        for key, item in value.items()
        if str(key) in _SAFE_ERROR_FIELDS
    }
    return {
        **selected,
        "message": "A user journey source failed without exposing request details.",
        "next_action": "Inspect this source category/code and retry the explicit page.",
    }


def _scrub(value: Any, *, secret: str) -> Any:
    if isinstance(value, Mapping):
        return {
            key: _scrub(item, secret=secret)
            for key, item in value.items()
            if str(key).casefold() not in _SENSITIVE_KEYS
        }
    if isinstance(value, list):
        return [_scrub(item, secret=secret) for item in value]
    if isinstance(value, tuple):
        return [_scrub(item, secret=secret) for item in value]
    if isinstance(value, str) and secret in value:
        pattern = rf"(?<![A-Za-z0-9_-]){re.escape(secret)}(?![A-Za-z0-9_-])"
        return re.sub(pattern, "[REDACTED]", value)
    return value


def _event_window(
    *, date_value: str | None, start: str | None, end: str | None
) -> dict[str, Any]:
    if date_value is not None:
        if start is not None or end is not None:
            raise InputValidationError(
                "user journey date cannot be combined with start/end", field="date"
            )
        return {"date": _iso_date(date_value, "date")}
    if start is None or end is None:
        raise InputValidationError(
            "user journey requires date or paired start/end", field="date"
        )
    first = _iso_date(start, "start")
    last = _iso_date(end, "end")
    if first > last:
        raise InputValidationError(
            "user journey start must not follow end", field="start/end"
        )
    return {"date_list": [first, last]}


def _iso_date(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise InputValidationError(
            "user journey dates must use YYYY-MM-DD", field=field
        )
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        raise InputValidationError(
            "user journey dates must use YYYY-MM-DD", field=field
        ) from None


def _identifier(value: Any, field: str) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise InputValidationError(
            f"user journey {field} must be a bounded identifier", field=field
        )
    rendered = str(value).strip()
    if not rendered or len(rendered) > 64:
        raise InputValidationError(
            f"user journey {field} must be a bounded identifier", field=field
        )
    return rendered


def _client_identifier(value: Any) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 256:
        raise InputValidationError(
            "user journey client_id must be a bounded identifier", field="client_id"
        )
    return value.strip()


def _bounded_integer(
    value: Any, field: str, *, minimum: int, maximum: int | None = None
) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < minimum
        or (maximum is not None and value > maximum)
    ):
        bound = f"{minimum}..{maximum}" if maximum is not None else f">={minimum}"
        raise InputValidationError(
            f"user journey {field} must be {bound}", field=field
        )
    return value


def _strings(value: Any, field: str, *, maximum: int) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise InputValidationError(
            f"user journey {field} must be a string array", field=field
        )
    selected = tuple(value)
    if len(selected) > maximum or any(
        not isinstance(item, str) or not item or len(item) > 256 for item in selected
    ):
        raise InputValidationError(
            f"user journey {field} is outside its contract", field=field
        )
    return selected


__all__ = [
    "SCHEMA_VERSION",
    "USER_EVENTS_OPERATION",
    "USER_JOURNEY_OPERATIONS",
    "USER_POSTBACKS_OPERATION",
    "USER_PROFILE_OPERATION",
    "user_journey",
    "validate_user_journey_input",
]
