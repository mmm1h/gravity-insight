"""Beijing-time window normalization shared by governed SQL products."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone


BEIJING = timezone(timedelta(hours=8), name="Asia/Shanghai")


def latest_safe_date(now: datetime | None = None) -> date:
    if now is None:
        current = datetime.now(BEIJING)
    elif now.tzinfo is None:
        current = now.replace(tzinfo=BEIJING)
    else:
        current = now.astimezone(BEIJING)
    return current.date() - timedelta(days=2 if current.hour < 2 else 1)


def day_window(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time.min, BEIJING)
    return start, start + timedelta(days=1)


def parse_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"invalid ISO timestamp: {value!r}") from exc
    parsed = (
        parsed.replace(tzinfo=BEIJING)
        if parsed.tzinfo is None
        else parsed.astimezone(BEIJING)
    )
    return parsed.replace(microsecond=0)


def normalize_window(start: str, end: str) -> tuple[datetime, datetime]:
    start_at, end_at = parse_timestamp(start), parse_timestamp(end)
    if start_at >= end_at:
        raise ValueError("start must be earlier than end")
    return start_at, end_at


__all__ = [
    "BEIJING",
    "day_window",
    "latest_safe_date",
    "normalize_window",
    "parse_timestamp",
]
