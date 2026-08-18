"""Deterministic relative calendar windows with an explicit timezone.

Callers may pass ISO dates or a closed set of Chinese/English relative
phrases. Ambiguous phrases fail closed. The calendar day is always taken
from an explicit IANA timezone; the process local zone is never used.

Timezone source, in order:

1. an explicit ``timezone=`` argument;
2. ``GRAVITY_TIMEZONE``;
3. ``workspace.defaults.timezone`` when a configured workspace is loaded;
4. ``Asia/Shanghai``.

The default is Gravity's documented business calendar (SQL products,
Evidence, credentials, and production windows all use Asia/Shanghai).
An unconfigured workspace reports ``timezone="UTC"`` as a placeholder
and is not consulted here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .actionable_error_values import actual_value
from .errors import InputValidationError
from .relative_date_lexicon import (
    AMBIGUOUS,
    ISO_DATE,
    NAMED_OFFSETS,
    ORDERED_PHRASES,
    RANGE_PHRASES,
    REMEDY,
    classify_token,
    extract_rolling,
    match_rolling,
    normalize_phrase,
    phrase_present,
    reject,
)


DEFAULT_TIMEZONE = "Asia/Shanghai"
DEFAULT_TIMEZONE_SOURCE = "sdk_default"
SCHEMA_VERSION = "gravity.relative-date-window.v1"
ISO_DATE_HELP = "YYYY-MM-DD"
WEEK_START = 0  # Monday; matches analysis.retention.query week_first_day=1.


@dataclass(frozen=True)
class RelativeDateWindow:
    """One inclusive calendar window plus the timezone that defined it."""

    start: str
    end: str
    timezone: str
    timezone_source: str
    expression: str
    kind: str

    def to_dict(self) -> dict[str, str]:
        return {
            "schema_version": SCHEMA_VERSION,
            "expression": self.expression,
            "kind": self.kind,
            "start": self.start,
            "end": self.end,
            "timezone": self.timezone,
            "timezone_source": self.timezone_source,
            "inclusive": "true",
            "display": (
                f"{self.expression} → {self.start}..{self.end} "
                f"({self.timezone})"
            ),
        }

    def with_zone(self, timezone_name: str, timezone_source: str) -> RelativeDateWindow:
        return RelativeDateWindow(
            start=self.start,
            end=self.end,
            timezone=timezone_name,
            timezone_source=timezone_source,
            expression=self.expression,
            kind=self.kind,
        )


def resolve_timezone(
    timezone_name: str | None = None,
    *,
    workspace: Any | None = None,
) -> tuple[str, str, ZoneInfo]:
    """Return ``(iana_name, source, zone)`` without using the host zone."""

    if timezone_name is not None:
        return timezone_name, "explicit", _zone(timezone_name, field="timezone")
    configured = _workspace_timezone(workspace)
    if configured is not None:
        return configured, "workspace.defaults.timezone", _zone(
            configured, field="timezone"
        )
    return DEFAULT_TIMEZONE, DEFAULT_TIMEZONE_SOURCE, _zone(
        DEFAULT_TIMEZONE, field="timezone"
    )


def calendar_today(
    *,
    timezone_name: str | None = None,
    workspace: Any | None = None,
    now: datetime | None = None,
) -> tuple[date, str, str]:
    """Return today's date in the resolved timezone."""

    name, source, zone = resolve_timezone(timezone_name, workspace=workspace)
    if now is None:
        current = datetime.now(zone)
    elif now.tzinfo is None:
        raise InputValidationError(
            f"actual value: {actual_value(now)}; allowed format: timezone-aware "
            "datetime; naive now is rejected so the host zone cannot leak in",
            field="now",
            next_action="Pass a timezone-aware datetime, or omit now.",
        )
    else:
        current = now.astimezone(zone)
    return current.date(), name, source


def parse_date_token(
    value: Any,
    *,
    field: str,
    timezone_name: str | None = None,
    workspace: Any | None = None,
    now: datetime | None = None,
) -> RelativeDateWindow:
    """Parse one token as a single inclusive calendar day or named range."""

    text = _token(value, field)
    today, zone_name, zone_source = calendar_today(
        timezone_name=timezone_name, workspace=workspace, now=now
    )
    if ISO_DATE.fullmatch(text):
        day = _iso_date(text, field)
        return _window(day, day, zone_name, zone_source, text, "iso")
    named = _named_day(text, today)
    if named is not None:
        return _window(named, named, zone_name, zone_source, text, "named_day")
    rolling = _rolling_days(text, today, field)
    if rolling is not None:
        return rolling.with_zone(zone_name, zone_source)
    calendar_range = _named_range(text, today)
    if calendar_range is not None:
        start, end, kind = calendar_range
        return _window(start, end, zone_name, zone_source, text, kind)
    raise InputValidationError(
        f"actual value: {actual_value(text)}; "
        "allowed format: YYYY-MM-DD or a closed relative phrase; "
        "ambiguous windows are not guessed",
        field=field,
        next_action=REMEDY,
    )


