"""Strict, bounded execution of Analysis charts stored in one Dashboard."""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from . import runtime
from .composite_batch import ordered_results, validate_composite_bounds
from .dashboard_artifact import (
    SUBJECT_KINDS,
    CompiledDashboardChart,
    compile_dashboard_chart,
    validate_dashboard_window,
)
from .dashboard_conditions import (
    DashboardPageConditions,
    page_condition_gap_envelope,
    read_dashboard_page_conditions,
)
from .dashboard_snapshot import (
    DASHBOARD_SNAPSHOT_SOURCES, DashboardIdentity, _dashboard_identities,
    _envelope_data, _positive_app_id, _read_tree, _reference, _resolve_dashboard,
)
from .errors import (
    ContractChangedError,
    ErrorCategory,
    ErrorCode,
    ErrorDetail,
    GravityInsightError,
    InputValidationError,
    LocalIOError,
    PaginationError,
    UnsupportedOperationError, exit_code_for_category,
)
from .result_source import GOVERNED_PRODUCT, result_source
from .plan_execution import result_item_count


SCHEMA_VERSION = "gravity-insight.dashboard-analysis.v1"
DEFAULT_CONCURRENCY = 6
MAX_CONCURRENCY = 24
DEFAULT_MAX_CHARTS = 32
HARD_MAX_CHARTS = 64
MIN_ANALYSIS_ITEMS = 3
_DETAIL_OPERATION = DASHBOARD_SNAPSHOT_SOURCES[0].operation_id
_SUCCESS_STATUSES = frozenset({"success", "empty", "contract_changed_additive"})
_KNOWN_CODES = frozenset(item.value for item in ErrorCode)


@dataclass(frozen=True)
class _PreparedDashboard:
    app_id: str
    dashboard: DashboardIdentity
    tree_items: int
    charts: tuple[CompiledDashboardChart | dict[str, Any], ...]
    page_conditions: DashboardPageConditions


def prepare_dashboard_analysis(
    client: Any,
    app_id: str | int,
    ref: str | int,
    *,
    start: str,
    end: str,
    max_charts: int = DEFAULT_MAX_CHARTS,
    max_items: int = 100_000,
) -> dict[str, Any]:
    """Read, resolve, and compile one Dashboard without executing chart queries."""

    state = _prepare(
        client,
        app_id,
        ref,
        start=start,
        end=end,
        max_charts=max_charts,
        max_items=max_items,
    )
    charts = [_prepared_chart(index, value) for index, value in enumerate(state.charts)]
    return _envelope(state, charts, mode="prepare", start=start, end=end)


def run_dashboard_analysis(
    client: Any,
    app_id: str | int,
    ref: str | int,
    *,
    start: str,
    end: str,
    max_workers: int = DEFAULT_CONCURRENCY,
    max_charts: int = DEFAULT_MAX_CHARTS,
    max_items: int = 100_000,
) -> dict[str, Any]:
    """Compile and execute supported Dashboard charts in declaration order."""

    workers = _workers(max_workers)
    state = _prepare(
        client,
        app_id,
        ref,
        start=start,
        end=end,
        max_charts=max_charts,
        max_items=max_items,
    )
    compiled = [
        (index, item)
        for index, item in enumerate(state.charts)
        if isinstance(item, CompiledDashboardChart)
    ]
    remaining = max_items - state.tree_items - len(state.charts)
    if len(compiled) > remaining:
        raise PaginationError("dashboard analysis has insufficient result item budget")
    requests = [_query_request(index, item) for index, item in compiled]
    ordered = _execute(
        client,
        requests,
        workers=workers,
        max_items=remaining,
    ) if requests else []
    by_report = {
        request["request_id"]: result
        for request, result in zip(requests, ordered, strict=True)
    }
    charts = [
        _executed_chart(index, value, by_report)
        for index, value in enumerate(state.charts)
    ]
    used = state.tree_items + len(charts) + sum(
        max(1, result_item_count(chart.get("result")))
        for chart in charts
        if chart.get("query_executed") is True
    )
    if used > max_items:
        raise PaginationError("dashboard analysis exceeded its aggregate item safety bound")
    return _envelope(state, charts, mode="run", start=start, end=end)


