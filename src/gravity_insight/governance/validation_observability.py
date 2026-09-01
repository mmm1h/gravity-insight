"""Value-free validation-cost and development-experience observations."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
from statistics import median
from typing import Any, Callable, Mapping, Sequence


SCHEMA_VERSION = "gravity.validation-experience-observation.v1"
BASELINE_SCHEMA_VERSION = "gravity.validation-experience-baselines.v1"
METRIC_NAMES = (
    "bootstrap_tokens",
    "task_context_tokens",
    "files_read_before_first_edit",
    "time_to_first_reproduction",
    "time_to_first_useful_edit",
    "focused_gate_seconds",
    "full_gate_seconds",
    "review_iterations",
    "context_resets",
    "archive_tokens_loaded",
    "active_docs_tokens",
)
TRACE_METRICS = {
    "files_read_before_first_edit": "ordered read/edit events from the agent tool trace",
    "time_to_first_reproduction": "session start and first successful reproduction events",
    "time_to_first_useful_edit": "session start and owner-confirmed useful-edit event",
    "review_iterations": "review-result events grouped by the same task run",
    "context_resets": "context compaction/reset events from the host session trace",
}
TREND_METRICS = (
    "bootstrap_tokens",
    "task_context_tokens",
    "archive_tokens_loaded",
    "active_docs_tokens",
    "files_read_before_first_edit",
    "time_to_first_reproduction",
    "time_to_first_useful_edit",
    "focused_gate_seconds",
)


class ValidationObservationError(ValueError):
    """Raised when an observation or baseline receipt is malformed."""


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _measured(value: int | float, unit: str, method: str) -> dict[str, Any]:
    return {"status": "measured", "value": value, "unit": unit, "method": method}


def _unmeasured(unit: str, missing_source: str) -> dict[str, Any]:
    return {
        "status": "unmeasured",
        "value": None,
        "unit": unit,
        "missing_source": missing_source,
    }


def _parse_time(raw: Any, field: str) -> datetime:
    if not isinstance(raw, str):
        raise ValidationObservationError(f"trace {field} must be an ISO-8601 string")
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValidationObservationError(f"trace {field} is not ISO-8601") from exc
    if parsed.tzinfo is None:
        raise ValidationObservationError(f"trace {field} must include a timezone")
    return parsed


def _parsed_trace(
    trace: Mapping[str, Any]
) -> tuple[datetime, list[tuple[datetime, str, str | None]]]:
    started = _parse_time(trace.get("session_started_at"), "session_started_at")
    events = trace.get("events")
    if not isinstance(events, list):
        raise ValidationObservationError("trace events must be an array")
    parsed: list[tuple[datetime, str, str | None]] = []
    for index, event in enumerate(events):
        if not isinstance(event, Mapping) or not isinstance(event.get("type"), str):
            raise ValidationObservationError(f"trace event {index} is invalid")
        parsed.append(
            (
                _parse_time(event.get("at"), f"events[{index}].at"),
                str(event["type"]),
                str(event["path"]) if isinstance(event.get("path"), str) else None,
            )
        )
    parsed.sort(key=lambda item: item[0])
    return started, parsed


def _elapsed_trace_metric(
    parsed: Sequence[tuple[datetime, str, str | None]],
    started: datetime,
    event_type: str,
) -> dict[str, Any]:
    matching = [item[0] for item in parsed if item[1] == event_type]
    if not matching:
        return _unmeasured("seconds", f"trace has no {event_type} event")
    return _measured(
        round((matching[0] - started).total_seconds(), 3),
        "seconds",
        f"first {event_type} event minus session_started_at",
    )


def _unmeasured_trace_metrics() -> dict[str, dict[str, Any]]:
    units = {
        "files_read_before_first_edit": "files",
        "time_to_first_reproduction": "seconds",
        "time_to_first_useful_edit": "seconds",
        "review_iterations": "iterations",
        "context_resets": "resets",
    }
    return {
        name: _unmeasured(units[name], source)
        for name, source in TRACE_METRICS.items()
    }


def _files_before_first_edit(
    parsed: Sequence[tuple[datetime, str, str | None]],
) -> dict[str, Any]:
    first_edits = [item for item in parsed if item[1] == "edit"]
    if not first_edits:
        return _unmeasured("files", "trace has no edit event")
    first_edit_at = first_edits[0][0]
    read_paths = {
        item[2]
        for item in parsed
        if item[1] == "read" and item[2] and item[0] < first_edit_at
    }
    return _measured(
        len(read_paths),
        "files",
        "unique read paths strictly before the first edit event",
    )


def _trace_metrics(trace: Mapping[str, Any] | None) -> dict[str, dict[str, Any]]:
    if trace is None:
        return _unmeasured_trace_metrics()
    started, parsed = _parsed_trace(trace)

    return {
        "files_read_before_first_edit": _files_before_first_edit(parsed),
        "time_to_first_reproduction": _elapsed_trace_metric(
            parsed, started, "reproduction"
        ),
        "time_to_first_useful_edit": _elapsed_trace_metric(
            parsed, started, "useful_edit"
        ),
        "review_iterations": _measured(
            sum(1 for item in parsed if item[1] == "review_result"),
            "iterations",
            "count of review_result events",
        ),
        "context_resets": _measured(
            sum(1 for item in parsed if item[1] == "context_reset"),
            "resets",
            "count of context_reset events",
        ),
    }


def _gate_metric(
    gate_receipts: Mapping[str, Mapping[str, Any]], gate: str
) -> dict[str, Any]:
    receipt = gate_receipts.get(gate)
    if receipt is None:
        return _unmeasured(
            "seconds", f"run the {gate} gate through validation_observability.py"
        )
    if receipt.get("ablated_commands"):
        return _unmeasured("seconds", f"{gate} receipt is an ablation, not a complete gate")
    if receipt.get("status") != "passed" or not isinstance(
        receipt.get("total_seconds"), (int, float)
    ):
        return _unmeasured("seconds", f"{gate} gate has no passing complete receipt")
    return _measured(
        float(receipt["total_seconds"]),
        "seconds",
        "sum of perf_counter durations for every selected gate command",
    )


def _reference_token_totals(
    references: Sequence[Any],
) -> tuple[int, int]:
    archive_tokens = 0
    active_docs_tokens = 0
    for item in references:
        if not isinstance(item, Mapping):
            continue
        path = PurePosixPath(str(item.get("path", "")).replace("\\", "/")).as_posix()
        tokens = int(item["estimated_tokens"])
        if path.startswith(("docs/archive/", "archive/", "history/")):
            archive_tokens += tokens
        elif path.startswith("docs/"):
            active_docs_tokens += tokens
    return archive_tokens, active_docs_tokens


def build_observation(
    task_context: Mapping[str, Any],
    *,
    root: Path,
    token_estimator: Callable[[bytes | str], int],
    gate_receipts: Mapping[str, Mapping[str, Any]] | None = None,
    trace: Mapping[str, Any] | None = None,
    revision: str,
    captured_at: str | None = None,
) -> dict[str, Any]:
    """Build one metric receipt without inventing unavailable interaction data."""

    references = task_context.get("minimal_references")
    if not isinstance(references, list):
        raise ValidationObservationError("task context has no minimal_references array")
    bootstrap_files = ["AGENTS.md"]
    bootstrap_tokens = sum(token_estimator((root / path).read_bytes()) for path in bootstrap_files)
    archive_tokens, active_docs_tokens = _reference_token_totals(references)
    metrics: dict[str, dict[str, Any]] = {
        "bootstrap_tokens": _measured(
            bootstrap_tokens,
            "tokens",
            "mixed CJK/code estimator over repository-visible bootstrap files",
        ),
        "task_context_tokens": _measured(
            int(task_context["size_comparison"]["pack_estimated_tokens"]),
            "tokens",
            "sum of estimated_tokens for minimal task-context references",
        ),
        "archive_tokens_loaded": _measured(
            archive_tokens,
            "tokens",
            "sum of task-context references under configured archive prefixes",
        ),
        "active_docs_tokens": _measured(
            active_docs_tokens,
            "tokens",
            "sum of non-archive docs references in the task-context pack",
        ),
        "focused_gate_seconds": _gate_metric(gate_receipts or {}, "focused"),
        "full_gate_seconds": _gate_metric(gate_receipts or {}, "full"),
        **_trace_metrics(trace),
    }
    if set(metrics) != set(METRIC_NAMES):
        raise ValidationObservationError("observation metric inventory drifted")
    timestamp = captured_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    selected_input = task_context.get("input", {})
    body = {
        "schema_version": SCHEMA_VERSION,
        "revision": revision,
        "captured_at": timestamp,
        "task": selected_input,
        "task_sha256": hashlib.sha256(canonical_bytes(selected_input)).hexdigest(),
        "risk_level": task_context.get("risk_assessment", {}).get("level"),
        "bootstrap_files": bootstrap_files,
        "metrics": {name: metrics[name] for name in METRIC_NAMES},
        "gate_receipts": dict(gate_receipts or {}),
    }
    body["receipt_sha256"] = hashlib.sha256(canonical_bytes(body)).hexdigest()
    return body


def validate_observation(value: Mapping[str, Any]) -> None:
    if value.get("schema_version") != SCHEMA_VERSION:
        raise ValidationObservationError("observation schema_version is invalid")
    metrics = value.get("metrics")
    if not isinstance(metrics, Mapping) or set(metrics) != set(METRIC_NAMES):
        raise ValidationObservationError("observation metrics are incomplete")
    expected = value.get("receipt_sha256")
    body = dict(value)
    body.pop("receipt_sha256", None)
    actual = hashlib.sha256(canonical_bytes(body)).hexdigest()
    if expected != actual:
        raise ValidationObservationError("observation receipt digest is invalid")


def read_baselines(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schema_version": BASELINE_SCHEMA_VERSION, "observations": []}
    parsed = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(parsed, dict) or parsed.get("schema_version") != BASELINE_SCHEMA_VERSION:
        raise ValidationObservationError("baseline archive schema is invalid")
    observations = parsed.get("observations")
    if not isinstance(observations, list):
        raise ValidationObservationError("baseline observations must be an array")
    for observation in observations:
        if not isinstance(observation, Mapping):
            raise ValidationObservationError("baseline observation is not an object")
        validate_observation(observation)
    return parsed


def append_baseline(path: Path, observation: Mapping[str, Any]) -> dict[str, Any]:
    """Atomically append one digest-bound receipt; never accept hand-entered metrics."""

    validate_observation(observation)
    document = read_baselines(path)
    observations = list(document["observations"])
    digest = observation["receipt_sha256"]
    if not any(item["receipt_sha256"] == digest for item in observations):
        observations.append(dict(observation))
    observations.sort(key=lambda item: (item["captured_at"], item["receipt_sha256"]))
    updated = {"schema_version": BASELINE_SCHEMA_VERSION, "observations": observations}
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(json.dumps(updated, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n")
    temporary.replace(path)
    return updated


def trend_summary(observations: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Flag only three consecutive revision medians that strictly increase."""

    by_revision: dict[str, dict[str, list[float]]] = defaultdict(
        lambda: defaultdict(list)
    )
    revision_order: dict[str, str] = {}
    for observation in observations:
        validate_observation(observation)
        revision = str(observation["revision"])
        revision_order[revision] = max(
            revision_order.get(revision, ""), str(observation["captured_at"])
        )
        for name in TREND_METRICS:
            metric = observation["metrics"][name]
            if metric.get("status") == "measured" and isinstance(
                metric.get("value"), (int, float)
            ):
                by_revision[revision][name].append(float(metric["value"]))
    ordered = sorted(revision_order, key=revision_order.__getitem__)
    result: dict[str, Any] = {}
    for name in TREND_METRICS:
        series = [
            {"revision": revision, "median": median(by_revision[revision][name])}
            for revision in ordered
            if by_revision[revision][name]
        ]
        recent = series[-3:]
        status = "insufficient_history"
        if len(recent) == 3:
            values = [item["median"] for item in recent]
            status = (
                "sustained_increase"
                if values[0] < values[1] < values[2]
                else "within_policy"
            )
        result[name] = {"status": status, "recent_revision_medians": recent}
    return result


__all__ = [
    "BASELINE_SCHEMA_VERSION",
    "METRIC_NAMES",
    "SCHEMA_VERSION",
    "TREND_METRICS",
    "ValidationObservationError",
    "append_baseline",
    "build_observation",
    "canonical_bytes",
    "read_baselines",
    "trend_summary",
    "validate_observation",
]