def parse_date_window(
    start: Any,
    end: Any,
    *,
    field: str = "start/end",
    timezone_name: str | None = None,
    workspace: Any | None = None,
    now: datetime | None = None,
) -> RelativeDateWindow:
    """Parse a paired start/end that may mix ISO dates and relative phrases.

    A range phrase such as ``last 7 days`` may occupy either side when the
    other side is absent or repeats the same phrase. Mixing two different
    range phrases is rejected.
    """

    start_text = _optional_token(start, "start")
    end_text = _optional_token(end, "end")
    if start_text is None and end_text is None:
        raise InputValidationError(
            f"actual value: {actual_value({'start': start, 'end': end})}; "
            "allowed format: paired ISO dates or a closed relative phrase",
            field=field,
            next_action=REMEDY,
        )
    if start_text is None or end_text is None:
        selected = start_text or end_text or ""
        if ISO_DATE.fullmatch(selected):
            raise InputValidationError(
                f"actual value: {actual_value({'start': start, 'end': end})}; "
                "allowed format: --start and --end together",
                field=field,
                next_action="Supply both ISO dates, or one closed relative phrase.",
            )
        return parse_date_token(
            selected,
            field=field,
            timezone_name=timezone_name,
            workspace=workspace,
            now=now,
        )
    options = {
        "timezone_name": timezone_name,
        "workspace": workspace,
        "now": now,
    }
    if start_text == end_text:
        return parse_date_token(start_text, field=field, **options)
    first = parse_date_token(start_text, field="start", **options)
    last = parse_date_token(end_text, field="end", **options)
    if first.kind not in {"iso", "named_day"} or last.kind not in {
        "iso",
        "named_day",
    }:
        raise InputValidationError(
            f"actual value: {actual_value({'start': start_text, 'end': end_text})}; "
            "allowed format: two ISO/named days, or the same range phrase on both sides",
            field=field,
            next_action=REMEDY,
        )
    if first.start > last.end:
        raise InputValidationError(
            f"actual value: {actual_value({'start': first.start, 'end': last.end})}; "
            "allowed range: start must not follow end",
            field=field,
            next_action="Swap the dates or supply an ordered window, then retry.",
        )
    return RelativeDateWindow(
        start=first.start,
        end=last.end,
        timezone=first.timezone,
        timezone_source=first.timezone_source,
        expression=f"{start_text}..{end_text}",
        kind="paired",
    )


def apply_relative_dates(
    args: Any,
    *,
    workspace: Any | None = None,
    now: datetime | None = None,
) -> RelativeDateWindow | None:
    """Resolve CLI date flags in place. Return the window when any flag changed."""

    timezone_name = getattr(args, "timezone", None)
    if timezone_name is None:
        import os

        timezone_name = os.environ.get("GRAVITY_TIMEZONE") or None
    records: list[RelativeDateWindow] = []
    if _pair_needs_resolution(getattr(args, "start", None), getattr(args, "end", None)):
        window = parse_date_window(
            getattr(args, "start", None),
            getattr(args, "end", None),
            field="start/end",
            timezone_name=timezone_name,
            workspace=workspace,
            now=now,
        )
        args.start = window.start
        args.end = window.end
        records.append(window)
    if _pair_needs_resolution(
        getattr(args, "compare_start", None), getattr(args, "compare_end", None)
    ):
        window = parse_date_window(
            getattr(args, "compare_start", None),
            getattr(args, "compare_end", None),
            field="compare_start/compare_end",
            timezone_name=timezone_name,
            workspace=workspace,
            now=now,
        )
        args.compare_start = window.start
        args.compare_end = window.end
        records.append(window)
    date_value = getattr(args, "date", None)
    if date_value is not None and classify_token(date_value) != "other":
        window = parse_date_token(
            args.date,
            field="date",
            timezone_name=timezone_name,
            workspace=workspace,
            now=now,
        )
        if window.start != window.end:
            raise InputValidationError(
                f"actual value: {actual_value(args.date)}; "
                "allowed format: one ISO day or a single-day relative phrase",
                field="date",
                next_action="Pass a single day such as yesterday or YYYY-MM-DD.",
            )
        args.date = window.start
        records.append(window)
    if not records:
        return None
    selected = records[0]
    args.resolved_date_window = selected.to_dict()
    return selected


def attach_resolved_window(result: Any, window: Any) -> Any:
    """Copy the resolved window onto a mapping result without replacing facts."""

    payload = window.to_dict() if isinstance(window, RelativeDateWindow) else window
    if payload is None or not isinstance(result, dict) or not isinstance(payload, dict):
        return result
    current = result.get("resolved_date_window")
    if current is not None and current != payload:
        return result
    selected = dict(result)
    selected["resolved_date_window"] = payload
    return selected


