"""Compare one governed Analysis spec across exactly two explicit periods."""

from __future__ import annotations

import copy
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .analysis_interpretation import attach_analysis_interpretation
from .analysis_spec import compile_query_spec, validate_query_spec
from .errors import InputValidationError
from .result_source import GOVERNED_PRODUCT, result_source
from .actionable_error_values import actual_value


SCHEMA_VERSION = "gravity-insight.analysis-period-compare.v1"
_SUCCESS = frozenset({"success", "empty"})
_DATA_KEYS = {
    "event": frozenset({"list", "target_list", "default_limit", "date_list"}),
    "funnel": frozenset(
        {"date_list", "aggregate_by_date", "aggregate_date", "window_funnel_mode"}
    ),
    "retention": frozenset({"total", "x", "y", "date_to_week", "date_to_month"}),
    "scatter": frozenset({"aggregate_date", "zone_tags"}),
}
_METRIC_ROOTS = {
    "funnel": ("aggregate_by_date", "aggregate_date"),
    "retention": ("total",),
    "scatter": ("aggregate_date",),
}
_DATE_KEY = re.compile(r"^\d{4}-\d{2}(?:-\d{2})?(?:[T ].*)?$")


@dataclass(frozen=True)
class _Metric:
    field: str
    aggregation: str
    event_index: int | None

    @property
    def identity(self) -> str:
        return f"{self.field}:{self.aggregation}"


def compare_analysis_periods(
    client: Any,
    kind: str,
    spec: Mapping[str, Any],
    *,
    baseline_start: str,
    baseline_end: str,
    current_start: str | None = None,
    current_end: str | None = None,
    workspace: Any | None = None,
    app: str | int | None = None,
    max_workers: int = 2,
) -> dict[str, Any]:
    """Run the same literal spec for a baseline and current period."""

    _workers(max_workers)
    selected_kind = str(kind or "").strip().casefold()
    if selected_kind == "property":
        return _capability_gap(
            selected_kind,
            "property Analysis has no governed date-window input",
            network_called=False,
        )
    options = {"workspace": workspace, "app": app}
    current = compile_query_spec(
        selected_kind, spec, start=current_start, end=current_end, **options
    )
    baseline = compile_query_spec(
        selected_kind, spec, start=baseline_start, end=baseline_end, **options
    )
    _same_spec(current.inputs, baseline.inputs)
    current, _ = validate_query_spec(
        client, selected_kind, spec, start=current_start, end=current_end, **options
    )
    baseline, _ = validate_query_spec(
        client, selected_kind, spec, start=baseline_start, end=baseline_end, **options
    )
    requests = [_request("baseline", baseline), _request("current", current)]
    results = client.batch(requests, max_workers=max_workers, max_pages=1)
    ordered = _ordered(results)
    windows = {
        "baseline": _window(
            ordered["baseline"], baseline_start, baseline_end, baseline.operation_id
        ),
        "current": _window(
            ordered["current"],
            current.inputs["date_list"][0]["start_date"],
            current.inputs["date_list"][0]["end_date"],
            current.operation_id,
        ),
    }
    return attach_analysis_interpretation(
        _envelope(selected_kind, baseline.inputs, windows),
        selected_kind,
        spec,
    )


def _request(request_id: str, compiled: Any) -> dict[str, Any]:
    return {
        "operation_id": compiled.operation_id,
        "request_id": request_id,
        "inputs": compiled.inputs,
    }


def _envelope(
    kind: str, inputs: Mapping[str, Any], windows: Mapping[str, Mapping[str, Any]]
) -> dict[str, Any]:
    statuses = [windows[name]["status"] for name in ("baseline", "current")]
    failed = [status for status in statuses if status not in _SUCCESS]
    empty = [status for status in statuses if status == "empty"]
    if failed:
        status = "error" if len(failed) == 2 else "partial"
        delta = _delta_unavailable("window_failed")
    elif empty:
        status = "empty" if len(empty) == 2 else "partial"
        reason = "baseline_empty" if statuses[0] == "empty" else "current_empty"
        delta = _delta_unavailable(reason)
    else:
        try:
            delta = _delta(kind, inputs, windows)
            status = "success"
        except _CapabilityGap as exc:
            status = "capability_gap"
            delta = _delta_unavailable("capability_gap", detail=str(exc))
    ok = status in {"success", "empty"}
    return {
        "schema_version": SCHEMA_VERSION,
        "result_source": result_source(GOVERNED_PRODUCT),
        "ok": ok,
        "status": status,
        "kind": kind,
        "operation_id": windows["current"]["operation_id"],
        "network_called": True,
        "windows": dict(windows),
        "delta": delta,
        "next_action": (
            "Consume the two governed windows and registered metric deltas."
            if status == "success"
            else "Inspect window and delta status; do not infer a missing delta as zero."
        ),
    }


