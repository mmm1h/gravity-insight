"""Beijing-time window normalization shared by governed SQL products."""

from __future__ import annotations

import time as _time
from collections.abc import Mapping, Sequence
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Callable


BEIJING = timezone(timedelta(hours=8), name="Asia/Shanghai")
VERIFICATION_CONCURRENCY = 1
VERIFICATION_MIN_BACKOFF_MS = 1_000
VERIFICATION_MAX_BACKOFF_MS = 30_000


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


def execute_sql_verification(
    owner: Any,
    client: Any,
    day: date,
    *,
    max_workers: int = VERIFICATION_CONCURRENCY,
    workspace: Any,
    resume: Mapping[str, Any] | None = None,
    sleeper: Callable[[float], None] = _time.sleep,
    clock: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    if type(max_workers) is not int or max_workers != VERIFICATION_CONCURRENCY:
        raise ValueError("SQL verification concurrency must be exactly 1")
    start_at, end_at = day_window(day)
    names = owner.product_names(workspace)
    segments, completed, delay_ms = owner.verification_resume_state(
        owner, resume, day, names, workspace, clock
    )
    if delay_ms:
        sleeper(delay_ms / 1_000)
    segment_started = verification_timestamp(clock)
    segment_products: list[str] = []
    for product in names[len(completed) :]:
        try:
            completed[product] = owner.run_product(
                client, product, start_at, end_at, workspace=workspace
            )
            segment_products.append(product)
        except Exception as exc:
            failure = owner.verification_failure(exc)
            rate_limited = owner.verification_failure_is_rate_limited(failure)
            segments.append(
                verification_segment(
                    len(segments) + 1,
                    segment_started,
                    verification_timestamp(clock),
                    segment_products,
                    "rate_limited" if rate_limited else "failed",
                    product,
                )
            )
            return owner.verification_failure_run(
                owner,
                day,
                names,
                completed,
                segments,
                product,
                failure,
                workspace,
                rate_limited=rate_limited,
            )
    segments.append(
        verification_segment(
            len(segments) + 1,
            segment_started,
            verification_timestamp(clock),
            segment_products,
            "complete",
            None,
        )
    )
    history = {
        "mode": "single_run" if len(segments) == 1 else "resumed_after_rate_limit",
        "segment_count": len(segments),
        "segments": segments,
    }
    owner.validate_verification_history(history, names, complete=True)
    return owner.build_evidence(
        day,
        list(completed.values()),
        verification=history,
        workspace=workspace,
    )


def verification_now(clock: Callable[[], datetime] | None = None) -> datetime:
    value = datetime.now(BEIJING) if clock is None else clock()
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ValueError("SQL verification clock must return a timezone-aware datetime")
    return value.astimezone(BEIJING)


def verification_timestamp(clock: Callable[[], datetime] | None = None) -> str:
    return verification_now(clock).isoformat(timespec="microseconds")


def verification_segment(
    sequence: int,
    started_at: str,
    completed_at: str,
    products: Sequence[str],
    status: str,
    failure_product: str | None,
) -> dict[str, Any]:
    return {
        "sequence": sequence,
        "started_at": started_at,
        "completed_at": completed_at,
        "products": list(products),
        "status": status,
        "failure_product": failure_product,
    }


def verification_resume_delay_ms(
    history: Mapping[str, Any],
    failure: Mapping[str, Any],
    clock: Callable[[], datetime] | None,
) -> int:
    failed_at = datetime.fromisoformat(str(history["segments"][-1]["completed_at"]))
    cooldown_ms = min(
        VERIFICATION_MAX_BACKOFF_MS,
        max(VERIFICATION_MIN_BACKOFF_MS, int(failure["retry_after_ms"])),
    )
    elapsed_ms = max(
        0, int((verification_now(clock) - failed_at).total_seconds() * 1_000)
    )
    return max(0, cooldown_ms - elapsed_ms)


__all__ = [
    "BEIJING",
    "VERIFICATION_CONCURRENCY",
    "VERIFICATION_MAX_BACKOFF_MS",
    "VERIFICATION_MIN_BACKOFF_MS",
    "day_window",
    "execute_sql_verification",
    "latest_safe_date",
    "normalize_window",
    "parse_timestamp",
    "verification_now",
    "verification_resume_delay_ms",
    "verification_segment",
    "verification_timestamp",
]