def _prepare(
    client: Any,
    app_id: str | int,
    ref: str | int,
    *,
    start: str,
    end: str,
    max_charts: int,
    max_items: int,
) -> _PreparedDashboard:
    selected_app = _positive_app_id(app_id)
    selected_ref = _reference(ref)
    validate_dashboard_window(start, end)
    _, items = validate_composite_bounds(
        1,
        max_items,
        minimum_items=MIN_ANALYSIS_ITEMS,
    )
    cap = _chart_cap(max_charts)
    tree = _read_tree(client, selected_app)
    candidates, tree_items = _dashboard_identities(tree, max_nodes=items - 1)
    dashboard = _resolve_dashboard(candidates, selected_ref)
    page_conditions = read_dashboard_page_conditions(
        client, selected_app, dashboard.dashboard_id
    )
    if page_conditions.active:
        return _PreparedDashboard(selected_app, dashboard, tree_items, (), page_conditions)
    reports = _reports(_read_detail(client, selected_app, dashboard), selected_app, dashboard)
    if len(reports) > cap:
        raise PaginationError("dashboard chart count exceeds the declared max_charts bound")
    if tree_items + len(reports) > items:
        raise PaginationError("dashboard analysis exceeded its aggregate item safety bound")
    charts = tuple(
        _compile_or_isolate(
            client,
            report,
            app_id=selected_app,
            start=start,
            end=end,
        )
        for report in reports
    )
    return _PreparedDashboard(selected_app, dashboard, tree_items, charts, page_conditions)


def _read_detail(
    client: Any,
    app_id: str,
    dashboard: DashboardIdentity,
) -> Mapping[str, Any]:
    try:
        result = client.read(
            _DETAIL_OPERATION,
            {
                "app_id": app_id,
                "id": dashboard.dashboard_id,
                "space_id": dashboard.space_id,
            },
        )
    except GravityInsightError as exc:
        raise _safe_exception(exc.to_error_detail(), "detail") from None
    except Exception:
        raise LocalIOError(
            "dashboard analysis detail client failed locally",
            next_action="Inspect the local Gravity client, then retry the dashboard analysis.",
        ) from None
    if not isinstance(result, Mapping):
        raise ContractChangedError("dashboard detail returned an invalid envelope")
    status = _status(result)
    if result.get("ok") is False or status not in _SUCCESS_STATUSES:
        if status == "contract_changed":
            raise ContractChangedError("dashboard detail contract changed")
        raise _safe_exception(result.get("error"), "detail")
    return result


def _reports(
    detail: Mapping[str, Any],
    app_id: str,
    dashboard: DashboardIdentity,
) -> list[Mapping[str, Any]]:
    data = _envelope_data(detail)
    if not isinstance(data, Mapping):
        raise ContractChangedError("dashboard detail no longer returns an object")
    if data.get("id") is None:
        raise ContractChangedError("dashboard detail no longer returns its required identity")
    for field, expected in (
        ("id", dashboard.dashboard_id),
        ("app_id", app_id),
        ("space_id", dashboard.space_id),
    ):
        value = data.get(field)
        if value is not None and str(value).strip() != expected:
            raise ContractChangedError("dashboard detail identity no longer matches the directory")
    raw = data.get("even_report")
    if raw is None:
        return []
    if not isinstance(raw, list) or any(not isinstance(item, Mapping) for item in raw):
        raise ContractChangedError("dashboard detail returned an invalid chart collection")
    return _unique_reports(raw)


