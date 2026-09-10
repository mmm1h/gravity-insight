"""Closed inputs and method disclosures for material acquisition aggregation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from typing import Any

from .contracts.envelope_obligations import (
    CompletenessState,
    DataCompleteness,
    DiagnosticEvidence,
    DiagnosticState,
    EnvelopeObligations,
    ExecutionState,
    ExecutionStatus,
    MutationCertainty,
    MutationState,
    SemanticState,
    SemanticValidity,
    serialize_envelope,
)
from .errors import InputValidationError
from .material_performance import (
    normalize_material_apps,
    normalize_material_platforms,
    normalize_material_window,
    normalize_material_workers,
)
from .user_detail_aggregate_contract import normalize_user_detail_aggregate_inputs


SCHEMA_VERSION = "gravity-insight.material-game-performance.v1"
METRICS = ("level", "payment", "duration", "retention")
METHOD = {
    "count": "Sum candidate same-ID rows with CreateTime on each queried calendar date; not matched or distinct users.",
    "platform_scope": "User-side platform discriminator binding is unproven; user metrics are unavailable, candidate aggregates diagnostic only.",
    "auto_window": "Lookback through cutoff, extended to earlier report create_time; delivery bounds are unproven.",
    "types": "Native scalar types only; validate before reduction, never cast strings or retry mixed types.",
    "metrics": "Project-owned count_if bindings; sum requires numeric metadata outside this two-source product.",
    "retention": "Unavailable: no proven retained-cohort observation in these two source contracts.",
    "time": "CreateTime calendar date as returned, without timezone conversion; metrics are current snapshots.",
    "advertising": "Only a unique report row is summarized; duplicate rows and rates are never added.",
}


def normalize_request(
    app_id: str | int,
    material_ids: Sequence[str | int],
    platform: str,
    *,
    start: str | None = None,
    end: str | None = None,
    as_of: str | None = None,
    lookback_days: int = 30,
    metrics: Mapping[str, Any] | None = None,
    object_type: str = "material",
    max_report_pages: int = 100,
    max_user_pages: int = 1_000,
    max_user_items: int = 100_000,
    max_days: int = 90,
    max_workers: int = 6,
) -> dict[str, Any]:
    app = normalize_material_apps([app_id])[0]
    normalize_material_platforms([platform])
    normalize_material_workers(max_workers)
    bounds = {
        "max_report_pages": max_report_pages,
        "max_user_pages": max_user_pages,
        "max_user_items": max_user_items,
        "max_days": max_days,
    }
    _validate_limits(bounds, lookback_days, object_type)
    ids = _material_ids(material_ids)
    start, end, mode = _dates(start, end, as_of, lookback_days)
    normalized_metrics = _metrics(metrics, app, start)
    return {
        "app_id": app,
        "material_ids": ids,
        "platform": platform,
        "object_type": object_type,
        "window": {"start": start, "end": end, "mode": mode},
        "metrics": normalized_metrics,
        "bounds": bounds,
        "max_workers": max_workers,
    }


def _validate_limits(bounds: Mapping[str, int], lookback_days: int, object_type: str) -> None:
    for key, maximum in (
        ("max_report_pages", 1000),
        ("max_user_pages", 1000),
        ("max_user_items", 100000),
        ("max_days", 366),
    ):
        if type(bounds[key]) is not int or not 1 <= bounds[key] <= maximum:
            raise InputValidationError(f"{key} must be between 1 and {maximum}", field=key)
    if type(lookback_days) is not int or not 1 <= lookback_days <= 366:
        raise InputValidationError("lookback_days must be between 1 and 366", field="lookback_days")
    if not isinstance(object_type, str) or object_type not in {"material", "creative", "campaign"}:
        raise InputValidationError("object_type must be material, creative or campaign", field="object_type")


def _material_ids(material_ids: Any) -> list[str | int]:
    if isinstance(material_ids, (str, bytes)) or not isinstance(material_ids, Sequence):
        raise InputValidationError("material_ids must be an array", field="material_ids")
    ids = list(material_ids)
    if (
        not 1 <= len(ids) <= 20
        or any(
            not (
                (type(value) is int and 0 < value < 10**64)
                or (
                    isinstance(value, str)
                    and value.isascii()
                    and value.isdecimal()
                    and 1 <= len(value) <= 64
                    and value[0] != "0"
                )
            )
            for value in ids
        )
        or len({str(value) for value in ids}) != len(ids)
    ):
        raise InputValidationError("Select 1 through 20 unique positive material IDs", field="material_ids")
    return ids


def _dates(start: Any, end: Any, as_of: Any, lookback_days: int) -> tuple[str, str, str]:
    if (start is None) != (end is None):
        raise InputValidationError("start and end must be supplied together", field="start/end")
    cutoff = (date.today() - timedelta(days=1)).isoformat() if as_of is None else as_of
    normalize_material_window(cutoff, cutoff)
    if start is None:
        try:
            start = (date.fromisoformat(cutoff) - timedelta(days=lookback_days - 1)).isoformat()
        except OverflowError:
            raise InputValidationError(
                "lookback exceeds the calendar",
                field="lookback_days",
                next_action="Use a later cutoff or fewer lookback days.",
            ) from None
        end = cutoff
        mode = "candidate"
    else:
        mode = "explicit"
    start, end = normalize_material_window(start, end)
    return start, end, mode


def _metrics(metrics: Any, app: str, start: str) -> dict[str, Any]:
    if not isinstance(metrics, (Mapping, type(None))) or (metrics and set(metrics) - set(METRICS)):
        raise InputValidationError(
            "metrics supports level, payment, duration and retention",
            field="metrics",
            next_action="Use only the documented metric keys; inspect materials game-performance --help.",
        )
    normalized_metrics = {}
    for key, measure in (metrics or {}).items():
        if not isinstance(measure, Mapping):
            raise InputValidationError("metric bindings must be aggregate measure objects", field="metrics")
        normalized_metrics[key] = normalize_user_detail_aggregate_inputs(
            {
                "source": {"app_id": app, "date": start},
                "filters": [],
                "group_by": [],
                "measures": [{**measure, "name": key}],
                "bounds": {"max_pages": 1, "max_items": 100, "max_cells": 200},
            }
        )["measures"][0]
        if normalized_metrics[key]["op"] == "count":
            raise InputValidationError(
                "game metrics require an explicit field binding",
                field="metrics",
                next_action="Use a count_if condition on a contracted scalar field.",
            )
        _numeric_threshold(normalized_metrics[key])
    return normalized_metrics


def _numeric_threshold(measure: Mapping[str, Any]) -> None:
    condition = measure.get("condition", {})
    if condition.get("operator") not in {"GT", "GTE", "LT", "LTE"}:
        return
    if type(condition["values"][0]) not in {int, float}:
        raise InputValidationError(
            "ordered game metric thresholds require native numeric values",
            field="metrics.condition.values",
            next_action="Use a numeric threshold; do not substitute lexical string ordering for numeric meaning.",
        )


def prepare_material_game_performance(*args: Any, **kwargs: Any) -> dict[str, Any]:
    request = normalize_request(*args, **kwargs)
    return _preview_envelope(
        {
            "schema_version": SCHEMA_VERSION,
            "ok": True,
            "status": "needs_source_reads",
            "exit_code": 0,
            "network_called": False,
            "method": dict(METHOD),
            "window": request["window"],
            "bounds": request["bounds"],
            "metric_preflight": {
                name: {
                    "status": "unsupported"
                    if name == "retention"
                    else "needs_observed_types"
                    if name in request["metrics"]
                    else "binding_required",
                    "type_policy": METHOD["types"],
                }
                for name in METRICS
            },
        }
    )


def _preview_envelope(payload: Mapping[str, Any]) -> dict[str, Any]:
    return serialize_envelope(
        payload,
        EnvelopeObligations(
            ExecutionStatus(ExecutionState.NOT_STARTED, "OFFLINE_PREFLIGHT"),
            DataCompleteness(CompletenessState.NOT_APPLICABLE, "SOURCE_NOT_READ"),
            SemanticValidity(SemanticState.UNKNOWN, ("METRIC_BINDINGS_REQUIRE_OBSERVED_TYPES",)),
            DiagnosticEvidence(DiagnosticState.NONE),
            MutationCertainty(MutationState.NOT_APPLICABLE, "READ_ONLY"),
        ),
    )
