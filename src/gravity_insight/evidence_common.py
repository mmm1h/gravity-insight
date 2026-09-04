"""Shared value-free helpers for repository evidence collectors."""

from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence


CONTEXT_BOUND_MEASUREMENT_VERSION = "gravity.context-bound-measurement.v1"
MEASUREMENT_RESOLUTION_VERSION = "gravity.measurement-resolution.v1"
MEASUREMENT_STATUSES = frozenset(
    {"measured", "not_measured", "expired", "not_applicable", "invalid"}
)


@dataclass(frozen=True)
class _MeasurementResolution:
    schema_version: str
    status: str
    reason_code: str | None
    value: Any
    context: dict[str, Any] | None
    expected_context: dict[str, Any]
    mismatches: list[dict[str, Any]]
    freshness: dict[str, Any] | None


def load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.as_posix()} must contain a JSON object")
    return value


def relative(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def git_state(root: Path) -> dict[str, Any]:
    def run(*args: str) -> str:
        completed = subprocess.run(
            ("git", *args),
            cwd=root,
            check=True,
            capture_output=True,
        )
        return completed.stdout.decode("utf-8").strip()

    return {
        "commit": run("rev-parse", "HEAD"),
        "branch": run("branch", "--show-current"),
        "dirty": bool(run("status", "--porcelain")),
    }


def context_bound_measurement(
    value: Any,
    *,
    coordinate: Mapping[str, Any],
    scope: Mapping[str, Any],
    captured_at: datetime | str,
    binds_to: Mapping[str, Any],
) -> dict[str, Any]:
    """Attach the context that determines what a captured value means."""
    return {
        "schema_version": CONTEXT_BOUND_MEASUREMENT_VERSION,
        "value": value,
        "coordinate": _context_object(coordinate, "coordinate"),
        "scope": _context_object(scope, "scope"),
        "captured_at": _timestamp(captured_at).isoformat(),
        "binds_to": _context_object(binds_to, "binds_to"),
    }


def resolve_context_bound_measurement(
    measurement: Mapping[str, Any] | None,
    *,
    expected_coordinate: Mapping[str, Any],
    expected_scope: Mapping[str, Any],
    expected_bindings: Mapping[str, Any],
    now: datetime | None = None,
    max_age: timedelta | None = None,
    future_skew: timedelta = timedelta(0),
) -> dict[str, Any]:
    """Resolve one value against an explicit consumer context."""
    expected = {
        "coordinate": _context_object(expected_coordinate, "expected_coordinate"),
        "scope": _context_object(expected_scope, "expected_scope"),
        "binds_to": _context_object(expected_bindings, "expected_bindings"),
    }
    if measurement is None:
        return _measurement_resolution(
            "not_measured", "MEASUREMENT_NOT_CAPTURED", expected=expected
        )
    try:
        context = _measurement_context(measurement)
    except (TypeError, ValueError):
        return _measurement_resolution(
            "invalid", "MEASUREMENT_CONTEXT_INVALID", expected=expected
        )
    mismatches = _context_mismatches(context, expected)
    if mismatches:
        return _measurement_resolution(
            "not_applicable",
            "MEASUREMENT_CONTEXT_MISMATCH",
            context=context,
            expected=expected,
            mismatches=mismatches,
        )
    freshness = _measurement_freshness(
        context["captured_at"], now=now, max_age=max_age, future_skew=future_skew
    )
    if freshness and freshness["status"] != "current":
        reason = (
            "MEASUREMENT_EXPIRED"
            if freshness["status"] == "expired"
            else "MEASUREMENT_CAPTURED_IN_FUTURE"
        )
        status = "expired" if freshness["status"] == "expired" else "invalid"
        return _measurement_resolution(
            status,
            reason,
            context=context,
            expected=expected,
            freshness=freshness,
        )
    return _measurement_resolution(
        "measured",
        None,
        value=measurement.get("value"),
        context=context,
        expected=expected,
        freshness=freshness,
    )


def _context_object(value: Mapping[str, Any], label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or not value:
        raise ValueError(f"{label} must be a non-empty object")
    if any(not isinstance(key, str) or not key for key in value):
        raise ValueError(f"{label} keys must be non-empty strings")
    return dict(value)


def _timestamp(value: datetime | str) -> datetime:
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("captured_at must be an ISO-8601 timestamp") from exc
    elif isinstance(value, datetime):
        parsed = value
    else:
        raise TypeError("captured_at must be a datetime or ISO-8601 string")
    if parsed.tzinfo is None:
        raise ValueError("captured_at must include a timezone")
    return parsed.astimezone(timezone.utc)


def _measurement_context(measurement: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "schema_version",
        "value",
        "coordinate",
        "scope",
        "captured_at",
        "binds_to",
    }
    if not isinstance(measurement, Mapping) or set(measurement) != required:
        raise ValueError("context-bound measurement has unsupported fields")
    if measurement.get("schema_version") != CONTEXT_BOUND_MEASUREMENT_VERSION:
        raise ValueError("unsupported context-bound measurement schema")
    return {
        "coordinate": _context_object(measurement.get("coordinate"), "coordinate"),
        "scope": _context_object(measurement.get("scope"), "scope"),
        "captured_at": _timestamp(measurement.get("captured_at")).isoformat(),
        "binds_to": _context_object(measurement.get("binds_to"), "binds_to"),
    }


def _context_mismatches(
    context: Mapping[str, Any], expected: Mapping[str, Mapping[str, Any]]
) -> list[dict[str, Any]]:
    result = []
    for section in ("coordinate", "scope", "binds_to"):
        observed = context[section]
        expected_section = expected[section]
        for key in sorted(set(observed) | set(expected_section)):
            expected_value = expected_section.get(key)
            observed_value = observed.get(key)
            if (
                (key in observed) != (key in expected_section)
                or observed_value != expected_value
            ):
                result.append(
                    {
                        "field": f"{section}.{key}",
                        "expected": expected_value,
                        "observed": observed_value,
                    }
                )
    return result


def _measurement_freshness(
    captured_at: str,
    *,
    now: datetime | None,
    max_age: timedelta | None,
    future_skew: timedelta,
) -> dict[str, Any] | None:
    if max_age is None:
        return None
    if max_age < timedelta(0) or future_skew < timedelta(0):
        raise ValueError("freshness durations must not be negative")
    if now is None or now.tzinfo is None:
        raise ValueError("freshness resolution requires a timezone-aware now")
    age = (now.astimezone(timezone.utc) - _timestamp(captured_at)).total_seconds()
    status = (
        "future"
        if age < -future_skew.total_seconds()
        else "expired" if age > max_age.total_seconds() else "current"
    )
    return {
        "status": status,
        "observed_at": captured_at,
        "age_seconds": round(age, 3),
        "max_age_seconds": int(max_age.total_seconds()),
        "future_clock_skew_seconds": int(future_skew.total_seconds()),
    }


def _measurement_resolution(
    status: str,
    reason_code: str | None,
    *,
    value: Any = None,
    context: Mapping[str, Any] | None = None,
    expected: Mapping[str, Any],
    mismatches: Sequence[Mapping[str, Any]] = (),
    freshness: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if status not in MEASUREMENT_STATUSES:
        raise ValueError(f"unsupported measurement status: {status}")
    return asdict(
        _MeasurementResolution(
            schema_version=MEASUREMENT_RESOLUTION_VERSION,
            status=status,
            reason_code=reason_code,
            value=value if status == "measured" else None,
            context=dict(context) if context is not None else None,
            expected_context=dict(expected),
            mismatches=[dict(item) for item in mismatches],
            freshness=dict(freshness) if freshness is not None else None,
        )
    )


def metric(
    *,
    source: str,
    claim: str,
    measured: bool,
    passed: int | None = None,
    total: int | None = None,
    observed: Any = None,
    proxy_metric: bool = False,
    limitation: str | None = None,
    missing: Sequence[str] = (),
    measurement_resolution: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if measurement_resolution is not None:
        measurement_status = measurement_resolution.get("status")
        if measurement_status not in MEASUREMENT_STATUSES:
            raise ValueError("metric measurement resolution has an invalid status")
        if measured != (measurement_status == "measured"):
            raise ValueError("metric measured flag conflicts with measurement resolution")
    if measured:
        if type(passed) is not int or type(total) is not int or total <= 0:
            raise ValueError("measured score metrics require integer passed/total")
        if passed < 0 or passed > total:
            raise ValueError("score metric passed count is outside its denominator")
    else:
        passed = None
        total = None
    result = {
        "source": source,
        "claim": claim,
        "measured": measured,
        "passed": passed,
        "total": total,
        "observed": observed,
        "proxy_metric": proxy_metric,
        "limitation": limitation,
        "missing": list(missing),
    }
    if measurement_resolution is not None:
        result["measurement"] = dict(measurement_resolution)
    return result


def dimension(
    *,
    dimension_id: str,
    name: str,
    maximum: int,
    evidence: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    required = [item for item in evidence if item.get("required", True)]
    measured, passed, total = _dimension_counts(required)
    score = round(maximum * passed / total, 2) if measured else None
    missing = _dimension_missing(required)
    return {
        "id": dimension_id,
        "name": name,
        "score": score,
        "max": maximum,
        "measured": measured,
        "status": _dimension_status(required, measured=measured),
        "evidence": [dict(item) for item in evidence],
        "missing": missing,
        "calculation": (
            {"passed": passed, "total": total, "formula": "max * passed / total"}
            if measured
            else None
        ),
    }


def _dimension_counts(
    required: Sequence[Mapping[str, Any]],
) -> tuple[bool, int | None, int | None]:
    if not required or any(item.get("measured") is not True for item in required):
        return False, None, None
    passed = sum(int(item["passed"]) for item in required)
    total = sum(int(item["total"]) for item in required)
    return (True, passed, total) if total > 0 else (False, None, None)


def _dimension_missing(required: Sequence[Mapping[str, Any]]) -> list[str]:
    return sorted(
        {
            str(value)
            for item in required
            if item.get("measured") is not True
            for value in item.get("missing", ())
        }
    )


def _dimension_status(
    required: Sequence[Mapping[str, Any]], *, measured: bool
) -> str:
    if measured:
        return "measured"
    statuses = {
        item.get("measurement", {}).get("status", "not_measured")
        if isinstance(item.get("measurement"), Mapping)
        else "not_measured"
        for item in required
        if item.get("measured") is not True
    }
    for status in ("invalid", "not_applicable", "expired", "not_measured"):
        if status in statuses:
            return status
    return "not_measured"


__all__ = [
    "CONTEXT_BOUND_MEASUREMENT_VERSION",
    "MEASUREMENT_RESOLUTION_VERSION",
    "MEASUREMENT_STATUSES",
    "context_bound_measurement",
    "dimension",
    "git_state",
    "load_object",
    "metric",
    "relative",
    "resolve_context_bound_measurement",
]
