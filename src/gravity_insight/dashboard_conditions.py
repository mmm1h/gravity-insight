"""Fail-closed detection of persisted Dashboard page conditions."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .dashboard_snapshot import DASHBOARD_SNAPSHOT_SOURCES
from .errors import (
    ContractChangedError,
    ErrorCode,
    ErrorDetail,
    GravityInsightError,
    LocalIOError,
    exit_code_for_error,
)
from .result_source import GOVERNED_PRODUCT, result_source


SOURCE_FIELD = "data.object.config.filter"
SOURCE_OPERATION = DASHBOARD_SNAPSHOT_SOURCES[-1].operation_id
_SUCCESS_STATUSES = frozenset({"success", "empty", "contract_changed_additive"})
_KNOWN_CODES = frozenset(item.value for item in ErrorCode)


@dataclass(frozen=True)
class DashboardPageConditions:
    """Value-free receipt for the persisted page-condition boundary."""

    operation_id: str
    present: bool
    active: bool
    condition_count: int

    def safe_receipt(self) -> dict[str, Any]:
        return {
            "source_operation": self.operation_id,
            "source_field": SOURCE_FIELD,
            "present": self.present,
            "active": self.active,
            "condition_count": self.condition_count,
            "application_status": (
                "blocked_unproven_merge" if self.active else "not_applicable"
            ),
            "merge_semantics": "unproven" if self.active else "not_required",
        }


def read_dashboard_page_conditions(
    client: Any,
    app_id: str,
    dashboard_id: str,
) -> DashboardPageConditions:
    """Read one default filter and classify only its presence, never its values."""

    try:
        result = client.read(
            SOURCE_OPERATION,
            {"app_id": app_id, "dashboard_id": dashboard_id},
        )
    except GravityInsightError as exc:
        raise _safe_exception(exc.to_error_detail(), SOURCE_OPERATION) from None
    except Exception:
        raise LocalIOError(
            "dashboard page-condition client failed locally",
            next_action="Inspect the local client before retrying this Dashboard.",
        ) from None
    if not isinstance(result, Mapping):
        raise ContractChangedError("dashboard page-condition envelope changed shape")
    status = _status(result)
    if result.get("ok") is False or status not in _SUCCESS_STATUSES:
        if status == "contract_changed":
            raise ContractChangedError("dashboard page-condition contract changed")
        raise _safe_exception(result.get("error"), SOURCE_OPERATION)
    return _classify(_envelope_data(result), SOURCE_OPERATION)


def unsupported_page_condition_error() -> ErrorDetail:
    """Describe the capability gap without exposing persisted filter values."""

    return ErrorDetail.create(
        ErrorCode.UNSUPPORTED,
        "Dashboard page conditions cannot be replayed without proven merge semantics.",
        field=SOURCE_FIELD,
        next_action=(
            "Capture one controlled Web query with conflicting page and chart "
            "conditions, then prove the upstream conflict rule before retrying."
        ),
    )


def page_condition_gap_envelope(
    conditions: DashboardPageConditions,
    *,
    schema_version: str,
    app_id: str,
    dashboard: Mapping[str, Any],
    mode: str,
    start: str,
    end: str,
) -> dict[str, Any]:
    """Return one value-free product envelope for an unprovable replay."""

    detail = unsupported_page_condition_error()
    error = detail.to_dict()
    return {
        "schema_version": schema_version,
        "result_source": result_source(GOVERNED_PRODUCT),
        "ok": False,
        "status": "unsupported",
        "exit_code": exit_code_for_error(detail),
        "total_count": 0,
        "app_id": app_id,
        "dashboard": dict(dashboard),
        "mode": mode,
        "date_range": {"start": start, "end": end, "inclusive": True},
        "page_conditions": conditions.safe_receipt(),
        "charts": [],
        "chart_count": 0,
        "supported_count": 0,
        "unsupported_count": 0,
        "success_count": 0,
        "failure_count": 1,
        "error": error,
        "next_action": error["next_action"],
        "network_called": True,
        "query_executed": False,
    }


def _classify(data: Any, operation_id: str) -> DashboardPageConditions:
    if not isinstance(data, Mapping) or "object" not in data:
        raise ContractChangedError("dashboard page-condition object is missing")
    value = data.get("object")
    if value is None:
        return DashboardPageConditions(operation_id, False, False, 0)
    if not isinstance(value, Mapping):
        raise ContractChangedError("dashboard page-condition object changed shape")
    config = value.get("config")
    if config is None:
        return DashboardPageConditions(operation_id, True, False, 0)
    if not isinstance(config, Mapping):
        raise ContractChangedError("dashboard page-condition config changed shape")
    filters = config.get("filter")
    if filters is None:
        return DashboardPageConditions(operation_id, True, False, 0)
    if not isinstance(filters, list):
        raise ContractChangedError("dashboard page-condition filter changed shape")
    return DashboardPageConditions(operation_id, True, bool(filters), len(filters))


def _envelope_data(value: Mapping[str, Any]) -> Any:
    data = value.get("data")
    if isinstance(data, Mapping) and "status" in data and "data" in data:
        return data.get("data")
    return data


def _safe_exception(value: Any, operation_id: str) -> GravityInsightError:
    raw = value.to_dict() if isinstance(value, ErrorDetail) else value
    raw = raw if isinstance(raw, Mapping) else {}
    code = str(raw.get("code", "")).strip().upper()
    selected = code if code in _KNOWN_CODES else ErrorCode.UPSTREAM_UNAVAILABLE.value
    retry_after = raw.get("retry_after_ms")
    detail = ErrorDetail.create(
        selected,
        "Dashboard page-condition read failed.",
        operation_id=operation_id,
        retry_after_ms=(
            retry_after
            if selected == ErrorCode.RATE_LIMITED.value
            and type(retry_after) is int
            and retry_after >= 0
            else None
        ),
    )
    return GravityInsightError(
        detail.message,
        code=detail.code,
        retry_after_ms=detail.retry_after_ms,
        next_action=detail.next_action,
    )


def _status(value: Mapping[str, Any]) -> str:
    status = value.get("status")
    return status.strip().casefold() if isinstance(status, str) else ""


__all__ = [
    "DashboardPageConditions",
    "SOURCE_FIELD",
    "SOURCE_OPERATION",
    "page_condition_gap_envelope",
    "read_dashboard_page_conditions",
    "unsupported_page_condition_error",
]