def _delta(
    kind: str, inputs: Mapping[str, Any], windows: Mapping[str, Mapping[str, Any]]
) -> dict[str, Any]:
    baseline = _metric_values(kind, inputs, windows["baseline"]["result"])
    current = _metric_values(kind, inputs, windows["current"]["result"])
    if set(baseline) != set(current):
        raise _CapabilityGap("the two windows do not expose the same metric paths")
    items = []
    for key in sorted(baseline):
        before, after = baseline[key], current[key]
        absolute = after[0] - before[0]
        relative = (
            {"status": "not_calculable", "reason": "baseline_zero"}
            if before[0] == 0
            else {"status": "calculated", "percent": absolute / before[0] * 100}
        )
        items.append(
            {
                "metric": {"field": key[0], "aggregation": key[1]},
                "baseline_path": before[1],
                "current_path": after[1],
                "baseline_value": before[0],
                "current_value": after[0],
                "absolute_change": absolute,
                "relative_change": relative,
            }
        )
    if not items:
        raise _CapabilityGap("the governed result contains no registered metric values")
    return {"status": "calculated", "items": items}


def _metric_values(
    kind: str, inputs: Mapping[str, Any], result: Mapping[str, Any]
) -> dict[tuple[str, str, str], tuple[int | float, str]]:
    data = result.get("data")
    if not isinstance(data, Mapping) or set(data) - _DATA_KEYS[kind]:
        raise _CapabilityGap("the result contains unregistered data fields")
    metrics = _metrics(inputs)
    if kind == "event":
        return _event_values(data.get("list"), metrics)
    unique = {(item.field, item.aggregation) for item in metrics}
    if len(unique) != 1:
        raise _CapabilityGap("this result shape cannot attribute values to multiple metrics")
    field, aggregation = next(iter(unique))
    values: dict[tuple[str, str, str], tuple[int | float, str]] = {}
    for root in _METRIC_ROOTS[kind]:
        if root in data:
            _collect_numbers(
                data[root],
                (root,),
                (field, aggregation),
                values,
            )
    return values


def _event_values(
    value: Any, metrics: Sequence[_Metric]
) -> dict[tuple[str, str, str], tuple[int | float, str]]:
    by_index = {item.event_index: item for item in metrics}
    values: dict[tuple[str, str, str], tuple[int | float, str]] = {}

    def visit(item: Any, path: tuple[str | int, ...]) -> None:
        if isinstance(item, Mapping):
            index = item.get("event_index")
            metric = by_index.get(index)
            if metric is not None:
                for name in ("target", "list"):
                    if name in item:
                        _collect_numbers(
                            item[name], path + (name,), (metric.field, metric.aggregation), values
                        )
                return
            for name, child in item.items():
                visit(child, path + (str(name),))
        elif isinstance(item, list):
            for index, child in enumerate(item):
                visit(child, path + (index,))

    visit(value, ("list",))
    return values


def _collect_numbers(
    value: Any,
    path: tuple[str | int, ...],
    metric: tuple[str, str],
    output: dict[tuple[str, str, str], tuple[int | float, str]],
    canonical_path: tuple[str | int, ...] | None = None,
) -> None:
    canonical_path = path if canonical_path is None else canonical_path
    if isinstance(value, (int, float)) and not isinstance(value, bool) and not _number(value):
        raise _CapabilityGap("a registered metric path contains a non-finite value")
    if _number(value):
        canonical = _pointer(canonical_path)
        key = (metric[0], metric[1], canonical)
        if key in output:
            raise _CapabilityGap("a metric path is ambiguous within one window")
        output[key] = (value, _pointer(path))
        return
    if isinstance(value, Mapping):
        date_order = {key: index for index, key in enumerate(sorted(
            (str(key) for key in value if _DATE_KEY.fullmatch(str(key)))
        ))}
        for key, child in value.items():
            rendered = str(key)
            segment = f"@date:{date_order[rendered]}" if rendered in date_order else rendered
            _collect_numbers(
                child,
                path + (rendered,),
                metric,
                output,
                canonical_path + (segment,),
            )
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _collect_numbers(
                child, path + (index,), metric, output, canonical_path + (index,)
            )