def _unique_reports(raw: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    seen: set[str] = set()
    reports: list[Mapping[str, Any]] = []
    for item in raw:
        identity = _report_identity(item.get("report_id"))
        if identity in seen:
            raise ContractChangedError("dashboard detail returned a duplicate chart identity")
        seen.add(identity)
        reports.append(item)
    return reports


def _report_identity(value: Any) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ContractChangedError("dashboard detail returned an incomplete chart identity")
    identity = str(value).strip()
    if not identity or len(identity) > 256:
        raise ContractChangedError("dashboard detail returned an invalid chart identity")
    return identity


def _compile_or_isolate(
    client: Any,
    report: Mapping[str, Any],
    *,
    app_id: str,
    start: str,
    end: str,
) -> CompiledDashboardChart | dict[str, Any]:
    try:
        return compile_dashboard_chart(
            client,
            report,
            app_id=app_id,
            start=start,
            end=end,
        )
    except (InputValidationError, UnsupportedOperationError) as exc:
        return _unsupported_chart(report, exc)
    except GravityInsightError as exc:
        raise _safe_exception(exc.to_error_detail(), "compiler") from None
    except Exception:
        raise LocalIOError(
            "dashboard chart compiler failed locally",
            next_action="Inspect the local compiler before retrying this dashboard.",
        ) from None


def _unsupported_chart(report: Mapping[str, Any], error: Any) -> dict[str, Any]:
    detail = error if isinstance(error, ErrorDetail) else _safe_compile_error(error)
    subject = report.get("subject")
    return {
        "report_id": _safe_identity(report.get("report_id")),
        "name": _safe_identity(report.get("name"), fallback="Unsupported chart"),
        "subject": _safe_identity(subject, fallback="unsupported"),
        "kind": SUBJECT_KINDS.get(str(subject)),
        "operation_id": None,
        "supported": False,
        "validation_status": "unsupported",
        "date_override_applied": False,
        "limitations": [],
        "error": detail.to_dict(),
    }


def _prepared_chart(
    index: int,
    value: CompiledDashboardChart | Mapping[str, Any],
) -> dict[str, Any]:
    selected = value.safe_summary() if isinstance(value, CompiledDashboardChart) else dict(value)
    return {
        "index": index,
        **selected,
        "query_executed": False,
        "result": None,
    }


def _executed_chart(
    index: int,
    value: CompiledDashboardChart | Mapping[str, Any],
    results: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    prepared = _prepared_chart(index, value)
    if not isinstance(value, CompiledDashboardChart):
        return prepared
    request_id = _request_id(index)
    result = results.get(request_id)
    if not isinstance(result, Mapping):
        return _query_failure(prepared, ErrorDetail.create(
            "BATCH_RESULT_MISSING",
            "Dashboard analysis omitted an expected chart result.",
            category=ErrorCategory.LOCAL,
        ))
    outer_status = _status(result)
    if result.get("ok") is not True:
        return _query_failure(prepared, _safe_query_error(result.get("error"), value.operation_id))
    if outer_status not in _SUCCESS_STATUSES:
        error = _contract_error(value.operation_id) if outer_status == "contract_changed" else _safe_query_error(result.get("error"), value.operation_id)
        return _query_failure(prepared, error)
    native = result.get("data")
    if not isinstance(native, Mapping):
        return _query_failure(prepared, _contract_error(value.operation_id))
    status = _status(native)
    if status not in _SUCCESS_STATUSES:
        error = _contract_error(value.operation_id) if status == "contract_changed" else _safe_query_error(native.get("error"), value.operation_id)
        return _query_failure(prepared, error)
    operation_id = native.get("operation_id")
    if operation_id not in (None, value.operation_id):
        return _query_failure(prepared, _contract_error(value.operation_id))
    safe_native = {
        "schema_version": "gravity-insight.read.v1",
        "operation_id": value.operation_id,
        "ok": True,
        "status": status,
        "data": copy.deepcopy(native.get("data")),
    }
    return {**prepared, "query_executed": True, "result": safe_native, "error": None}


def _execute(
    client: Any,
    requests: Sequence[Mapping[str, Any]],
    *,
    workers: int,
    max_items: int,
) -> list[dict[str, Any]]:
    try:
        raw = runtime.call_batch(
            client,
            requests,
            concurrency=workers,
            max_pages=1,
            max_total_items=max_items,
        )
        return ordered_results(raw, requests, component="dashboard analysis")
    except GravityInsightError as exc:
        raise _safe_exception(exc.to_error_detail(), "batch") from None
    except Exception:
        raise LocalIOError(
            "dashboard analysis batch client failed locally",
            next_action="Inspect the local Gravity client, then retry the dashboard analysis.",
        ) from None


def _query_request(index: int, chart: CompiledDashboardChart) -> dict[str, Any]:
    return {
        "operation_id": chart.operation_id,
        "request_id": _request_id(index),
        "inputs": copy.deepcopy(chart.inputs),
        "read_all": False,
    }


def _request_id(index: int) -> str:
    return f"chart-{index}"


def _query_failure(chart: Mapping[str, Any], detail: ErrorDetail) -> dict[str, Any]:
    return {
        **dict(chart),
        "query_executed": True,
        "result": None,
        "error": detail.to_dict(),
    }


def _envelope(
    state: _PreparedDashboard,
    charts: Sequence[Mapping[str, Any]],
    *,
    mode: str,
    start: str,
    end: str,
) -> dict[str, Any]:
    if state.page_conditions.active:
        return page_condition_gap_envelope(
            state.page_conditions, schema_version=SCHEMA_VERSION,
            app_id=state.app_id, dashboard=state.dashboard.to_dict(),
            mode=mode, start=start, end=end,
        )
    supported = sum(item.get("supported") is True for item in charts)
    unsupported = len(charts) - supported
    successes = sum(item.get("query_executed") is True and item.get("error") is None for item in charts)
    query_failures = sum(
        item.get("query_executed") is True and item.get("error") is not None
        for item in charts
    )
    failures = query_failures + (unsupported if mode == "run" else 0)
    error = _highest_error(charts, include_unsupported=mode == "run") if failures else None
    status = "partial" if failures else "prepared" if mode == "prepare" else "success"
    return {
        "schema_version": SCHEMA_VERSION,
        "result_source": result_source(GOVERNED_PRODUCT),
        "ok": not failures,
        "status": status,
        "exit_code": _exit_code(error),
        "total_count": len(charts),
        "app_id": state.app_id,
        "dashboard": state.dashboard.to_dict(),
        "mode": mode,
        "date_range": {"start": start, "end": end, "inclusive": True},
        "page_conditions": state.page_conditions.safe_receipt(),
        "charts": list(charts),
        "chart_count": len(charts),
        "supported_count": supported,
        "unsupported_count": unsupported,
        "success_count": successes,
        "failure_count": failures,
        "error": error,
        "next_action": (
            "Consume successful chart results and inspect isolated failures."
            if failures
            else "Unsupported charts remain isolated; consume only governed chart results."
        ),
        "network_called": True,
        "query_executed": mode == "run" and bool(successes or failures),
    }


def _highest_error(
    charts: Sequence[Mapping[str, Any]], *, include_unsupported: bool
) -> dict[str, Any] | None:
    details = [
        item.get("error")
        for item in charts
        if isinstance(item.get("error"), Mapping)
        and (item.get("query_executed") is True or include_unsupported)
    ]
    if not details:
        return None
    return copy.deepcopy(max(details, key=_exit_code))


def _safe_compile_error(error: GravityInsightError) -> ErrorDetail:
    code = str(error.code.value if isinstance(error.code, ErrorCode) else error.code)
    selected = code if code in _KNOWN_CODES else ErrorCode.UNSUPPORTED.value
    return ErrorDetail.create(
        selected,
        "Dashboard chart cannot be compiled through a proven stable contract.",
        field="report.config",
        next_action="Keep this chart unsupported until its Web artifact contract is proven.",
    )


def _safe_query_error(value: Any, operation_id: str) -> ErrorDetail:
    raw = value if isinstance(value, Mapping) else {}
    code = str(raw.get("code", "")).strip().upper()
    selected = code if code in _KNOWN_CODES or code == "BATCH_RESULT_MISSING" else ErrorCode.LOCAL_IO_ERROR.value
    retry_after = raw.get("retry_after_ms")
    return ErrorDetail.create(
        selected,
        "Dashboard chart query failed.",
        operation_id=operation_id,
        retry_after_ms=retry_after if selected == ErrorCode.RATE_LIMITED.value and type(retry_after) is int and retry_after >= 0 else None,
    )


def _contract_error(operation_id: str) -> ErrorDetail:
    return ErrorDetail.create(
        ErrorCode.CONTRACT_CHANGED,
        "Dashboard chart query result contract changed.",
        operation_id=operation_id,
    )


def _safe_exception(value: Any, component: str) -> GravityInsightError:
    raw = value.to_dict() if isinstance(value, ErrorDetail) else value
    raw = raw if isinstance(raw, Mapping) else {}
    code = str(raw.get("code", "")).strip().upper()
    selected = code if code in _KNOWN_CODES else ErrorCode.UPSTREAM_UNAVAILABLE.value
    detail = ErrorDetail.create(selected, f"Dashboard analysis {component} read failed.")
    return GravityInsightError(detail.message, code=detail.code, next_action=detail.next_action)


def _safe_identity(value: Any, *, fallback: str = "unknown") -> str:
    if isinstance(value, (str, int)) and not isinstance(value, bool):
        rendered = str(value).strip()
        if 0 < len(rendered) <= 512:
            return rendered
    return fallback


def _workers(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_CONCURRENCY:
        raise InputValidationError(
            f"dashboard analysis max_workers must be between 1 and {MAX_CONCURRENCY}",
            field="max_workers",
        )
    return value


def _chart_cap(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= HARD_MAX_CHARTS:
        raise InputValidationError(
            f"max_charts must be between 1 and {HARD_MAX_CHARTS}",
            field="max_charts",
        )
    return value


def _status(value: Mapping[str, Any]) -> str:
    status = value.get("status")
    return status.strip().casefold() if isinstance(status, str) else ""


def _exit_code(error: Mapping[str, Any] | None) -> int:
    return 0 if error is None else exit_code_for_category(str(error.get("category")), default=ErrorCategory.LOCAL)


__all__ = [
    "DEFAULT_CONCURRENCY",
    "DEFAULT_MAX_CHARTS",
    "HARD_MAX_CHARTS",
    "MIN_ANALYSIS_ITEMS",
    "SCHEMA_VERSION",
    "prepare_dashboard_analysis",
    "run_dashboard_analysis",
]
