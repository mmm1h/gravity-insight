"""Timing and bounded-result support shared by governed SQL products."""

from __future__ import annotations

import time as _time
from collections.abc import Mapping, Sequence
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Callable


BEIJING = timezone(timedelta(hours=8), name="Asia/Shanghai")
VERIFICATION_CONCURRENCY = 1
VERIFICATION_MIN_BACKOFF_MS = 1_000
VERIFICATION_MAX_BACKOFF_MS = 30_000
POSSIBLE_TRUNCATION_WARNING = (
    "POSSIBLE_TRUNCATION: returned rows reached max_rows while the total row count "
    "is unknown"
)
_SIGNAL_RULES = {
    "below_row_cap": ("complete", False, False, False),
    "possible_truncation": ("unknown", True, False, True),
    "total_row_count_match": ("complete", None, True, False),
}


class EvidenceFormatError(ValueError):
    pass


def summarize_custom(
    rows: list[dict[str, Any]],
    app_ids: tuple[int, ...],
    start_at: datetime,
    end_at: datetime,
    *,
    output_fields: list[str],
    max_rows: int,
    measurement: str,
    total_row_count: int | None = None,
) -> tuple[dict[str, Any], str, list[str], list[str]]:
    summary, status, warnings, notes, _signal = summarize_custom_result(
        rows,
        app_ids,
        start_at,
        end_at,
        output_fields=output_fields,
        max_rows=max_rows,
        measurement=measurement,
        total_row_count=total_row_count,
    )
    return summary, status, warnings, notes


def summarize_custom_result(
    rows: list[dict[str, Any]],
    app_ids: tuple[int, ...],
    _start_at: datetime,
    _end_at: datetime,
    *,
    output_fields: list[str],
    max_rows: int,
    measurement: str,
    total_row_count: int | None = None,
) -> tuple[dict[str, Any], str, list[str], list[str], dict[str, Any]]:
    row_count = len(rows)
    _validate_summary_counts(row_count, max_rows, total_row_count)
    projected = _project_rows(rows, output_fields)
    signal, warnings = _classify_rows(row_count, max_rows, total_row_count)
    summary = {
        "rows": projected,
        "row_count": row_count,
        "max_rows": max_rows,
        "total_row_count": total_row_count,
        "app_ids": list(app_ids),
        "measurement": measurement,
    }
    return summary, "complete", warnings, [], signal


def validate_product_completeness(
    product: str,
    result: Mapping[str, Any],
    *,
    require_completeness: bool,
) -> None:
    signal = _validated_signal_fields(product, result, require_completeness)
    if signal is None:
        return
    row_count, max_rows, total_row_count = _validated_result_counts(product, result)
    row_cap_reached = result["row_cap_reached"]
    if type(row_cap_reached) is not bool or row_cap_reached != (row_count == max_rows):
        raise EvidenceFormatError(f"invalid product row-cap signal: {product}")
    _validate_signal_rule(product, result, total_row_count)


def _validate_summary_counts(
    row_count: int, max_rows: int, total_row_count: int | None
) -> None:
    if row_count > max_rows:
        raise EvidenceFormatError(f"custom SQL product exceeded max_rows={max_rows}")
    if total_row_count is not None and not _nonnegative_int(total_row_count):
        raise EvidenceFormatError("custom SQL product total_row_count is invalid")
    if total_row_count is not None and total_row_count > max_rows:
        raise EvidenceFormatError(f"custom SQL product exceeded max_rows={max_rows}")
    if total_row_count is not None and total_row_count != row_count:
        raise EvidenceFormatError("custom SQL product total_row_count differs from rows")


def _project_rows(
    rows: list[dict[str, Any]], output_fields: list[str]
) -> list[dict[str, Any]]:
    projected: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise EvidenceFormatError("custom SQL product returned a non-object row")
        projected.append({field: row.get(field) for field in output_fields})
    return projected