def extract_relative_expression(query: str) -> str | None:
    """Return one closed relative phrase from a query, or None.

    Ambiguous phrases raise. Two distinct closed phrases raise. A query
    with no closed phrase returns None so the caller keeps placeholders.
    """

    text = str(query or "").strip()
    if not text:
        return None
    compact = "".join(text.split())
    folded = text.casefold()
    for phrase in AMBIGUOUS:
        if phrase_present(folded, compact, phrase):
            raise InputValidationError(
                f"actual value: {actual_value(phrase)}; "
                "allowed format: YYYY-MM-DD or a closed relative phrase; "
                "ambiguous windows are not guessed",
                field="start/end",
                next_action=REMEDY,
            )
    found: list[str] = []
    for phrase in ORDERED_PHRASES:
        if phrase_present(folded, compact, phrase) and not any(
            phrase in item for item in found
        ):
            found.append(phrase)
    rolling = extract_rolling(compact, folded)
    if rolling is not None:
        found.append(rolling)
    unique = list(dict.fromkeys(found))
    if len(unique) != 1:
        return None
    return unique[0]


def _pair_needs_resolution(start: Any, end: Any) -> bool:
    if start is None and end is None:
        return False
    kinds = {classify_token(start), classify_token(end)} - {None}
    return "relative" in kinds


def _workspace_timezone(workspace: Any | None) -> str | None:
    if workspace is None:
        try:
            from .workspace import load_workspace

            workspace = load_workspace()
        except (OSError, ValueError):
            return None
    if getattr(workspace, "path", None) is None:
        return None
    defaults = getattr(workspace, "defaults", None)
    name = getattr(defaults, "timezone", None)
    if not isinstance(name, str) or not name.strip():
        return None
    return name


def _zone(name: str, *, field: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise InputValidationError(
            f"actual value: {actual_value(name)}; allowed format: IANA timezone",
            field=field,
            next_action="Pass a valid IANA name such as Asia/Shanghai, then retry.",
        ) from exc


def _token(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InputValidationError(
            f"actual value: {actual_value(value)}; allowed format: {ISO_DATE_HELP} "
            "or a closed relative phrase",
            field=field,
            next_action=REMEDY,
        )
    return normalize_phrase(value)


def _optional_token(value: Any, field: str) -> str | None:
    if value is None:
        return None
    return _token(value, field)


def _iso_date(value: str, field: str) -> date:
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise InputValidationError(
            f"actual value: {actual_value(value)}; allowed format: {ISO_DATE_HELP}",
            field=field,
            next_action="Pass a canonical YYYY-MM-DD date, then retry.",
        ) from exc
    if parsed.isoformat() != value:
        raise InputValidationError(
            f"actual value: {actual_value(value)}; allowed format: {ISO_DATE_HELP}",
            field=field,
            next_action="Pass a canonical YYYY-MM-DD date, then retry.",
        )
    return parsed


def _named_day(text: str, today: date) -> date | None:
    offset = NAMED_OFFSETS.get(text)
    if offset is None:
        return None
    return today - timedelta(days=offset)


def _named_range(text: str, today: date) -> tuple[date, date, str] | None:
    kind = RANGE_PHRASES.get(text)
    if kind is None:
        return None
    if kind == "this_week":
        start = today - timedelta(days=today.weekday() - WEEK_START)
        return start, start + timedelta(days=6), kind
    if kind == "last_week":
        end = today - timedelta(days=today.weekday() - WEEK_START + 1)
        return end - timedelta(days=6), end, kind
    if kind == "this_month":
        return today.replace(day=1), today, kind
    first = today.replace(day=1)
    end = first - timedelta(days=1)
    return end.replace(day=1), end, kind


def _rolling_days(text: str, today: date, field: str) -> RelativeDateWindow | None:
    matched = match_rolling(text)
    if matched is None:
        return None
    expression, count, kind = matched
    if count < 1 or count > 366:
        raise InputValidationError(
            f"actual value: {actual_value(expression)}; "
            "allowed range: N must be an integer from 1 through 366",
            field=field,
            next_action="Pass last/past N days with 1 <= N <= 366, then retry.",
        )
    start = today - timedelta(days=count - 1)
    return _window(
        start, today, DEFAULT_TIMEZONE, DEFAULT_TIMEZONE_SOURCE, expression, kind
    )


def _window(
    start: date,
    end: date,
    timezone_name: str,
    timezone_source: str,
    expression: str,
    kind: str,
) -> RelativeDateWindow:
    return RelativeDateWindow(
        start=start.isoformat(),
        end=end.isoformat(),
        timezone=timezone_name,
        timezone_source=timezone_source,
        expression=expression,
        kind=kind,
    )


__all__ = [
    "DEFAULT_TIMEZONE",
    "DEFAULT_TIMEZONE_SOURCE",
    "SCHEMA_VERSION",
    "RelativeDateWindow",
    "apply_relative_dates",
    "attach_resolved_window",
    "calendar_today",
    "extract_relative_expression",
    "parse_date_token",
    "parse_date_window",
    "resolve_timezone",
]