def _metrics(inputs: Mapping[str, Any]) -> tuple[_Metric, ...]:
    items = inputs.get("query_item_list")
    if not isinstance(items, Sequence) or isinstance(items, (str, bytes)):
        raise _CapabilityGap("the compiled spec has no registered physical metrics")
    result = []
    for index, item in enumerate(items):
        target = item.get("target") if isinstance(item, Mapping) else None
        field = target.get("field") if isinstance(target, Mapping) else None
        aggregation = target.get("name") if isinstance(target, Mapping) else None
        if not isinstance(field, str) or not isinstance(aggregation, str):
            raise _CapabilityGap("the compiled metric identity changed shape")
        result.append(_Metric(field, aggregation, int(item.get("event_index", index))))
    return tuple(result)


def _window(
    item: Any, start: str, end: str, operation_id: str
) -> dict[str, Any]:
    outer = item if isinstance(item, Mapping) else {}
    raw = outer.get("data") if isinstance(outer.get("data"), Mapping) else outer
    status = str(raw.get("status", outer.get("status", "error"))).casefold()
    if outer.get("ok") is False or status not in _SUCCESS:
        status = status if status not in _SUCCESS else "error"
    safe = _safe_result(raw, operation_id, status)
    return {
        "start": start,
        "end": end,
        "operation_id": operation_id,
        "ok": status in _SUCCESS,
        "status": status,
        "result": safe,
    }


def _safe_result(value: Mapping[str, Any], operation_id: str, status: str) -> dict[str, Any]:
    allowed = {
        "schema_version", "ok", "status", "operation_id", "contract_version",
        "source", "fetched_at", "schema_fingerprint", "page", "data", "warnings",
    }
    selected = {key: copy.deepcopy(item) for key, item in value.items() if key in allowed}
    selected.update(operation_id=operation_id, status=status, ok=status in _SUCCESS)
    if status not in _SUCCESS:
        error = value.get("error")
        selected["data"] = {}
        selected["error"] = {
            key: copy.deepcopy(item)
            for key, item in (error.items() if isinstance(error, Mapping) else ())
            if key in {"category", "code", "field", "retryable", "retry_after_ms"}
        }
    return selected


def _ordered(value: Any) -> dict[str, Mapping[str, Any]]:
    if not isinstance(value, list):
        raise RuntimeError("Analysis period compare batch returned an invalid result list")
    result = {
        item.get("request_id"): item
        for item in value
        if isinstance(item, Mapping) and item.get("request_id") in {"baseline", "current"}
    }
    if set(result) != {"baseline", "current"}:
        raise RuntimeError("Analysis period compare batch omitted a window result")
    return result


def _same_spec(current: Mapping[str, Any], baseline: Mapping[str, Any]) -> None:
    def semantic(value: Mapping[str, Any]) -> dict[str, Any]:
        return {key: copy.deepcopy(item) for key, item in value.items()
                if key not in {"date_list", "query_id"}}

    if semantic(current) != semantic(baseline):
        raise InputValidationError(
            f"actual value: {actual_value(current)}; " + ("period compare requires exactly the same Analysis spec for both windows"),
            field="spec",
        )


def _workers(value: int) -> None:
    if type(value) is not int or not 1 <= value <= 24:
        raise InputValidationError(f"actual value: {actual_value(value)}; " + ("max_workers must be between 1 and 24"), field="max_workers")


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _pointer(path: Sequence[str | int]) -> str:
    return "/" + "/".join(str(item).replace("~", "~0").replace("/", "~1") for item in path)


def _delta_unavailable(reason: str, *, detail: str | None = None) -> dict[str, Any]:
    result = {"status": "not_calculated", "reason": reason, "items": []}
    if detail:
        result["detail"] = detail
    return result


def _capability_gap(kind: str, detail: str, *, network_called: bool) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "result_source": result_source(GOVERNED_PRODUCT),
        "ok": False,
        "status": "capability_gap",
        "kind": kind,
        "network_called": network_called,
        "windows": {},
        "delta": _delta_unavailable("capability_gap", detail=detail),
        "next_action": "Use a dated Analysis kind with explicitly governed metric paths.",
    }


class _CapabilityGap(RuntimeError):
    pass


__all__ = ["SCHEMA_VERSION", "compare_analysis_periods"]