def _classify_rows(
    row_count: int, max_rows: int, total_row_count: int | None
) -> tuple[dict[str, Any], list[str]]:
    row_cap_reached = row_count == max_rows
    if total_row_count is not None:
        completeness, reason, warnings = "complete", "total_row_count_match", []
    elif row_cap_reached:
        completeness = "unknown"
        reason = "possible_truncation"
        warnings = [POSSIBLE_TRUNCATION_WARNING]
    else:
        completeness, reason, warnings = "complete", "below_row_cap", []
    return {
        "row_cap_reached": row_cap_reached,
        "completeness": completeness,
        "completeness_reason": reason,
    }, warnings


def _validated_signal_fields(
    product: str, result: Mapping[str, Any], require_completeness: bool
) -> bool | None:
    fields = {"row_cap_reached", "completeness", "completeness_reason"}
    summary_fields = {"max_rows", "total_row_count"}
    present = fields & set(result)
    summary_present = summary_fields & set(result["summary"])
    if not present and not summary_present and not require_completeness:
        return None
    if present != fields or summary_present != summary_fields:
        raise EvidenceFormatError(f"incomplete product completeness signal: {product}")
    return True


def _validated_result_counts(
    product: str, result: Mapping[str, Any]
) -> tuple[int, int, int | None]:
    summary = result["summary"]
    row_count = summary.get("row_count")
    max_rows = summary.get("max_rows")
    total_row_count = summary.get("total_row_count")
    valid = _nonnegative_int(row_count) and _bounded_max_rows(max_rows)
    valid = valid and row_count <= max_rows
    valid = valid and (
        total_row_count is None
        or (_nonnegative_int(total_row_count) and total_row_count == row_count)
    )
    if not valid:
        raise EvidenceFormatError(f"invalid product row-cap signal: {product}")
    return row_count, max_rows, total_row_count


def _validate_signal_rule(
    product: str, result: Mapping[str, Any], total_row_count: int | None
) -> None:
    rule = _SIGNAL_RULES.get(result["completeness_reason"])
    if rule is None:
        raise EvidenceFormatError(f"invalid product completeness signal: {product}")
    expected_completeness, expected_cap, expected_total, expected_warning = rule
    warnings = result.get("warnings")
    has_warning = isinstance(warnings, list) and POSSIBLE_TRUNCATION_WARNING in warnings
    valid = result["completeness"] == expected_completeness
    valid = valid and (total_row_count is not None) == expected_total
    valid = valid and has_warning == expected_warning
    if expected_cap is not None:
        valid = valid and result["row_cap_reached"] is expected_cap
    if not valid:
        raise EvidenceFormatError(f"invalid product completeness signal: {product}")


def _nonnegative_int(value: Any) -> bool:
    return type(value) is int and value >= 0


def _bounded_max_rows(value: Any) -> bool:
    return type(value) is int and 1 <= value <= 10_000


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
        counted = _CountedVerificationClient(client)
        product_started = _time.monotonic()
        try:
            completed[product] = owner.run_product(
                counted, product, start_at, end_at, workspace=workspace
            )
            segment_products.append(product)
        except Exception as exc:
            failure = _timed_verification_failure(
                owner, exc, counted, product_started
            )
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


class _CountedVerificationClient:
    """Count logical SQL calls without exposing or retaining their statements."""

    def __init__(self, client: Any) -> None:
        self._client = client
        self.request_count = 0

    def execute_sql(self, sql: str) -> list[dict[str, Any]]:
        self.request_count += 1
        return self._client.execute_sql(sql)


def _timed_verification_failure(
    owner: Any,
    error: BaseException,
    client: _CountedVerificationClient,
    started: float,
) -> dict[str, Any]:
    return owner.verification_failure(
        error,
        elapsed_seconds=_time.monotonic() - started,
        request_count=client.request_count,
        request_count_bound=1,
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
    "EvidenceFormatError",
    "POSSIBLE_TRUNCATION_WARNING",
    "VERIFICATION_CONCURRENCY",
    "VERIFICATION_MAX_BACKOFF_MS",
    "VERIFICATION_MIN_BACKOFF_MS",
    "day_window",
    "execute_sql_verification",
    "latest_safe_date",
    "normalize_window",
    "parse_timestamp",
    "summarize_custom",
    "summarize_custom_result",
    "validate_product_completeness",
    "verification_now",
    "verification_resume_delay_ms",
    "verification_segment",
    "verification_timestamp",
]
